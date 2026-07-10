"""Storage: SQLite behind a thin repository interface.

Design rationale: no premature infrastructure. Everything the funnel,
harness and API persist goes through this one class, so the documented
Postgres upgrade is a reimplementation of ~10 methods, not a refactor.
Calibration records are append-only (audit trail); predictions and outcomes
are keyed so the harness can join them.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

_audit_logger = logging.getLogger("creativegate.audit")

from ..schemas import (
    CalibrationRecord,
    EvaluationProfile,
    GroundTruthRecord,
    GroundTruthSet,
    Verdict,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS predictions (
    rung TEXT NOT NULL,
    artifact_ref TEXT NOT NULL,
    segment TEXT NOT NULL,
    modality TEXT NOT NULL,
    metric TEXT NOT NULL,
    predicted REAL NOT NULL,
    verdict_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (rung, artifact_ref, metric)
);
CREATE TABLE IF NOT EXISTS outcomes (
    artifact_ref TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    segment TEXT NOT NULL,
    modality TEXT NOT NULL,
    quality TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (artifact_ref, metric)
);
CREATE TABLE IF NOT EXISTS calibrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rung TEXT NOT NULL,
    segment TEXT NOT NULL,
    modality TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS verdicts (
    id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ground_truth_sets (
    name TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    modality TEXT NOT NULL,
    text TEXT,
    segment TEXT NOT NULL,
    created_at TEXT NOT NULL,
    path TEXT
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    verdict_id TEXT,
    error TEXT,
    webhook_url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    subject TEXT NOT NULL,
    detail TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    name TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# The job lifecycle is a real state machine; illegal transitions are bugs
# and must fail loudly rather than silently corrupt history.
VALID_JOB_TRANSITIONS: dict[str, set[str]] = {
    "queued": {"running", "error", "interrupted"},
    "running": {"done", "error", "interrupted"},
    "done": set(),
    "error": set(),
    "interrupted": set(),
}

# Idempotent migrations for databases created before a column existed.
_MIGRATIONS = [
    "ALTER TABLE artifacts ADD COLUMN path TEXT",
]


class Repository:
    def __init__(self, db_path: str | Path = "creativegate.db"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        for migration in _MIGRATIONS:
            try:
                self._conn.execute(migration)
            except sqlite3.OperationalError:
                pass  # column already exists
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # -- predictions ---------------------------------------------------------

    def save_prediction(self, rung: str, artifact_ref: str, segment: str,
                        modality: str, metric: str, predicted: float,
                        verdict_id: Optional[str]) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO predictions VALUES (?,?,?,?,?,?,?,?)",
            (rung, artifact_ref, segment, modality, metric, predicted,
             verdict_id, datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    # -- outcomes ------------------------------------------------------------

    def save_outcome(self, record: GroundTruthRecord) -> None:
        for metric, value in record.outcomes.items():
            self._conn.execute(
                "INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?,?,?)",
                (record.artifact_ref, metric, value, record.segment,
                 record.modality.value, record.outcome_quality.value,
                 record.timestamp.isoformat()),
            )
        self._conn.commit()

    def affected_cells(self, artifact_refs: list[str]) -> list[tuple[str, str, str, str]]:
        """(rung, segment, modality, metric) cells with new prediction/outcome joins."""
        qmarks = ",".join("?" * len(artifact_refs))
        rows = self._conn.execute(
            f"""SELECT DISTINCT p.rung, p.segment, p.modality, p.metric
                FROM predictions p JOIN outcomes o
                  ON p.artifact_ref = o.artifact_ref AND p.metric = o.metric
                WHERE o.artifact_ref IN ({qmarks})""",
            artifact_refs,
        ).fetchall()
        return [tuple(r) for r in rows]

    def prediction_outcome_pairs(self, rung: str, segment: str, modality: str,
                                 metric: str) -> list[tuple[float, float]]:
        rows = self._conn.execute(
            """SELECT p.predicted, o.value
               FROM predictions p JOIN outcomes o
                 ON p.artifact_ref = o.artifact_ref AND p.metric = o.metric
               WHERE p.rung=? AND p.segment=? AND p.modality=? AND p.metric=?""",
            (rung, segment, modality, metric),
        ).fetchall()
        return [(float(p), float(o)) for p, o in rows]

    # -- calibrations (append-only audit trail) -------------------------------

    def save_calibration(self, record: CalibrationRecord) -> None:
        self._conn.execute(
            "INSERT INTO calibrations (rung, segment, modality, payload, updated_at) VALUES (?,?,?,?,?)",
            (record.rung, record.segment, record.modality,
             record.model_dump_json(), record.updated_at.isoformat()),
        )
        self._conn.commit()

    def latest_calibration(self, rung: str, segment: str, modality: str) -> Optional[CalibrationRecord]:
        row = self._conn.execute(
            """SELECT payload FROM calibrations
               WHERE rung=? AND segment=? AND modality=?
               ORDER BY id DESC LIMIT 1""",
            (rung, segment, modality),
        ).fetchone()
        return CalibrationRecord.model_validate_json(row[0]) if row else None

    def calibrations_for_rung(self, rung: str) -> list[CalibrationRecord]:
        rows = self._conn.execute(
            "SELECT payload FROM calibrations WHERE rung=? ORDER BY id", (rung,)
        ).fetchall()
        return [CalibrationRecord.model_validate_json(r[0]) for r in rows]

    def all_calibrations(self) -> list[CalibrationRecord]:
        """Full audit trail across every rung, in insertion order."""
        rows = self._conn.execute(
            "SELECT payload FROM calibrations ORDER BY id"
        ).fetchall()
        return [CalibrationRecord.model_validate_json(r[0]) for r in rows]

    # -- verdicts --------------------------------------------------------------

    def save_verdict(self, verdict: Verdict) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO verdicts VALUES (?,?,?,?)",
            (verdict.id, verdict.artifact_id, verdict.model_dump_json(),
             verdict.created_at.isoformat()),
        )
        self._conn.commit()

    def get_verdict(self, verdict_id: str) -> Optional[Verdict]:
        row = self._conn.execute(
            "SELECT payload FROM verdicts WHERE id=?", (verdict_id,)
        ).fetchone()
        return Verdict.model_validate_json(row[0]) if row else None

    def list_verdicts(self, limit: int = 50) -> list[Verdict]:
        rows = self._conn.execute(
            "SELECT payload FROM verdicts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [Verdict.model_validate_json(r[0]) for r in rows]

    # -- artifacts (text payloads for dashboard preview) -----------------------

    def save_artifact(self, artifact_id: str, modality: str, text: Optional[str],
                      segment: str, path: Optional[str] = None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?,?,?)",
            (artifact_id, modality, text, segment,
             datetime.now(timezone.utc).isoformat(), path),
        )
        self._conn.commit()

    def get_artifact(self, artifact_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT id, modality, text, segment, path FROM artifacts WHERE id=?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "modality": row[1], "text": row[2], "segment": row[3], "path": row[4]}

    # -- audit log (operational event history, append-only) --------------------

    def append_event(self, event: str, subject: str, **detail) -> None:
        """One timestamped line of operational history. Append-only; the
        detail payload carries inputs/outputs references (ids, counts,
        scores) — full artifacts/verdicts live in their own tables."""
        payload = json.dumps(detail, default=str)
        self._conn.execute(
            "INSERT INTO audit_log (ts, event, subject, detail) VALUES (?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), event, subject, payload),
        )
        self._conn.commit()
        _audit_logger.info("event=%s subject=%s detail=%s", event, subject, payload)

    def recent_events(self, limit: int = 100, subject: Optional[str] = None,
                      event_prefix: Optional[str] = None) -> list[dict]:
        query = "SELECT ts, event, subject, detail FROM audit_log"
        clauses, params = [], []
        if subject:
            clauses.append("subject = ?")
            params.append(subject)
        if event_prefix:
            clauses.append("event LIKE ?")
            params.append(event_prefix + "%")
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(query, params).fetchall()
        return [{"ts": ts, "event": ev, "subject": subj, "detail": json.loads(det)}
                for ts, ev, subj, det in rows]

    # -- jobs (durable async-evaluation state) ---------------------------------

    def create_job(self, job_id: str, webhook_url: Optional[str] = None,
                   artifact_id: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
            (job_id, "queued", None, None, webhook_url, now, now),
        )
        self._conn.commit()
        self.append_event("job.queued", job_id, artifact_id=artifact_id,
                          webhook=bool(webhook_url))

    def update_job(self, job_id: str, status: str, verdict_id: Optional[str] = None,
                   error: Optional[str] = None) -> None:
        row = self._conn.execute(
            "SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown job '{job_id}'")
        current = row[0]
        if status not in VALID_JOB_TRANSITIONS.get(current, set()):
            raise ValueError(
                f"Illegal job transition '{current}' -> '{status}' for {job_id}")
        self._conn.execute(
            "UPDATE jobs SET status=?, verdict_id=COALESCE(?, verdict_id), "
            "error=?, updated_at=? WHERE id=?",
            (status, verdict_id, error, datetime.now(timezone.utc).isoformat(), job_id),
        )
        self._conn.commit()
        self.append_event(f"job.{status}", job_id, previous=current,
                          verdict_id=verdict_id, error=error)

    def get_job(self, job_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT id, status, verdict_id, error, webhook_url FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        if row is None:
            return None
        return {"job_id": row[0], "status": row[1], "verdict_id": row[2],
                "error": row[3], "webhook_url": row[4]}

    def mark_stale_jobs_interrupted(self) -> int:
        """Jobs left queued/running by a dead process are truthfully marked
        interrupted at startup instead of appearing to run forever."""
        stale = [r[0] for r in self._conn.execute(
            "SELECT id FROM jobs WHERE status IN ('queued','running')").fetchall()]
        if not stale:
            return 0
        self._conn.execute(
            "UPDATE jobs SET status='interrupted', "
            "error='server restarted before the job finished', updated_at=? "
            "WHERE status IN ('queued','running')",
            (datetime.now(timezone.utc).isoformat(),),
        )
        self._conn.commit()
        self.append_event("jobs.interrupted_sweep", "startup",
                          count=len(stale), job_ids=stale)
        return len(stale)

    # -- profiles (declarative funnel definitions, one per artifact class) ------

    def save_profile(self, profile: "EvaluationProfile") -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO profiles VALUES (?,?,?)",
            (profile.name, profile.model_dump_json(),
             datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def get_profile(self, name: str) -> Optional["EvaluationProfile"]:
        row = self._conn.execute(
            "SELECT payload FROM profiles WHERE name=?", (name,)
        ).fetchone()
        return EvaluationProfile.model_validate_json(row[0]) if row else None

    def list_profile_names(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT name FROM profiles ORDER BY name").fetchall()
        return [r[0] for r in rows]

    # -- ground truth sets ------------------------------------------------------

    def save_ground_truth_set(self, gt: GroundTruthSet) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO ground_truth_sets VALUES (?,?,?)",
            (gt.name, gt.model_dump_json(), datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def get_ground_truth_set(self, name: str) -> Optional[GroundTruthSet]:
        row = self._conn.execute(
            "SELECT payload FROM ground_truth_sets WHERE name=?", (name,)
        ).fetchone()
        return GroundTruthSet.model_validate_json(row[0]) if row else None

    def latest_ground_truth_set(self) -> Optional[GroundTruthSet]:
        row = self._conn.execute(
            "SELECT payload FROM ground_truth_sets ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return GroundTruthSet.model_validate_json(row[0]) if row else None

    def list_ground_truth_sets(self) -> list[tuple[str, int]]:
        rows = self._conn.execute(
            "SELECT name, payload FROM ground_truth_sets ORDER BY updated_at DESC"
        ).fetchall()
        return [(name, len(GroundTruthSet.model_validate_json(p).records)) for name, p in rows]

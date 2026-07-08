"""Storage: SQLite behind a thin repository interface.

Design rationale: no premature infrastructure. Everything the funnel,
harness and API persist goes through this one class, so the documented
Postgres upgrade is a reimplementation of ~10 methods, not a refactor.
Calibration records are append-only (audit trail); predictions and outcomes
are keyed so the harness can join them.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..schemas import (
    CalibrationRecord,
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
    created_at TEXT NOT NULL
);
"""


class Repository:
    def __init__(self, db_path: str | Path = "creativegate.db"):
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
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
                      segment: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO artifacts VALUES (?,?,?,?,?)",
            (artifact_id, modality, text, segment,
             datetime.now(timezone.utc).isoformat()),
        )
        self._conn.commit()

    def get_artifact(self, artifact_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT id, modality, text, segment FROM artifacts WHERE id=?", (artifact_id,)
        ).fetchone()
        if row is None:
            return None
        return {"id": row[0], "modality": row[1], "text": row[2], "segment": row[3]}

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

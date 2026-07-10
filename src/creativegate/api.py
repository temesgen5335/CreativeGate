"""CreativeGate API.

Design rationale: API-first — agentic pipelines gate their own outputs
through these endpoints, and the dashboard SPA at ``GET /`` is just another
API client. Production posture without premature infrastructure:

- **Durable jobs**: evaluation jobs live in the jobs table, not process
  memory; a restart marks orphans "interrupted" instead of losing them.
  Optional per-job webhook fires on completion (best-effort).
- **Token auth, keyless-degradation style**: set ``CREATIVEGATE_API_TOKEN``
  and every mutating endpoint requires ``Authorization: Bearer <token>``;
  leave it unset and the API is open for local development. Reads stay open.
- **Artifact store**: ``POST /artifacts`` uploads text/image payloads to a
  filesystem store next to the database; ``POST /evaluate`` can then
  reference them by id.
"""

from __future__ import annotations

import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import __version__
from .calibration import CalibrationHarness
from .engine import FunnelEngine
from .profiles import default_profile
from .report import render_verdict_report
from .schemas import Artifact, EvaluationProfile, GroundTruthRecord, GroundTruthSet, Modality
from .storage import Repository

_repo: Optional[Repository] = None
DEFAULT_PROFILE_NAME = "default-text-v0.1"

_UPLOAD_EXTENSIONS = {".txt": Modality.TEXT, ".png": Modality.IMAGE,
                      ".jpg": Modality.IMAGE, ".jpeg": Modality.IMAGE}


def get_repo() -> Repository:
    global _repo
    if _repo is None:
        _repo = Repository(os.environ.get("CREATIVEGATE_DB", "creativegate.db"))
    return _repo


def artifact_dir() -> Path:
    configured = os.environ.get("CREATIVEGATE_ARTIFACT_DIR")
    path = Path(configured) if configured else Path(get_repo().db_path + ".artifacts")
    path.mkdir(parents=True, exist_ok=True)
    return path


def require_token(authorization: Optional[str] = Header(None)) -> None:
    """Bearer-token gate for mutating endpoints. Unset token = open dev mode."""
    token = os.environ.get("CREATIVEGATE_API_TOKEN")
    if not token:
        return
    if authorization != f"Bearer {token}":
        raise HTTPException(401, "Missing or invalid bearer token.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    interrupted = get_repo().mark_stale_jobs_interrupted()
    if interrupted:
        import logging
        logging.getLogger("creativegate").warning(
            "marked %d orphaned job(s) as interrupted at startup", interrupted)
    yield


app = FastAPI(
    title="CreativeGate",
    version=__version__,
    description="A simulation-first evaluation funnel for creative artifacts: evaluate before you spend.",
    lifespan=lifespan,
)

_cors = os.environ.get("CREATIVEGATE_CORS_ORIGINS", "")
if _cors:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _cors.split(",") if o.strip()],
        allow_methods=["*"], allow_headers=["*"],
    )


def get_profile(name: Optional[str]) -> EvaluationProfile:
    """Resolve a profile by name: stored profiles win, the shipped default
    backs the default name. Criteria per artifact class = one profile each."""
    if name is None:
        name = DEFAULT_PROFILE_NAME
    stored = get_repo().get_profile(name)
    if stored is not None:
        return stored
    if name == DEFAULT_PROFILE_NAME:
        return default_profile()
    known = sorted(set(get_repo().list_profile_names()) | {DEFAULT_PROFILE_NAME})
    raise HTTPException(404, f"Unknown profile '{name}'. Known: {known}")


class EvaluateRequest(BaseModel):
    artifact_id: str = Field(default_factory=lambda: f"a-{uuid.uuid4().hex[:8]}")
    modality: Modality = Modality.TEXT
    text: Optional[str] = None
    segment: str = "default"
    platform: str = "default"
    profile: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    webhook_url: Optional[str] = None    # POSTed {job_id, status, verdict_id} on completion


class JobResponse(BaseModel):
    job_id: str
    status: str
    verdict_id: Optional[str] = None


def _fire_webhook(url: str, payload: dict) -> None:
    try:
        httpx.post(url, json=payload, timeout=5.0)
    except Exception:
        pass  # best-effort by contract; the job row remains the source of truth


def _run_job(job_id: str, req: EvaluateRequest) -> None:
    repo = get_repo()
    try:
        repo.update_job(job_id, "running")
        profile = get_profile(req.profile)
        harness = CalibrationHarness(repo)
        # Convenience for the DEFAULT profile only: fall back to the most
        # recently stored set so a freshly-uploaded corpus works without
        # profile editing. Custom profiles name their corpus explicitly —
        # a missing set means the learned rungs refuse, which is honest;
        # silently training banner criteria on storyboard outcomes is not.
        gt = repo.get_ground_truth_set(profile.ground_truth_set)
        if gt is None and profile.name == DEFAULT_PROFILE_NAME:
            gt = repo.latest_ground_truth_set()
        engine = FunnelEngine(profile, ground_truth=gt, harness=harness)

        text, modality, path = req.text, req.modality, None
        stored = repo.get_artifact(req.artifact_id)
        if req.text is None and stored is not None:
            # Evaluate a previously-uploaded artifact by reference.
            text = stored["text"]
            modality = Modality(stored["modality"])
            path = stored.get("path")
        else:
            repo.save_artifact(req.artifact_id, modality.value, text, req.segment)

        artifact = Artifact(
            id=req.artifact_id, modality=modality, text=text, path=path,
            segment=req.segment, platform=req.platform, metadata=req.metadata,
        )
        verdict = engine.evaluate(artifact)
        repo.save_verdict(verdict)
        repo.append_event(
            "verdict.stored", verdict.id,
            artifact_id=artifact.id, profile=verdict.profile_name,
            config_hash=verdict.config_hash, eliminated=verdict.eliminated,
            eliminated_by=verdict.eliminated_by, score=verdict.score,
            flags=len(verdict.flags), runtime_ms=verdict.runtime_ms,
        )
        repo.update_job(job_id, "done", verdict_id=verdict.id)
        if req.webhook_url:
            _fire_webhook(req.webhook_url,
                          {"job_id": job_id, "status": "done", "verdict_id": verdict.id})
    except Exception as e:  # surfaced to the poller, never swallowed
        try:
            repo.update_job(job_id, "error", error=str(e))
        except Exception:
            pass  # job row already terminal/missing; the audit log has the story
        if req.webhook_url:
            _fire_webhook(req.webhook_url,
                          {"job_id": job_id, "status": "error", "error": str(e)})


@app.post("/evaluate", response_model=JobResponse, dependencies=[Depends(require_token)])
def evaluate(req: EvaluateRequest, background: BackgroundTasks) -> JobResponse:
    job_id = f"job-{uuid.uuid4().hex[:12]}"
    get_repo().create_job(job_id, webhook_url=req.webhook_url, artifact_id=req.artifact_id)
    background.add_task(_run_job, job_id, req)
    return JobResponse(job_id=job_id, status="queued")


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = get_repo().get_job(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job.")
    job.pop("webhook_url", None)
    return job


@app.post("/artifacts", dependencies=[Depends(require_token)])
async def upload_artifact(file: UploadFile = File(...), segment: str = "default") -> dict:
    """Upload a creative payload (.txt/.png/.jpg) into the artifact store.

    Returns an artifact_id usable in POST /evaluate. Text is stored inline;
    images go to the filesystem store so the deterministic gate can check
    structure (and the saliency rung can read pixels in v0.2).
    """
    ext = Path(file.filename or "").suffix.lower()
    if ext not in _UPLOAD_EXTENSIONS:
        raise HTTPException(415, f"Unsupported extension '{ext}'. Allowed: {sorted(_UPLOAD_EXTENSIONS)}")
    max_mb = float(os.environ.get("CREATIVEGATE_MAX_UPLOAD_MB", "25"))
    data = await file.read()
    if len(data) > max_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds the {max_mb:.0f} MB upload limit.")

    modality = _UPLOAD_EXTENSIONS[ext]
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(file.filename or "artifact").stem)[:48]
    artifact_id = f"{stem}-{uuid.uuid4().hex[:6]}"
    repo = get_repo()
    if modality == Modality.TEXT:
        repo.save_artifact(artifact_id, modality.value,
                           data.decode("utf-8", errors="replace").strip(), segment)
        path = None
    else:
        path = artifact_dir() / f"{artifact_id}{ext}"
        path.write_bytes(data)
        repo.save_artifact(artifact_id, modality.value, None, segment, path=str(path))
    repo.append_event("artifact.uploaded", artifact_id,
                      filename=file.filename, modality=modality.value, bytes=len(data))
    return {"artifact_id": artifact_id, "modality": modality.value,
            "bytes": len(data), "stored_path": str(path) if path else None}


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    """The CreativeGate dashboard SPA (home / ingest / dashboard / calibration)."""
    page = Path(__file__).parent / "report" / "dashboard.html"
    return page.read_text()


@app.get("/verdicts")
def list_verdicts(limit: int = 50) -> dict:
    """Recent verdicts, newest first, with artifact text for preview."""
    repo = get_repo()
    out = []
    for v in repo.list_verdicts(limit=min(limit, 200)):
        artifact = repo.get_artifact(v.artifact_id)
        out.append({
            "verdict": v.model_dump(mode="json"),
            "artifact": artifact,
        })
    return {"verdicts": out}


@app.get("/artifact/{artifact_id}")
def get_artifact(artifact_id: str) -> dict:
    artifact = get_repo().get_artifact(artifact_id)
    if artifact is None:
        raise HTTPException(404, "Unknown artifact.")
    return artifact


@app.get("/calibration")
def calibration_overview() -> dict:
    """Full calibration audit trail grouped by rung — drives the harness view."""
    records = get_repo().all_calibrations()
    by_rung: dict[str, list[dict]] = {}
    for r in records:
        by_rung.setdefault(r.rung, []).append(r.model_dump(mode="json"))
    return {"rungs": by_rung, "total_records": len(records)}


@app.get("/verdict/{verdict_id}")
def get_verdict(verdict_id: str) -> dict:
    verdict = get_repo().get_verdict(verdict_id)
    if verdict is None:
        raise HTTPException(404, "Unknown verdict.")
    return verdict.model_dump(mode="json")


@app.get("/verdict/{verdict_id}/report", response_class=HTMLResponse)
def get_verdict_report(verdict_id: str) -> str:
    verdict = get_repo().get_verdict(verdict_id)
    if verdict is None:
        raise HTTPException(404, "Unknown verdict.")
    return render_verdict_report(verdict)


class GroundTruthIngest(BaseModel):
    records: list[GroundTruthRecord]


@app.post("/ground-truth", dependencies=[Depends(require_token)])
def ingest_ground_truth(body: GroundTruthIngest) -> dict:
    """Ingest real outcomes; triggers recalibration of every affected rung cell."""
    repo = get_repo()
    harness = CalibrationHarness(repo)
    updated = harness.ingest_outcomes(body.records)
    repo.append_event(
        "ground_truth.ingested", f"{len(body.records)} records",
        artifact_refs=[r.artifact_ref for r in body.records[:20]],
        recalibrated=[f"{r.rung}/{r.segment}/{r.modality} r={r.spearman:.2f} n={r.n}"
                      for r in updated],
    )
    for r in updated:
        if r.drift_detected:
            repo.append_event(
                "calibration.drift", f"{r.rung}/{r.segment}/{r.modality}",
                previous_spearman=r.previous_spearman, spearman=r.spearman, n=r.n)
    return {
        "ingested": len(body.records),
        "recalibrated": [r.model_dump(mode="json") for r in updated],
    }


@app.post("/ground-truth-sets", dependencies=[Depends(require_token)])
def create_ground_truth_set(gt: GroundTruthSet) -> dict:
    """Store a named ground-truth corpus: artifacts with known outcomes.

    This is what the performance predictor trains on and the judge draws its
    pairwise anchors from. Bring real ads with measured CTRs. Storing a set
    does NOT create calibration records — rungs still have to earn fusion
    weight by predicting outcomes that are later reported to /ground-truth.
    """
    usable = [r for r in gt.records if r.text and gt.target_metric in r.outcomes]
    if len(usable) < 2:
        raise HTTPException(422, "Need at least 2 records with text and the target metric "
                                 "(2+ enables judge anchors; 10+ enables the predictor).")
    get_repo().save_ground_truth_set(gt)
    get_repo().append_event("ground_truth_set.stored", gt.name,
                            records=len(gt.records), usable=len(usable),
                            target_metric=gt.target_metric)
    warnings = []
    if len(usable) < 10:
        warnings.append(f"Only {len(usable)} usable records: the predictor refuses below 10 "
                        "and will contribute evidence only.")
    return {"name": gt.name, "records": len(gt.records),
            "usable": len(usable), "target_metric": gt.target_metric,
            "warnings": warnings}


@app.get("/ground-truth-sets")
def list_ground_truth_sets() -> dict:
    return {"sets": [{"name": n, "records": c} for n, c in get_repo().list_ground_truth_sets()]}


@app.get("/calibration/{rung}")
def calibration_report(rung: str) -> dict:
    return CalibrationHarness(get_repo()).report(rung).model_dump(mode="json")


@app.get("/profiles")
def list_profiles() -> dict:
    names = sorted(set(get_repo().list_profile_names()) | {DEFAULT_PROFILE_NAME})
    return {"profiles": names}


@app.get("/profiles/{name}")
def get_profile_detail(name: str) -> dict:
    """Full declarative definition of a profile: rungs, thresholds, configs,
    fusion policy — the exact configuration a verdict's config_hash refers to."""
    profile = get_profile(name)
    return {**profile.model_dump(mode="json"), "config_hash": profile.config_hash()}


@app.post("/profiles", dependencies=[Depends(require_token)])
def create_profile(profile: EvaluationProfile) -> dict:
    """Store (or replace) a named profile — the criteria for one artifact
    class: gate rules, thresholds, judge rubric/anchors, and which
    ground-truth set the learned rungs derive quality from."""
    if profile.name == DEFAULT_PROFILE_NAME:
        raise HTTPException(409, "The shipped default profile is immutable; pick a new name.")
    repo = get_repo()
    repo.save_profile(profile)
    repo.append_event("profile.created", profile.name,
                      config_hash=profile.config_hash(),
                      ground_truth_set=profile.ground_truth_set)
    return {"name": profile.name, "config_hash": profile.config_hash()}


@app.get("/audit")
def audit_trail(limit: int = 100, subject: Optional[str] = None,
                event: Optional[str] = None) -> dict:
    """Operational event history, newest first: job transitions, verdicts,
    uploads, ground-truth ingestions, drift alarms. Filter by exact subject
    (e.g. a job or verdict id) or event prefix (e.g. 'job.' or 'calibration.')."""
    events = get_repo().recent_events(
        limit=min(limit, 500), subject=subject, event_prefix=event)
    return {"events": events, "count": len(events)}


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        "auth": "token" if os.environ.get("CREATIVEGATE_API_TOKEN") else "open",
    }

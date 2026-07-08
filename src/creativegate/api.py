"""CreativeGate API (v0.1 minimal surface).

Design rationale: API-first — agentic pipelines gate their own outputs
through these endpoints. v0.1 keeps the async job model simple: an
in-process job registry with background execution; webhooks and a durable
queue are the documented upgrade, not a prerequisite for correctness.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import __version__
from .calibration import CalibrationHarness
from .engine import FunnelEngine
from .profiles import default_profile
from .report import render_verdict_report
from .schemas import Artifact, EvaluationProfile, GroundTruthRecord, Modality
from .storage import Repository

app = FastAPI(
    title="CreativeGate",
    version=__version__,
    description="A simulation-first evaluation funnel for creative artifacts: evaluate before you spend.",
)

_repo: Optional[Repository] = None
_jobs: dict[str, dict[str, Any]] = {}
_profiles: dict[str, EvaluationProfile] = {}


def get_repo() -> Repository:
    global _repo
    if _repo is None:
        _repo = Repository(os.environ.get("CREATIVEGATE_DB", "creativegate.db"))
    return _repo


def get_profile(name: Optional[str]) -> EvaluationProfile:
    if name is None or name == "default-text-v0.1":
        return _profiles.get("default-text-v0.1", default_profile())
    if name in _profiles:
        return _profiles[name]
    raise HTTPException(404, f"Unknown profile '{name}'. Known: {sorted(_profiles) + ['default-text-v0.1']}")


class EvaluateRequest(BaseModel):
    artifact_id: str = Field(default_factory=lambda: f"a-{uuid.uuid4().hex[:8]}")
    modality: Modality = Modality.TEXT
    text: Optional[str] = None
    segment: str = "default"
    platform: str = "default"
    profile: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class JobResponse(BaseModel):
    job_id: str
    status: str
    verdict_id: Optional[str] = None


def _run_job(job_id: str, req: EvaluateRequest) -> None:
    try:
        repo = get_repo()
        profile = get_profile(req.profile)
        harness = CalibrationHarness(repo)
        gt = repo.get_ground_truth_set(profile.ground_truth_set)
        engine = FunnelEngine(profile, ground_truth=gt, harness=harness)
        artifact = Artifact(
            id=req.artifact_id, modality=req.modality, text=req.text,
            segment=req.segment, platform=req.platform, metadata=req.metadata,
        )
        verdict = engine.evaluate(artifact)
        repo.save_verdict(verdict)
        _jobs[job_id] = {"status": "done", "verdict_id": verdict.id}
    except Exception as e:  # surfaced to the poller, never swallowed
        _jobs[job_id] = {"status": "error", "error": str(e)}


@app.post("/evaluate", response_model=JobResponse)
def evaluate(req: EvaluateRequest, background: BackgroundTasks) -> JobResponse:
    job_id = f"job-{uuid.uuid4().hex[:12]}"
    _jobs[job_id] = {"status": "running"}
    background.add_task(_run_job, job_id, req)
    return JobResponse(job_id=job_id, status="queued")


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job.")
    return {"job_id": job_id, **job}


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


@app.post("/ground-truth")
def ingest_ground_truth(body: GroundTruthIngest) -> dict:
    """Ingest real outcomes; triggers recalibration of every affected rung cell."""
    harness = CalibrationHarness(get_repo())
    updated = harness.ingest_outcomes(body.records)
    return {
        "ingested": len(body.records),
        "recalibrated": [r.model_dump(mode="json") for r in updated],
    }


@app.get("/calibration/{rung}")
def calibration_report(rung: str) -> dict:
    return CalibrationHarness(get_repo()).report(rung).model_dump(mode="json")


@app.get("/profiles")
def list_profiles() -> dict:
    names = sorted(set(_profiles) | {"default-text-v0.1"})
    return {"profiles": names}


@app.post("/profiles")
def create_profile(profile: EvaluationProfile) -> dict:
    _profiles[profile.name] = profile
    return {"name": profile.name, "config_hash": profile.config_hash()}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}

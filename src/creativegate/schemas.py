"""Core schemas: the stable contract of CreativeGate.

Design rationale: every model behind the funnel is swappable, but the shapes
here are the product. Verdicts, rung results, calibration records and
profiles are typed, versioned, and serializable so any evaluation is
replayable and any diff between two verdicts is attributable to a recorded
config/model/prompt version change.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

SCHEMA_VERSION = "0.1.1"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


class Modality(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    HTML = "html"
    COMPOSITE = "composite"


class Artifact(BaseModel):
    """A creative artifact under evaluation.

    ``text`` carries caption/copy/parsed-HTML text; ``path`` points at a
    binary payload (image/video) in the artifact store. ``segment`` and
    ``platform`` drive which calibration records apply to it.
    """

    id: str
    modality: Modality
    text: Optional[str] = None
    path: Optional[str] = None
    segment: str = "default"
    platform: str = "default"
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Rung results and validity
# ---------------------------------------------------------------------------


class CostTier(int, Enum):
    """Ordinal cost of one evaluation. The funnel executes cheap -> expensive."""

    FREE = 0        # deterministic checks
    CHEAP = 1       # learned models, local inference
    MODERATE = 2    # LLM ensembles, saliency APIs
    EXPENSIVE = 3   # panels, OPE over large logs


class Validity(BaseModel):
    """What a rung's score is actually worth, and where.

    A rung may never claim validity it does not have: this object is built
    from calibration records (or their absence), not from the rung's
    self-assessment. ``calibrated=False`` means the score is directional
    only and must carry zero weight in fusion.
    """

    calibrated: bool = False
    correlation: Optional[float] = None       # Spearman r vs ground truth
    pearson: Optional[float] = None
    n: int = 0                                # outcomes backing the correlation
    segment: Optional[str] = None
    modality: Optional[str] = None
    freshness: Optional[datetime] = None
    statement: str = "Unvalidated: no calibration records for this segment/modality."


class Evidence(BaseModel):
    """One entry in a verdict's evidence ledger."""

    source: str                               # rung or check that produced it
    kind: str                                 # "check", "comparison", "prediction", "flag"
    summary: str
    detail: dict[str, Any] = Field(default_factory=dict)


class RungResult(BaseModel):
    """Common return type of every rung (see rungs.base.Rung)."""

    rung: str
    rung_version: str
    score: Optional[float] = None             # 0..1, None if the rung only gates/flags
    passed: bool = True                       # False => artifact eliminated here
    confidence: float = 0.0                   # rung-internal confidence, 0..1
    variance: Optional[float] = None          # ensemble/sample variance when applicable
    evidence: list[Evidence] = Field(default_factory=list)
    cost_tier: CostTier = CostTier.FREE
    validity: Validity = Field(default_factory=Validity)
    flags: list[str] = Field(default_factory=list)
    provider_fidelity: str = "full"           # "full" | "degraded" (keyless fallback)


# ---------------------------------------------------------------------------
# Ground truth and calibration
# ---------------------------------------------------------------------------


class OutcomeQuality(str, Enum):
    MEASURED = "measured"
    ESTIMATED = "estimated"


class GroundTruthRecord(BaseModel):
    """One artifact with a known real-world outcome."""

    artifact_ref: str
    modality: Modality
    segment: str = "default"
    platform: str = "default"
    outcomes: dict[str, float]                # e.g. {"ctr": 0.031, "cvr": 0.004}
    outcome_quality: OutcomeQuality = OutcomeQuality.MEASURED
    timestamp: datetime = Field(default_factory=utcnow)
    text: Optional[str] = None                # inline payload for text artifacts
    features: dict[str, float] = Field(default_factory=dict)
    is_anchor: bool = False                   # usable as a pairwise-judge anchor


class GroundTruthSet(BaseModel):
    name: str
    target_metric: str = "ctr"
    records: list[GroundTruthRecord] = Field(default_factory=list)

    def for_segment(self, segment: str, modality: Modality) -> list[GroundTruthRecord]:
        return [r for r in self.records if r.segment == segment and r.modality == modality]


class CalibrationRecord(BaseModel):
    """Measured trustworthiness of one rung for one (segment, modality).

    This is the unit of honesty: fusion weights derive from these records
    and from nothing else.
    """

    rung: str
    segment: str
    modality: str
    metric: str                               # which outcome it was validated against
    spearman: float
    pearson: float
    n: int
    updated_at: datetime = Field(default_factory=utcnow)
    previous_spearman: Optional[float] = None
    drift_detected: bool = False
    notes: str = ""


class CalibrationReport(BaseModel):
    rung: str
    records: list[CalibrationRecord] = Field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Profiles (declarative funnel definition)
# ---------------------------------------------------------------------------


class RungConfig(BaseModel):
    name: str
    enabled: bool = True
    threshold: Optional[float] = None         # min score to survive; None = gate-only
    config: dict[str, Any] = Field(default_factory=dict)


class EvaluationProfile(BaseModel):
    name: str
    target_metric: str = "ctr"
    ground_truth_set: str = "synthetic-starter"
    rungs: list[RungConfig] = Field(default_factory=list)
    fusion: dict[str, Any] = Field(default_factory=lambda: {
        "policy": "calibration-weighted",
        "min_weight_r": 0.1,      # calibration r below this contributes nothing
        "good_anchor_floor": 0.25,  # known-good anchors may not score below this
    })
    seed: int = 7

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Verdicts
# ---------------------------------------------------------------------------


class NextTest(BaseModel):
    """The cheapest next test that would most tighten this verdict."""

    kind: str                                 # "human_pretest" | "micro_flight" | "sequential_ab" | "none"
    rationale: str
    estimated_cost_usd: Optional[float] = None
    expected_gain: str = ""


class Verdict(BaseModel):
    id: str
    artifact_id: str
    schema_version: str = SCHEMA_VERSION
    profile_name: str
    config_hash: str
    seed: int
    created_at: datetime = Field(default_factory=utcnow)

    eliminated: bool = False
    eliminated_by: Optional[str] = None       # rung name

    score: Optional[float] = None             # fused score, 0..1
    band: Optional[tuple[float, float]] = None  # score +/- uncertainty
    confidence_note: str = ""

    rung_results: list[RungResult] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    validity_summary: str = ""
    next_test: Optional[NextTest] = None

    versions: dict[str, str] = Field(default_factory=dict)  # rung -> version, models, prompts
    runtime_ms: Optional[float] = None                       # wall clock; display-only, never fused

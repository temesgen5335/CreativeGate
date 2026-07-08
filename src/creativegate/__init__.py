"""CreativeGate: a simulation-first evaluation funnel for creative artifacts.

Evaluate before you spend — and make every cheap evaluator earn its trust by
continuous calibration against the expensive ones.
"""

__version__ = "0.1.0"

from .schemas import (
    Artifact,
    EvaluationProfile,
    GroundTruthRecord,
    GroundTruthSet,
    Modality,
    RungResult,
    Verdict,
)
from .engine import FunnelEngine
from .calibration import CalibrationHarness, SyntheticWorld, make_starter_set
from .storage import Repository

__all__ = [
    "Artifact",
    "EvaluationProfile",
    "GroundTruthRecord",
    "GroundTruthSet",
    "Modality",
    "RungResult",
    "Verdict",
    "FunnelEngine",
    "CalibrationHarness",
    "SyntheticWorld",
    "make_starter_set",
    "Repository",
]

"""Evaluation rungs: composable evaluators implementing one interface."""

from .base import Rung, RungContext
from .deterministic import DeterministicGate
from .judge import CalibratedJudgeEnsemble
from .predictor import PerformancePredictor

RUNG_REGISTRY: dict[str, type[Rung]] = {
    DeterministicGate.name: DeterministicGate,
    CalibratedJudgeEnsemble.name: CalibratedJudgeEnsemble,
    PerformancePredictor.name: PerformancePredictor,
}

__all__ = [
    "Rung",
    "RungContext",
    "DeterministicGate",
    "CalibratedJudgeEnsemble",
    "PerformancePredictor",
    "RUNG_REGISTRY",
]

"""The rung plugin interface.

Design rationale: every evaluator — shipped or third-party — implements this
one contract, so the funnel engine composes rungs without knowing what they
are. Two rules are enforced *here*, not trusted to implementations:

1. A rung's ``Validity`` is stamped from the calibration store, never from
   the rung's own claims (safety rail §9.6: "a rung can never report
   validity it doesn't have").
2. Rungs are pure with respect to a ``RungContext``: same artifact + same
   context + same seed => same result, so verdicts are replayable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from ..schemas import (
    Artifact,
    CalibrationRecord,
    CostTier,
    GroundTruthSet,
    Modality,
    RungResult,
    Validity,
)


@dataclass
class RungContext:
    """Everything a rung may read: config, ground truth, providers, seed."""

    config: dict[str, Any] = field(default_factory=dict)
    ground_truth: Optional[GroundTruthSet] = None
    target_metric: str = "ctr"
    seed: int = 7
    providers: dict[str, Any] = field(default_factory=dict)
    calibration_lookup: Optional[Any] = None  # callable (rung, segment, modality) -> CalibrationRecord|None


class Rung(ABC):
    name: str = "abstract"
    version: str = "0.0.0"
    cost_tier: CostTier = CostTier.FREE
    supported_modalities: tuple[Modality, ...] = (Modality.TEXT,)

    @abstractmethod
    def evaluate(self, artifact: Artifact, ctx: RungContext) -> RungResult:
        """Score/gate one artifact. Must be deterministic given (artifact, ctx)."""

    def predict_outcome(self, artifact: Artifact, ctx: RungContext) -> Optional[float]:
        """The rung's raw outcome-correlated score for calibration purposes.

        Default: run evaluate() and use its score. Rungs may override with a
        cheaper path.
        """
        return self.evaluate(artifact, ctx).score

    # -- validity stamping (framework-owned, not implementation-owned) ------

    def stamped_validity(self, artifact: Artifact, ctx: RungContext) -> Validity:
        """Build Validity strictly from the calibration store."""
        record: Optional[CalibrationRecord] = None
        if ctx.calibration_lookup is not None:
            record = ctx.calibration_lookup(self.name, artifact.segment, artifact.modality.value)
        if record is None or record.n < 5:
            return Validity(
                calibrated=False,
                segment=artifact.segment,
                modality=artifact.modality.value,
                n=record.n if record else 0,
                statement=(
                    f"Unvalidated for segment='{artifact.segment}', "
                    f"modality='{artifact.modality.value}': "
                    + ("insufficient outcomes." if record else "no calibration records.")
                    + " Score is directional only."
                ),
            )
        return Validity(
            calibrated=True,
            correlation=record.spearman,
            pearson=record.pearson,
            n=record.n,
            segment=artifact.segment,
            modality=artifact.modality.value,
            freshness=record.updated_at,
            statement=(
                f"Validated for segment='{artifact.segment}', modality='{artifact.modality.value}': "
                f"Spearman r={record.spearman:.2f} vs {record.metric} (n={record.n})."
                + (" DRIFT WARNING: correlation decayed since last window." if record.drift_detected else "")
            ),
        )

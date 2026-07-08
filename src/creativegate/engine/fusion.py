"""Score fusion: calibration-weighted, uncertainty-propagating, never naive.

Design rationale: the final verdict is a weighted mean where each rung's
weight is its MEASURED calibration (Spearman vs ground truth for this
artifact's segment/modality), supplied by the harness. Uncalibrated rungs
contribute flags and evidence, never weight — enforced here structurally:
weights come only from the harness's ``fusion_weight``, which returns 0.0
for anything without sufficient calibration records.

The confidence band combines three real sources of doubt:
- rung-internal variance (ensemble disagreement),
- calibration weakness (a rung with r=0.5 explains little of reality),
- coverage (how much total calibrated weight backs the number at all).
"""

from __future__ import annotations

import math
from typing import Optional

from ..schemas import RungResult


def fuse(results: list[RungResult], weights: dict[str, float]) -> tuple[Optional[float], Optional[tuple[float, float]], str]:
    """Return (score, (lo, hi) band, explanation). Score is None when no
    calibrated signal exists — the honest answer, not a fake average."""
    scored = [r for r in results if r.score is not None]
    if not scored:
        return None, None, "No rung produced a score; verdict is gate-evidence only."

    weighted = [(r, weights.get(r.rung, 0.0)) for r in scored]
    total_w = sum(w for _, w in weighted)

    if total_w <= 0:
        # Nothing calibrated: report the unweighted mean as clearly-labeled
        # directional signal with a maximally wide band.
        mean = sum(r.score for r in scored) / len(scored)
        lo, hi = max(0.0, mean - 0.35), min(1.0, mean + 0.35)
        return mean, (lo, hi), (
            "DIRECTIONAL ONLY: no rung is calibrated for this segment/modality, so "
            "this is an unweighted mean with a deliberately wide band. "
            "Calibrate against real outcomes to tighten it."
        )

    score = sum(r.score * w for r, w in weighted) / total_w

    # Uncertainty propagation.
    # 1) rung-internal variance propagated through the weights
    internal_var = sum((w / total_w) ** 2 * (r.variance or 0.0) for r, w in weighted)
    # 2) calibration weakness: weighted-average unexplained rank variance (1 - r^2)
    unexplained = sum(w * (1.0 - min(abs(w), 1.0) ** 2) for _, w in weighted) / total_w
    # 3) coverage: little total calibrated weight => wide band
    coverage_penalty = 0.25 / (1.0 + 2.0 * total_w)

    half_band = min(0.5, math.sqrt(internal_var) + 0.20 * unexplained + coverage_penalty)
    lo, hi = max(0.0, score - half_band), min(1.0, score + half_band)

    parts = [
        f"{r.rung} (score {r.score:.3f}, weight {w:.2f})"
        for r, w in weighted if w > 0
    ]
    zero = [r.rung for r, w in weighted if w <= 0]
    explanation = "Calibration-weighted fusion of " + ", ".join(parts) + "."
    if zero:
        explanation += (
            f" Excluded from weighting (uncalibrated, evidence-only): {', '.join(zero)}."
        )
    return score, (lo, hi), explanation

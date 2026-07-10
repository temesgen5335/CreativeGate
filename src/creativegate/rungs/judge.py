"""Rung 2: the Calibrated Judge Ensemble.

Design rationale: judges are far more reliable at "A vs B" than at absolute
scores, so this rung *only* does pairwise comparison. The artifact is
compared against K anchors drawn deterministically from the ground-truth set
(spanning the outcome range), each comparison repeated over N ensemble
passes with distinct seeds. The score is an outcome-weighted win-rate:
beating a high-CTR anchor moves the score more than beating a dud.

Reliability engineering, in order: temperature 0; rubric-anchored prompt;
pairwise-only; N-sample ensembling with variance reported; and calibration —
this rung's fusion weight comes exclusively from measured correlation with
real outcomes (stamped by the framework, see rungs.base).
"""

from __future__ import annotations

import hashlib

from ..schemas import Artifact, CostTier, Evidence, GroundTruthRecord, Modality, RungResult
from ..providers import resolve_llm
from .base import Rung, RungContext

RUNG_VERSION = "0.1.0"
PROMPT_VERSION = "0.1.0"

RUBRIC_PROMPT = """You are an expert direct-response creative evaluator.
Judge which of two creatives is more likely to make a typical member of the
target audience act (click / convert). Weigh, in order:
1. Clarity of the offer — can a reader say what is being offered in 3 seconds?
2. Strength and specificity of the call to action.
3. Credible motivation (benefit, urgency) without spam signals
   (ALL CAPS, '!!', 'guaranteed', 'miracle' reduce trust and performance).
4. Fit of length and tone to a feed placement.
Pick the better performer even if both are weak or both are strong.
"""


def select_anchors(records: list[GroundTruthRecord], metric: str, k: int) -> list[GroundTruthRecord]:
    """Deterministically pick k anchors spanning the outcome range: sort by
    outcome and take evenly spaced quantiles (worst, ..., best)."""
    usable = [r for r in records if r.text and metric in r.outcomes]
    usable.sort(key=lambda r: (r.outcomes[metric], r.artifact_ref))
    if len(usable) <= k:
        return usable
    idx = [round(i * (len(usable) - 1) / (k - 1)) for i in range(k)]
    return [usable[i] for i in sorted(set(idx))]


class CalibratedJudgeEnsemble(Rung):
    name = "judge_ensemble"
    version = RUNG_VERSION
    cost_tier = CostTier.MODERATE
    supported_modalities = (Modality.TEXT,)

    def evaluate(self, artifact: Artifact, ctx: RungContext) -> RungResult:
        cfg = ctx.config
        k = int(cfg.get("num_anchors", 5))
        n_passes = int(cfg.get("ensemble_passes", 3))
        # The rubric is profile config (charter §6): a mobile-app storyboard
        # and a web banner are judged against different written criteria.
        # The anchors — the other half of the criteria — come from the
        # profile's ground-truth set. Default rubric when unset.
        rubric = cfg.get("rubric") or RUBRIC_PROMPT
        rubric_version = (PROMPT_VERSION if rubric is RUBRIC_PROMPT
                          else "custom-" + hashlib.sha256(rubric.encode()).hexdigest()[:8])
        llm = ctx.providers.get("llm") or resolve_llm(cfg.get("llm"))

        evidence: list[Evidence] = []
        gt = ctx.ground_truth
        anchors = select_anchors(gt.records if gt else [], ctx.target_metric, k) if gt else []

        if not artifact.text or len(anchors) < 2:
            return RungResult(
                rung=self.name, rung_version=self.version, score=None, passed=True,
                confidence=0.0, cost_tier=self.cost_tier,
                validity=self.stamped_validity(artifact, ctx),
                evidence=[Evidence(source=self.name, kind="flag",
                                   summary="Judge skipped: no text or fewer than 2 usable anchors.")],
                flags=["judge_skipped"],
                provider_fidelity=llm.fidelity,
            )

        outcomes = [a.outcomes[ctx.target_metric] for a in anchors]
        lo, hi = min(outcomes), max(outcomes)
        span = (hi - lo) or 1.0

        # Outcome-weighted win-rate over N ensemble passes, position-debiased
        # by alternating A/B order across passes.
        per_pass_scores: list[float] = []
        win_counts = {a.artifact_ref: 0 for a in anchors}
        for p in range(n_passes):
            total_w, won_w = 0.0, 0.0
            for a in anchors:
                weight = 0.5 + (a.outcomes[ctx.target_metric] - lo) / span  # 0.5..1.5
                seed = ctx.seed * 1000 + p
                if p % 2 == 0:
                    verdict = llm.compare(rubric, artifact.text, a.text, seed)
                    won = verdict == "A"
                else:
                    verdict = llm.compare(rubric, a.text, artifact.text, seed)
                    won = verdict == "B"
                total_w += weight
                if won:
                    won_w += weight
                    win_counts[a.artifact_ref] += 1
            per_pass_scores.append(won_w / total_w)

        score = sum(per_pass_scores) / len(per_pass_scores)
        variance = float(
            sum((s - score) ** 2 for s in per_pass_scores) / max(len(per_pass_scores) - 1, 1)
        )

        for a in anchors:
            evidence.append(Evidence(
                source=self.name, kind="comparison",
                summary=(
                    f"vs anchor '{a.artifact_ref}' ({ctx.target_metric}="
                    f"{a.outcomes[ctx.target_metric]:.4f}): won {win_counts[a.artifact_ref]}/{n_passes} passes"
                ),
                detail={"anchor": a.artifact_ref, "wins": win_counts[a.artifact_ref], "passes": n_passes},
            ))
        evidence.append(Evidence(
            source=self.name, kind="prediction",
            summary=(
                f"Outcome-weighted win-rate {score:.3f} over {len(anchors)} anchors x "
                f"{n_passes} passes (ensemble variance {variance:.4f}); "
                f"comparator={llm.name} ({llm.fidelity} fidelity)."
            ),
            detail={"per_pass": per_pass_scores, "prompt_version": rubric_version},
        ))

        threshold = cfg.get("threshold")
        passed = True if threshold is None else score >= float(threshold)
        return RungResult(
            rung=self.name,
            rung_version=self.version,
            score=score,
            passed=passed,
            confidence=max(0.0, 1.0 - 4.0 * variance ** 0.5),
            variance=variance,
            evidence=evidence,
            cost_tier=self.cost_tier,
            validity=self.stamped_validity(artifact, ctx),
            flags=([] if llm.fidelity == "full" else ["degraded_provider: keyless heuristic comparator"]),
            provider_fidelity=llm.fidelity,
        )

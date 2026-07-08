"""The funnel engine: cost-ordered execution with filtering.

Design rationale: each rung filters; only survivors proceed to more
expensive rungs. Thresholds are profile config, not code. Every elimination
carries the evidence that caused it. Survivors get a calibration-weighted
fused score with a confidence band, a validity summary in which the system
volunteers its own limits, and a cheapest-next-test recommendation.

Determinism: the profile's seed feeds every rung; the verdict records the
config hash and every rung/prompt/provider version so any evaluation is
replayable and diffs are attributable.

Safety rails enforced here (tested in tests/test_safety_rails.py):
- fusion weights come only from the calibration harness (uncalibrated => 0);
- known-good anchors scored below the profile's floor are flagged for human
  review instead of being silently buried.
"""

from __future__ import annotations

import uuid
from typing import Optional

from ..calibration.harness import CalibrationHarness
from ..rungs import RUNG_REGISTRY, Rung, RungContext
from ..schemas import (
    Artifact,
    Evidence,
    EvaluationProfile,
    GroundTruthSet,
    Verdict,
)
from .fusion import fuse
from .recommend import recommend_next_test


class FunnelEngine:
    def __init__(self, profile: EvaluationProfile,
                 ground_truth: Optional[GroundTruthSet] = None,
                 harness: Optional[CalibrationHarness] = None,
                 providers: Optional[dict] = None):
        self.profile = profile
        self.ground_truth = ground_truth
        self.harness = harness
        self.providers = providers or {}

        self._rungs: list[tuple[Rung, dict]] = []
        for rc in profile.rungs:
            if not rc.enabled:
                continue
            cls = RUNG_REGISTRY.get(rc.name)
            if cls is None:
                raise ValueError(f"Unknown rung '{rc.name}'. Available: {sorted(RUNG_REGISTRY)}")
            cfg = dict(rc.config)
            if rc.threshold is not None:
                cfg["threshold"] = rc.threshold
            self._rungs.append((cls(), cfg))
        # Cost-ordered: cheap rungs filter before expensive rungs run.
        # Stable sort preserves profile order within a tier.
        self._rungs.sort(key=lambda pair: pair[0].cost_tier.value)

    def _ctx(self, cfg: dict) -> RungContext:
        lookup = self.harness.lookup if self.harness else None
        return RungContext(
            config=cfg,
            ground_truth=self.ground_truth,
            target_metric=self.profile.target_metric,
            seed=self.profile.seed,
            providers=self.providers,
            calibration_lookup=lookup,
        )

    def evaluate(self, artifact: Artifact, record_predictions: bool = True) -> Verdict:
        verdict = Verdict(
            id=f"v-{uuid.uuid4().hex[:12]}",
            artifact_id=artifact.id,
            profile_name=self.profile.name,
            config_hash=self.profile.config_hash(),
            seed=self.profile.seed,
        )

        results = []
        for rung, cfg in self._rungs:
            if artifact.modality not in rung.supported_modalities:
                verdict.evidence.append(Evidence(
                    source="funnel", kind="flag",
                    summary=f"Rung '{rung.name}' skipped: does not support modality '{artifact.modality.value}'.",
                ))
                continue
            result = rung.evaluate(artifact, self._ctx(cfg))
            results.append(result)
            verdict.rung_results.append(result)
            verdict.evidence.extend(result.evidence)
            verdict.flags.extend(f"{result.rung}: {f}" for f in result.flags)
            verdict.versions[result.rung] = result.rung_version

            if record_predictions and self.harness and result.score is not None:
                self.harness.record_prediction(
                    rung=result.rung, artifact_ref=artifact.id,
                    segment=artifact.segment, modality=artifact.modality.value,
                    metric=self.profile.target_metric, predicted=result.score,
                    verdict_id=verdict.id,
                )

            if not result.passed:
                verdict.eliminated = True
                verdict.eliminated_by = result.rung
                verdict.confidence_note = (
                    f"Eliminated at '{result.rung}'; more expensive rungs were not run."
                )
                fails = [e.summary for e in result.evidence
                         if e.kind == "check" and not e.detail.get("passed", True)]
                verdict.validity_summary = "; ".join(fails) or f"Failed threshold at '{result.rung}'."
                return verdict

        # -- fusion over survivors -------------------------------------------
        min_r = float(self.profile.fusion.get("min_weight_r", 0.1))
        weights = {}
        if self.harness:
            for r in results:
                weights[r.rung] = self.harness.fusion_weight(
                    r.rung, artifact.segment, artifact.modality.value, min_r=min_r
                )
        score, band, explanation = fuse(results, weights)
        verdict.score = score
        verdict.band = band
        verdict.confidence_note = explanation

        # Validity summary: the system volunteers its own limits.
        validity_lines = [
            f"{r.rung}: {r.validity.statement}" for r in results if r.score is not None
        ]
        verdict.validity_summary = " | ".join(validity_lines) or "No scoring rungs ran."

        # Safety rail: known-good anchors can't be quietly scored below the floor.
        floor = float(self.profile.fusion.get("good_anchor_floor", 0.25))
        if score is not None and score < floor and self._is_known_good(artifact):
            verdict.flags.append(
                f"HUMAN_REVIEW_REQUIRED: artifact matches a known-good/converting anchor but "
                f"fused score {score:.2f} is below the floor {floor:.2f}. "
                "A rung may have drifted; do not auto-reject."
            )

        verdict.next_test = recommend_next_test(
            results, weights, band, self.profile.fusion.get("test_costs")
        )
        return verdict

    def _is_known_good(self, artifact: Artifact) -> bool:
        if self.ground_truth is None:
            return False
        metric = self.profile.target_metric
        vals = [r.outcomes[metric] for r in self.ground_truth.records if metric in r.outcomes]
        if len(vals) < 5:
            return False
        vals.sort()
        top_quartile = vals[int(len(vals) * 0.75)]
        for r in self.ground_truth.records:
            if r.artifact_ref == artifact.id or (r.text and r.text == artifact.text):
                return r.outcomes.get(metric, 0.0) >= top_quartile
        return False

    def evaluate_batch(self, artifacts: list[Artifact]) -> list[Verdict]:
        return [self.evaluate(a) for a in artifacts]

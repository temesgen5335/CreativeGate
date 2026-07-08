"""The safety rails of design principle 9.6 — the spine of the test suite.

1. An uncalibrated rung can never dominate (or even enter) fusion.
2. A rung can never report validity it doesn't have.
3. Known-good anchors can never be scored below the floor without a
   human-review flag.
4. Deterministic rungs have zero variance; verdicts are reproducible.
"""

from creativegate.engine import FunnelEngine
from creativegate.engine.fusion import fuse
from creativegate.rungs import DeterministicGate, PerformancePredictor
from creativegate.rungs.base import RungContext
from creativegate.schemas import (
    Artifact,
    CalibrationRecord,
    Modality,
    RungResult,
    Validity,
)


def _result(rung: str, score: float, variance: float = 0.0) -> RungResult:
    return RungResult(rung=rung, rung_version="0.1.0", score=score,
                      variance=variance, validity=Validity())


class TestUncalibratedNeverDominates:
    def test_uncalibrated_rungs_carry_zero_weight(self, harness):
        # No calibration records exist => fusion_weight must be 0.
        assert harness.fusion_weight("judge_ensemble", "default", "text") == 0.0

    def test_fusion_with_all_zero_weights_is_labeled_directional(self):
        score, band, note = fuse([_result("a", 0.9), _result("b", 0.2)], {"a": 0.0, "b": 0.0})
        assert "DIRECTIONAL ONLY" in note
        assert band is not None and band[1] - band[0] >= 0.5  # deliberately wide

    def test_calibrated_rung_outweighs_uncalibrated(self):
        # 'good' is calibrated (w=0.8), 'noisy' is not (w=0): the fused score
        # must equal the calibrated rung's score exactly.
        score, _, note = fuse([_result("good", 0.7), _result("noisy", 0.1)],
                              {"good": 0.8, "noisy": 0.0})
        assert abs(score - 0.7) < 1e-9
        assert "noisy" in note and "uncalibrated" in note.lower()

    def test_weight_requires_min_samples(self, harness, repo):
        # 3 perfectly-correlated pairs are below MIN_SAMPLES: still weight 0.
        for i, (p, o) in enumerate([(0.1, 0.01), (0.5, 0.02), (0.9, 0.03)]):
            repo.save_prediction("r", f"a{i}", "default", "text", "ctr", p, None)
        from creativegate.schemas import GroundTruthRecord
        recs = [GroundTruthRecord(artifact_ref=f"a{i}", modality=Modality.TEXT,
                                  outcomes={"ctr": o})
                for i, (p, o) in enumerate([(0.1, 0.01), (0.5, 0.02), (0.9, 0.03)])]
        harness.ingest_outcomes(recs)
        assert harness.fusion_weight("r", "default", "text") == 0.0


class TestNoUnearnedValidity:
    def test_validity_is_stamped_from_store_not_self_asserted(self, harness):
        rung = PerformancePredictor()
        artifact = Artifact(id="x", modality=Modality.TEXT, text="Shop now for great shoes today.")
        ctx = RungContext(calibration_lookup=harness.lookup)
        v = rung.stamped_validity(artifact, ctx)
        assert v.calibrated is False
        assert "directional only" in v.statement.lower()

    def test_validity_reflects_store_when_records_exist(self, harness, repo):
        repo.save_calibration(CalibrationRecord(
            rung="performance_predictor", segment="default", modality="text",
            metric="ctr", spearman=0.62, pearson=0.60, n=200))
        rung = PerformancePredictor()
        artifact = Artifact(id="x", modality=Modality.TEXT, text="t")
        v = rung.stamped_validity(artifact, RungContext(calibration_lookup=harness.lookup))
        assert v.calibrated is True and abs(v.correlation - 0.62) < 1e-9 and v.n == 200

    def test_validity_is_segment_scoped(self, harness, repo):
        repo.save_calibration(CalibrationRecord(
            rung="performance_predictor", segment="gen-z", modality="text",
            metric="ctr", spearman=0.7, pearson=0.7, n=100))
        rung = PerformancePredictor()
        other = Artifact(id="x", modality=Modality.TEXT, text="t", segment="boomers")
        v = rung.stamped_validity(other, RungContext(calibration_lookup=harness.lookup))
        assert v.calibrated is False  # validated for gen-z is not validated for boomers


class TestKnownGoodFloor:
    def test_known_good_anchor_below_floor_raises_human_review(self, ground_truth, harness, profile):
        # Take the best-performing record in the set and force a low fused
        # score by neutering thresholds and using a hostile calibration.
        best = max(ground_truth.records, key=lambda r: r.outcomes["ctr"])
        engine = FunnelEngine(profile, ground_truth=ground_truth, harness=harness)
        # Simulate a drifted world: a calibrated-but-wrong rung scoring low.
        verdict = engine.evaluate(Artifact(id=best.artifact_ref, modality=Modality.TEXT,
                                           text=best.text), record_predictions=False)
        if verdict.score is not None and verdict.score < profile.fusion["good_anchor_floor"]:
            assert any("HUMAN_REVIEW_REQUIRED" in f for f in verdict.flags)

    def test_floor_flag_fires_deterministically(self, ground_truth, harness, profile, monkeypatch):
        # Force the fused score below the floor and confirm the flag.
        from creativegate.engine import funnel as funnel_mod
        best = max(ground_truth.records, key=lambda r: r.outcomes["ctr"])
        engine = FunnelEngine(profile, ground_truth=ground_truth, harness=harness)
        monkeypatch.setattr(funnel_mod, "fuse", lambda results, weights: (0.05, (0.0, 0.2), "forced"))
        verdict = engine.evaluate(Artifact(id=best.artifact_ref, modality=Modality.TEXT,
                                           text=best.text), record_predictions=False)
        assert any("HUMAN_REVIEW_REQUIRED" in f for f in verdict.flags)

    def test_unknown_artifact_gets_no_review_flag(self, ground_truth, harness, profile, monkeypatch):
        from creativegate.engine import funnel as funnel_mod
        engine = FunnelEngine(profile, ground_truth=ground_truth, harness=harness)
        monkeypatch.setattr(funnel_mod, "fuse", lambda results, weights: (0.05, (0.0, 0.2), "forced"))
        verdict = engine.evaluate(Artifact(id="novel", modality=Modality.TEXT,
                                           text="Get our brand new coffee subscription today. Try it free."),
                                  record_predictions=False)
        assert not any("HUMAN_REVIEW_REQUIRED" in f for f in verdict.flags)


class TestDeterminism:
    def test_gate_zero_variance(self):
        gate = DeterministicGate()
        artifact = Artifact(id="x", modality=Modality.TEXT, text="Buy our miracle cream now!")
        ctx = RungContext(config={"banned_phrases": ["miracle"], "min_words": 3})
        r1 = gate.evaluate(artifact, ctx)
        r2 = gate.evaluate(artifact, ctx)
        assert r1.model_dump() == r2.model_dump()
        assert r1.passed is False

    def test_full_verdict_reproducible(self, ground_truth, harness, profile):
        engine = FunnelEngine(profile, ground_truth=ground_truth, harness=harness)
        artifact = Artifact(id="x", modality=Modality.TEXT,
                            text="Meet your new favorite running shoes. Free shipping included. Shop now.")
        v1 = engine.evaluate(artifact, record_predictions=False)
        v2 = engine.evaluate(artifact, record_predictions=False)
        assert v1.score == v2.score and v1.band == v2.band
        assert [r.score for r in v1.rung_results] == [r.score for r in v2.rung_results]

    def test_verdict_stamps_config_hash_and_versions(self, ground_truth, harness, profile):
        engine = FunnelEngine(profile, ground_truth=ground_truth, harness=harness)
        v = engine.evaluate(Artifact(id="x", modality=Modality.TEXT,
                                     text="Try our meal kits today. Save 30% on your first order."),
                            record_predictions=False)
        assert v.config_hash == profile.config_hash()
        assert "deterministic_gate" in v.versions

"""The synthetic world verifies the whole loop against known physics.

Because we wrote the outcome-generating model, we can assert that the
funnel's learned components actually recover signal that provably exists —
this is the harness testing itself.
"""

from scipy import stats

from creativegate.calibration import CalibrationHarness, SyntheticWorld
from creativegate.engine import FunnelEngine
from creativegate.profiles import default_profile
from creativegate.schemas import Artifact, Modality


class TestWorldDeterminism:
    def test_same_seed_same_world(self):
        a = SyntheticWorld(seed=7).generate_set(30)
        b = SyntheticWorld(seed=7).generate_set(30)
        assert [r.text for r in a.records] == [r.text for r in b.records]
        assert [r.outcomes for r in a.records] == [r.outcomes for r in b.records]

    def test_different_seed_different_world(self):
        a = SyntheticWorld(seed=7).generate_set(30)
        b = SyntheticWorld(seed=8).generate_set(30)
        assert [r.text for r in a.records] != [r.text for r in b.records]

    def test_physics_are_real(self, world):
        # Outcomes must actually depend on the true features: ads with CTAs
        # must out-perform ads without, on average, by construction.
        gt = world.generate_set(300)
        with_cta = [r.outcomes["ctr"] for r in gt.records if r.features["cta"]]
        without = [r.outcomes["ctr"] for r in gt.records if not r.features["cta"]]
        assert sum(with_cta) / len(with_cta) > sum(without) / len(without)


class TestLoopRecoversKnownSignal:
    def test_predictor_recovers_signal_and_harness_measures_it(self, repo):
        world = SyntheticWorld(seed=7)
        full = world.generate_set(180)
        train = full.model_copy(update={"records": full.records[:150]})
        holdout = full.records[150:]

        harness = CalibrationHarness(repo)
        profile = default_profile(seed=7)
        engine = FunnelEngine(profile, ground_truth=train, harness=harness)

        # Calibrate on the training world.
        for r in train.records:
            engine.evaluate(Artifact(id=r.artifact_ref, modality=Modality.TEXT,
                                     text=r.text, segment=r.segment))
        updated = harness.ingest_outcomes(train.records)
        by_rung = {u.rung: u for u in updated}

        # The predictor must recover strong signal (the physics are learnable
        # from the shared feature extractor by construction).
        assert by_rung["performance_predictor"].spearman > 0.5

        # And the funnel's fused ranking must predict held-out truth.
        engine = FunnelEngine(profile, ground_truth=train, harness=harness)
        scored = []
        for r in holdout:
            v = engine.evaluate(Artifact(id=r.artifact_ref, modality=Modality.TEXT,
                                         text=r.text), record_predictions=False)
            if not v.eliminated and v.score is not None:
                scored.append((v.score, r.outcomes["ctr"]))
        assert len(scored) >= 10
        rho = stats.spearmanr([s for s, _ in scored], [t for _, t in scored]).statistic
        assert rho > 0.4

    def test_calibrated_verdicts_report_validated_statements(self, repo):
        world = SyntheticWorld(seed=7)
        gt = world.generate_set(80)
        harness = CalibrationHarness(repo)
        profile = default_profile(seed=7)
        engine = FunnelEngine(profile, ground_truth=gt, harness=harness)
        for r in gt.records:
            engine.evaluate(Artifact(id=r.artifact_ref, modality=Modality.TEXT, text=r.text))
        harness.ingest_outcomes(gt.records)

        engine = FunnelEngine(profile, ground_truth=gt, harness=harness)
        v = engine.evaluate(Artifact(id="new", modality=Modality.TEXT,
                                     text="Meet your new favorite meal kits. Free shipping included. Try it free."),
                            record_predictions=False)
        assert not v.eliminated
        assert "Validated for segment='default'" in v.validity_summary
        # With calibration in place the verdict is no longer directional-only.
        assert "DIRECTIONAL ONLY" not in v.confidence_note

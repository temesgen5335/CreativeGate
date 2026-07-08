"""Calibration harness: correlation math, drift detection, audit trail."""

import numpy as np

from creativegate.calibration.harness import DRIFT_DECAY_THRESHOLD
from creativegate.schemas import GroundTruthRecord, Modality


def _feed(repo, harness, pairs, rung="r", start=0):
    """Store predictions then ingest outcomes for (predicted, actual) pairs."""
    records = []
    for i, (p, o) in enumerate(pairs, start=start):
        ref = f"art-{i}"
        repo.save_prediction(rung, ref, "default", "text", "ctr", p, None)
        records.append(GroundTruthRecord(artifact_ref=ref, modality=Modality.TEXT,
                                         outcomes={"ctr": o}))
    return harness.ingest_outcomes(records)


class TestCorrelationMath:
    def test_perfect_monotone_gives_spearman_one(self, repo, harness):
        pairs = [(i / 10, i / 100) for i in range(10)]
        updated = _feed(repo, harness, pairs)
        assert len(updated) == 1
        assert abs(updated[0].spearman - 1.0) < 1e-9

    def test_anticorrelated_gives_negative(self, repo, harness):
        pairs = [(i / 10, (9 - i) / 100) for i in range(10)]
        updated = _feed(repo, harness, pairs)
        assert updated[0].spearman < -0.9
        # And a negatively-correlated rung must carry zero fusion weight.
        assert harness.fusion_weight("r", "default", "text") == 0.0

    def test_measures_known_noisy_correlation(self, repo, harness):
        rng = np.random.RandomState(0)
        truth = rng.rand(200)
        noisy = truth + rng.normal(0, 0.35, 200)  # analytically r ~ 0.7
        updated = _feed(repo, harness, list(zip(noisy, truth)))
        assert 0.55 < updated[0].spearman < 0.85

    def test_refuses_below_min_samples(self, repo, harness):
        updated = _feed(repo, harness, [(0.1, 0.01), (0.9, 0.03)])
        assert updated == []

    def test_refuses_degenerate_constant_predictions(self, repo, harness):
        updated = _feed(repo, harness, [(0.5, i / 100) for i in range(10)])
        assert updated == []


class TestDriftDetection:
    def test_drift_alarm_and_weight_cut(self, repo, harness):
        # Window 1: rung tracks reality well.
        good = [(i / 20, i / 200) for i in range(20)]
        first = _feed(repo, harness, good)[0]
        assert first.drift_detected is False
        w_before = harness.fusion_weight("r", "default", "text")

        # Window 2: the world shifts — new outcomes are anti-correlated with
        # the rung's predictions, dragging the pooled correlation down.
        rng = np.random.RandomState(1)
        bad = [(p, float(0.1 - p / 10 + rng.normal(0, 0.01))) for p in rng.rand(60)]
        second = _feed(repo, harness, bad, start=100)[0]
        assert first.spearman - second.spearman > DRIFT_DECAY_THRESHOLD
        assert second.drift_detected is True
        assert "DRIFT" in second.notes
        w_after = harness.fusion_weight("r", "default", "text")
        assert w_after < w_before  # decayed rung's weight is cut

    def test_audit_trail_is_append_only(self, repo, harness):
        _feed(repo, harness, [(i / 10, i / 100) for i in range(10)])
        _feed(repo, harness, [(i / 10, i / 100) for i in range(10, 20)], start=10)
        assert len(repo.calibrations_for_rung("r")) == 2  # both windows kept


class TestValidityReport:
    def test_unvalidated_rung_says_so(self, harness):
        report = harness.report("judge_ensemble")
        assert "unvalidated everywhere" in report.summary.lower()
        assert "directional only" in report.summary.lower()

    def test_validated_rung_reports_scope(self, repo, harness):
        _feed(repo, harness, [(i / 10, i / 100) for i in range(10)], rung="judge_ensemble")
        report = harness.report("judge_ensemble")
        assert "validated for" in report.summary.lower()
        assert "unvalidated elsewhere" in report.summary.lower()
        assert "n=10" in report.summary

"""Funnel mechanics: gating, cost ordering, elimination evidence, fusion,
next-test recommendations, image header parsing, and the API surface."""

import struct
import zlib

from fastapi.testclient import TestClient

from creativegate.engine import FunnelEngine
from creativegate.engine.fusion import fuse
from creativegate.engine.recommend import recommend_next_test
from creativegate.rungs import DeterministicGate
from creativegate.rungs.base import RungContext
from creativegate.rungs.deterministic import image_dimensions
from creativegate.schemas import Artifact, Modality, RungResult, Validity


def _png(width: int, height: int) -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    chunk = b"IHDR" + ihdr
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk
            + struct.pack(">I", zlib.crc32(chunk)))


class TestDeterministicGate:
    def _run(self, text, config):
        gate = DeterministicGate()
        return gate.evaluate(Artifact(id="x", modality=Modality.TEXT, text=text),
                             RungContext(config=config))

    def test_banned_phrase_eliminates_with_evidence(self):
        r = self._run("Miracle cream, buy now", {"banned_phrases": ["miracle"]})
        assert r.passed is False
        fails = [e for e in r.evidence if not e.detail.get("passed", True)]
        assert fails and "miracle" in fails[0].summary

    def test_required_element(self):
        cfg = {"required_elements": [{"name": "cta", "pattern": r"\bshop\b"}]}
        assert self._run("Just vibes here", cfg).passed is False
        assert self._run("Shop today", cfg).passed is True

    def test_length_limits(self):
        assert self._run("hi", {"min_words": 3}).passed is False
        assert self._run("a " * 300, {"max_chars": 100}).passed is False

    def test_gate_never_scores(self):
        r = self._run("A perfectly fine ad, shop now today", {"min_words": 2})
        assert r.score is None  # passing all rules is not quality

    def test_png_dimensions(self, tmp_path):
        p = tmp_path / "banner.png"
        p.write_bytes(_png(1200, 628))
        assert image_dimensions(str(p)) == (1200, 628)

    def test_image_aspect_ratio_check(self, tmp_path):
        p = tmp_path / "square.png"
        p.write_bytes(_png(500, 500))
        gate = DeterministicGate()
        good = gate.evaluate(
            Artifact(id="i", modality=Modality.IMAGE, path=str(p)),
            RungContext(config={"image": {"aspect_ratio": [1, 1]}}))
        assert good.passed is True
        bad = gate.evaluate(
            Artifact(id="i", modality=Modality.IMAGE, path=str(p)),
            RungContext(config={"image": {"aspect_ratio": [16, 9]}}))
        assert bad.passed is False


class TestFunnelMechanics:
    def test_rungs_execute_cheap_to_expensive(self, ground_truth, harness, profile):
        engine = FunnelEngine(profile, ground_truth=ground_truth, harness=harness)
        tiers = [r.cost_tier.value for r, _ in engine._rungs]
        assert tiers == sorted(tiers)

    def test_elimination_stops_expensive_rungs(self, ground_truth, harness, profile):
        engine = FunnelEngine(profile, ground_truth=ground_truth, harness=harness)
        v = engine.evaluate(Artifact(id="bad", modality=Modality.TEXT,
                                     text="Miracle guaranteed results!!"),
                            record_predictions=False)
        assert v.eliminated and v.eliminated_by == "deterministic_gate"
        assert len(v.rung_results) == 1  # predictor and judge never ran
        assert v.score is None

    def test_unknown_rung_is_a_config_error(self, profile):
        from creativegate.schemas import RungConfig
        import pytest
        profile.rungs.append(RungConfig(name="nonexistent_rung"))
        with pytest.raises(ValueError, match="Unknown rung"):
            FunnelEngine(profile)


class TestFusionMath:
    def _r(self, name, score, var=0.0):
        return RungResult(rung=name, rung_version="0", score=score, variance=var,
                          validity=Validity())

    def test_weighted_mean(self):
        score, band, _ = fuse([self._r("a", 0.8), self._r("b", 0.4)], {"a": 0.6, "b": 0.2})
        assert abs(score - (0.8 * 0.6 + 0.4 * 0.2) / 0.8) < 1e-9
        assert band[0] <= score <= band[1]

    def test_more_calibration_means_tighter_band(self):
        results = [self._r("a", 0.6), self._r("b", 0.6)]
        _, weak, _ = fuse(results, {"a": 0.2, "b": 0.0})
        _, strong, _ = fuse(results, {"a": 0.9, "b": 0.85})
        assert (strong[1] - strong[0]) < (weak[1] - weak[0])

    def test_no_scores_is_honest_none(self):
        gate_only = RungResult(rung="gate", rung_version="0", score=None, validity=Validity())
        score, band, note = fuse([gate_only], {})
        assert score is None and band is None


class TestNextTestRecommendation:
    def _r(self, name, score, fidelity="full"):
        return RungResult(rung=name, rung_version="0", score=score,
                          provider_fidelity=fidelity, validity=Validity())

    def test_all_uncalibrated_recommends_human_pretest(self):
        nt = recommend_next_test([self._r("a", 0.5)], {"a": 0.0}, (0.2, 0.8))
        assert nt.kind == "human_pretest"
        assert "directional" in nt.rationale

    def test_calibrated_but_wide_band_recommends_micro_flight(self):
        nt = recommend_next_test([self._r("a", 0.5)], {"a": 0.7}, (0.2, 0.6))
        assert nt.kind == "micro_flight"

    def test_tight_and_calibrated_recommends_sequential_or_none(self):
        nt = recommend_next_test([self._r("a", 0.5)], {"a": 0.9}, (0.45, 0.55))
        assert nt.kind == "none"


class TestAPI:
    def test_evaluate_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CREATIVEGATE_DB", str(tmp_path / "api.db"))
        import creativegate.api as api_mod
        monkeypatch.setattr(api_mod, "_repo", None)
        client = TestClient(api_mod.app)

        resp = client.post("/evaluate", json={
            "artifact_id": "api-test",
            "text": "Try our meal kits today. Save 30% on your first order.",
        })
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        job = client.get(f"/jobs/{job_id}").json()
        assert job["status"] == "done", job
        verdict = client.get(f"/verdict/{job['verdict_id']}").json()
        assert verdict["artifact_id"] == "api-test"
        # No ground truth in this db: predictor/judge must refuse gracefully,
        # verdict survives on gate evidence with honest flags.
        assert verdict["eliminated"] is False

        html = client.get(f"/verdict/{job['verdict_id']}/report")
        assert html.status_code == 200 and "CreativeGate verdict" in html.text

    def test_ground_truth_ingest_and_calibration_endpoints(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CREATIVEGATE_DB", str(tmp_path / "api2.db"))
        import creativegate.api as api_mod
        monkeypatch.setattr(api_mod, "_repo", None)
        client = TestClient(api_mod.app)

        records = [{"artifact_ref": f"a{i}", "modality": "text", "outcomes": {"ctr": i / 100}}
                   for i in range(6)]
        resp = client.post("/ground-truth", json={"records": records})
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 6

        cal = client.get("/calibration/performance_predictor")
        assert cal.status_code == 200
        assert "unvalidated" in cal.json()["summary"].lower()

    def test_profiles_endpoints(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CREATIVEGATE_DB", str(tmp_path / "api3.db"))
        import creativegate.api as api_mod
        client = TestClient(api_mod.app)
        assert "default-text-v0.1" in client.get("/profiles").json()["profiles"]

    def test_dashboard_and_listing_endpoints(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CREATIVEGATE_DB", str(tmp_path / "api4.db"))
        import creativegate.api as api_mod
        monkeypatch.setattr(api_mod, "_repo", None)
        client = TestClient(api_mod.app)

        # The dashboard SPA is served at the root.
        home = client.get("/")
        assert home.status_code == 200
        assert "CreativeGate" in home.text and "Evidence ledger" in home.text

        # Evaluate stores the artifact text; /verdicts returns it for preview.
        resp = client.post("/evaluate", json={
            "artifact_id": "dash-test",
            "text": "Try our meal kits today. Save 30% on your first order.",
        })
        job = client.get(f"/jobs/{resp.json()['job_id']}").json()
        assert job["status"] == "done"

        listing = client.get("/verdicts").json()["verdicts"]
        assert len(listing) == 1
        entry = listing[0]
        assert entry["verdict"]["artifact_id"] == "dash-test"
        assert entry["verdict"]["runtime_ms"] is not None
        assert entry["artifact"]["text"].startswith("Try our meal kits")

        art = client.get("/artifact/dash-test").json()
        assert art["modality"] == "text"

        # Calibration overview: empty trail on a fresh db, grouped shape.
        overview = client.get("/calibration").json()
        assert overview == {"rungs": {}, "total_records": 0}

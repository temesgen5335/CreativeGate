"""Production-hardening invariants: durable jobs, token auth, the artifact
upload store, predictor cache persistence, and modality-aware gate rules."""

import json
import struct
import zlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from creativegate.engine import FunnelEngine
from creativegate.rungs import DeterministicGate
from creativegate.rungs.base import RungContext
from creativegate.schemas import Artifact, Modality
from creativegate.storage import Repository


def _png(width: int, height: int) -> bytes:
    ihdr = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    chunk = b"IHDR" + ihdr
    return (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(ihdr)) + chunk
            + struct.pack(">I", zlib.crc32(chunk)))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CREATIVEGATE_DB", str(tmp_path / "hard.db"))
    monkeypatch.setenv("CREATIVEGATE_ARTIFACT_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("CREATIVEGATE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("CREATIVEGATE_API_TOKEN", raising=False)
    import creativegate.api as api_mod
    monkeypatch.setattr(api_mod, "_repo", None)
    with TestClient(api_mod.app) as c:
        yield c


class TestDurableJobs:
    def test_job_state_survives_a_new_repository_handle(self, client, tmp_path):
        resp = client.post("/evaluate", json={"text": "Try our meal kits today. Shop now."})
        job_id = resp.json()["job_id"]
        # A fresh Repository over the same file (= a restarted process) must
        # see the finished job — state lives in the DB, not process memory.
        fresh = Repository(tmp_path / "hard.db")
        job = fresh.get_job(job_id)
        fresh.close()
        assert job is not None and job["status"] == "done"
        assert job["verdict_id"]

    def test_orphaned_jobs_marked_interrupted_at_startup(self, tmp_path):
        repo = Repository(tmp_path / "orphan.db")
        repo.create_job("job-orphan")
        repo.update_job("job-orphan", "running")
        assert repo.mark_stale_jobs_interrupted() == 1
        job = repo.get_job("job-orphan")
        repo.close()
        assert job["status"] == "interrupted"
        assert "restarted" in job["error"]

    def test_unknown_job_is_404(self, client):
        assert client.get("/jobs/job-nope").status_code == 404


class TestJobStateMachine:
    def test_legal_lifecycle(self, tmp_path):
        repo = Repository(tmp_path / "sm.db")
        repo.create_job("j1")
        repo.update_job("j1", "running")
        repo.update_job("j1", "done", verdict_id="v-x")
        assert repo.get_job("j1")["status"] == "done"
        repo.close()

    def test_terminal_states_cannot_regress(self, tmp_path):
        repo = Repository(tmp_path / "sm.db")
        repo.create_job("j1")
        repo.update_job("j1", "running")
        repo.update_job("j1", "done", verdict_id="v-x")
        with pytest.raises(ValueError, match="Illegal job transition"):
            repo.update_job("j1", "running")
        with pytest.raises(ValueError, match="Illegal job transition"):
            repo.update_job("j1", "error", error="late failure")
        assert repo.get_job("j1")["status"] == "done"  # history uncorrupted
        repo.close()

    def test_queued_cannot_jump_to_done(self, tmp_path):
        repo = Repository(tmp_path / "sm.db")
        repo.create_job("j1")
        with pytest.raises(ValueError, match="Illegal job transition"):
            repo.update_job("j1", "done", verdict_id="v-x")
        repo.close()

    def test_unknown_job_rejected(self, tmp_path):
        repo = Repository(tmp_path / "sm.db")
        with pytest.raises(ValueError, match="Unknown job"):
            repo.update_job("ghost", "running")
        repo.close()


class TestAuditTrail:
    def test_evaluation_leaves_a_complete_event_timeline(self, client):
        resp = client.post("/evaluate", json={
            "artifact_id": "audited-ad",
            "text": "Try our meal kits today. Save 30% on your first order."})
        job_id = resp.json()["job_id"]

        events = client.get("/audit", params={"subject": job_id}).json()["events"]
        names = [e["event"] for e in reversed(events)]      # chronological
        assert names == ["job.queued", "job.running", "job.done"]
        assert events[-1]["detail"]["artifact_id"] == "audited-ad"

        verdicts = client.get("/audit", params={"event": "verdict."}).json()["events"]
        assert verdicts and verdicts[0]["detail"]["artifact_id"] == "audited-ad"
        assert "score" in verdicts[0]["detail"] and "runtime_ms" in verdicts[0]["detail"]

    def test_upload_and_ground_truth_are_audited(self, client):
        client.post("/artifacts", files={
            "file": ("copy.txt", b"Order the bundle today. Shop now.", "text/plain")})
        records = [{"artifact_ref": f"a{i}", "modality": "text",
                    "outcomes": {"ctr": i / 100}} for i in range(6)]
        client.post("/ground-truth", json={"records": records})

        all_events = client.get("/audit").json()["events"]
        names = {e["event"] for e in all_events}
        assert "artifact.uploaded" in names
        assert "ground_truth.ingested" in names

    def test_audit_is_readable_without_token(self, client, monkeypatch):
        monkeypatch.setenv("CREATIVEGATE_API_TOKEN", "s3cret")
        assert client.get("/audit").status_code == 200  # reads stay open

    def test_interrupted_sweep_is_audited(self, tmp_path):
        repo = Repository(tmp_path / "sweep.db")
        repo.create_job("j-lost")
        repo.update_job("j-lost", "running")
        repo.mark_stale_jobs_interrupted()
        events = repo.recent_events(event_prefix="jobs.interrupted")
        assert events and events[0]["detail"]["job_ids"] == ["j-lost"]
        repo.close()


class TestTokenAuth:
    def test_mutations_require_token_when_set(self, client, monkeypatch):
        monkeypatch.setenv("CREATIVEGATE_API_TOKEN", "s3cret")
        body = {"text": "Shop now for great shoes."}
        assert client.post("/evaluate", json=body).status_code == 401
        assert client.post("/evaluate", json=body,
                           headers={"Authorization": "Bearer wrong"}).status_code == 401
        ok = client.post("/evaluate", json=body,
                         headers={"Authorization": "Bearer s3cret"})
        assert ok.status_code == 200

    def test_reads_stay_open_with_token_set(self, client, monkeypatch):
        monkeypatch.setenv("CREATIVEGATE_API_TOKEN", "s3cret")
        assert client.get("/verdicts").status_code == 200
        assert client.get("/calibration").status_code == 200
        assert client.get("/health").json()["auth"] == "token"

    def test_open_mode_when_unset(self, client):
        assert client.get("/health").json()["auth"] == "open"


class TestArtifactUpload:
    def test_text_upload_then_evaluate_by_reference(self, client):
        up = client.post("/artifacts", files={
            "file": ("headline_variant.txt", b"Try our coffee subscription today. Claim your offer.", "text/plain")})
        assert up.status_code == 200
        art = up.json()
        assert art["modality"] == "text"

        job = client.post("/evaluate", json={"artifact_id": art["artifact_id"]}).json()
        st = client.get(f"/jobs/{job['job_id']}").json()
        assert st["status"] == "done"
        verdict = client.get(f"/verdict/{st['verdict_id']}").json()
        assert verdict["eliminated"] is False  # CTA present, no banned phrases

    def test_image_upload_runs_structural_gate_only(self, client):
        up = client.post("/artifacts", files={
            "file": ("banner.png", _png(1200, 628), "image/png")})
        assert up.status_code == 200
        art = up.json()
        assert art["modality"] == "image" and art["stored_path"]

        job = client.post("/evaluate", json={"artifact_id": art["artifact_id"]}).json()
        st = client.get(f"/jobs/{job['job_id']}").json()
        verdict = client.get(f"/verdict/{st['verdict_id']}").json()
        # Text rules (required CTA, min words) must NOT fire on an image
        # without copy; scoring rungs skip; verdict is gate-evidence only.
        assert verdict["eliminated"] is False
        assert verdict["score"] is None

    def test_unsupported_extension_rejected(self, client):
        up = client.post("/artifacts", files={"file": ("clip.mp4", b"xxxx", "video/mp4")})
        assert up.status_code == 415

    def test_oversize_rejected(self, client, monkeypatch):
        monkeypatch.setenv("CREATIVEGATE_MAX_UPLOAD_MB", "0.0001")
        up = client.post("/artifacts", files={"file": ("big.txt", b"y" * 2000, "text/plain")})
        assert up.status_code == 413


class TestGroundTruthSetAPI:
    CORPUS = Path(__file__).parent.parent / "examples" / "ground-truth-example.json"

    def test_upload_corpus_enables_scored_verdicts(self, client):
        payload = json.loads(self.CORPUS.read_text())
        resp = client.post("/ground-truth-sets", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["usable"] == 14 and body["warnings"] == []

        # Default profile names 'synthetic-starter'; the freshly-uploaded set
        # must be used via the latest-set fallback — no profile editing.
        job = client.post("/evaluate", json={
            "text": "Meet your new favorite trail shoes. Free shipping on your first order. "
                    "Shop now — sale ends Friday."}).json()
        st = client.get(f"/jobs/{job['job_id']}").json()
        assert st["status"] == "done"
        verdict = client.get(f"/verdict/{st['verdict_id']}").json()
        assert verdict["eliminated"] is False
        assert verdict["score"] is not None          # predictor trained, judge anchored
        # No outcomes reported yet => nothing calibrated => honest labeling.
        assert "DIRECTIONAL ONLY" in verdict["confidence_note"]

    def test_full_bootstrap_produces_weighted_verdicts(self, client):
        payload = json.loads(self.CORPUS.read_text())
        client.post("/ground-truth-sets", json=payload)
        for r in payload["records"]:
            client.post("/evaluate", json={"artifact_id": r["artifact_ref"], "text": r["text"]})
        resp = client.post("/ground-truth", json={"records": payload["records"]})
        recalibrated = resp.json()["recalibrated"]
        assert {r["rung"] for r in recalibrated} >= {"performance_predictor", "judge_ensemble"}

        job = client.post("/evaluate", json={
            "text": "Meet your new favorite trail shoes. Free shipping on your first order. "
                    "Shop now — sale ends Friday."}).json()
        st = client.get(f"/jobs/{job['job_id']}").json()
        verdict = client.get(f"/verdict/{st['verdict_id']}").json()
        assert "DIRECTIONAL ONLY" not in verdict["confidence_note"]
        assert "Calibration-weighted fusion" in verdict["confidence_note"]

    def test_undersized_set_rejected(self, client):
        resp = client.post("/ground-truth-sets", json={
            "name": "tiny",
            "records": [{"artifact_ref": "a1", "modality": "text",
                         "text": "One ad. Shop now.", "outcomes": {"ctr": 0.02}}]})
        assert resp.status_code == 422

    def test_small_set_accepted_with_warning(self, client):
        records = [{"artifact_ref": f"a{i}", "modality": "text",
                    "text": f"Ad number {i} with an offer. Shop now.",
                    "outcomes": {"ctr": 0.01 * (i + 1)}} for i in range(3)]
        resp = client.post("/ground-truth-sets", json={"name": "small", "records": records})
        assert resp.status_code == 200
        assert resp.json()["warnings"]  # predictor will refuse below 10

    def test_listing(self, client):
        payload = json.loads(self.CORPUS.read_text())
        client.post("/ground-truth-sets", json=payload)
        sets = client.get("/ground-truth-sets").json()["sets"]
        assert {"name": "starter-live", "records": 14} in sets


class TestProfilesPerArtifactClass:
    BANNER_PROFILE = {
        "name": "banner-web-v1",
        "target_metric": "ctr",
        "ground_truth_set": "banner-outcomes",   # its own corpus, not the default's
        "seed": 7,
        "rungs": [
            {"name": "deterministic_gate",
             "config": {"banned_phrases": ["click here"], "min_words": 3}},
            {"name": "performance_predictor", "threshold": 0.1},
            {"name": "judge_ensemble",
             "config": {"rubric": "Judge for display-banner attention capture.",
                        "num_anchors": 3, "ensemble_passes": 1}},
        ],
    }

    def test_profile_persists_across_restart(self, client, tmp_path, monkeypatch):
        resp = client.post("/profiles", json=self.BANNER_PROFILE)
        assert resp.status_code == 200

        # Simulated restart: fresh repository handle over the same file.
        import creativegate.api as api_mod
        monkeypatch.setattr(api_mod, "_repo", None)
        client2 = TestClient(api_mod.app)
        assert "banner-web-v1" in client2.get("/profiles").json()["profiles"]
        detail = client2.get("/profiles/banner-web-v1").json()
        assert detail["ground_truth_set"] == "banner-outcomes"

    def test_profile_criteria_actually_apply(self, client):
        client.post("/profiles", json=self.BANNER_PROFILE)
        # 'click here' is legal under the default profile, banned under banner's.
        job = client.post("/evaluate", json={
            "text": "Great deals on shoes, click here to shop now.",
            "profile": "banner-web-v1"}).json()
        st = client.get(f"/jobs/{job['job_id']}").json()
        verdict = client.get(f"/verdict/{st['verdict_id']}").json()
        assert verdict["eliminated"] and verdict["eliminated_by"] == "deterministic_gate"
        assert "click here" in verdict["validity_summary"]

    def test_custom_profile_never_falls_back_to_foreign_corpus(self, client):
        # A stored corpus exists (under another name), but banner-web-v1 names
        # its own missing set: learned rungs must refuse, not borrow criteria.
        payload = json.loads((Path(__file__).parent.parent / "examples" /
                              "ground-truth-example.json").read_text())
        client.post("/ground-truth-sets", json=payload)
        client.post("/profiles", json=self.BANNER_PROFILE)
        job = client.post("/evaluate", json={
            "text": "Banner headline with a strong offer. Shop now.",
            "profile": "banner-web-v1"}).json()
        st = client.get(f"/jobs/{job['job_id']}").json()
        verdict = client.get(f"/verdict/{st['verdict_id']}").json()
        assert verdict["score"] is None           # refused: no banner corpus
        flags = " ".join(verdict["flags"])
        assert "predictor" in flags

    def test_default_profile_is_immutable(self, client):
        resp = client.post("/profiles", json={"name": "default-text-v0.1", "rungs": []})
        assert resp.status_code == 409

    def test_unknown_profile_is_404_with_known_list(self, client):
        job = client.post("/evaluate", json={"text": "x", "profile": "ghost"}).json()
        st = client.get(f"/jobs/{job['job_id']}").json()
        assert st["status"] == "error" and "Unknown profile" in st["error"]


class TestJudgeRubricConfig:
    def test_custom_rubric_reaches_the_comparator(self, ground_truth, harness):
        from creativegate.rungs import CalibratedJudgeEnsemble
        from creativegate.rungs.base import RungContext
        seen_prompts = []

        class Spy:
            name, fidelity = "spy", "full"
            def compare(self, prompt, a, b, seed):
                seen_prompts.append(prompt)
                return "A"

        rung = CalibratedJudgeEnsemble()
        ctx = RungContext(
            config={"rubric": "Judge banners for attention capture.",
                    "num_anchors": 3, "ensemble_passes": 1},
            ground_truth=ground_truth, providers={"llm": Spy()})
        result = rung.evaluate(
            Artifact(id="b", modality=Modality.TEXT, text="A banner. Shop now."), ctx)
        assert set(seen_prompts) == {"Judge banners for attention capture."}
        pred = [e for e in result.evidence if e.kind == "prediction"][0]
        assert pred.detail["prompt_version"].startswith("custom-")


class TestGateModalityScoping:
    def test_no_text_means_no_text_checks(self):
        gate = DeterministicGate()
        ctx = RungContext(config={
            "banned_phrases": ["miracle"], "min_words": 4,
            "required_elements": [{"name": "cta", "pattern": r"\bshop\b"}],
        })
        r = gate.evaluate(Artifact(id="i", modality=Modality.IMAGE, text=None), ctx)
        assert r.passed is True
        assert all(e.detail.get("check") not in
                   {"banned_phrase", "required_element", "min_words"} for e in r.evidence)

    def test_empty_string_text_still_checked(self):
        # "" is a claim of empty copy; None is absence of copy.
        gate = DeterministicGate()
        ctx = RungContext(config={"min_words": 4})
        r = gate.evaluate(Artifact(id="t", modality=Modality.TEXT, text=""), ctx)
        assert r.passed is False


class TestPredictorCachePersistence:
    def test_model_persists_across_cache_clear(self, tmp_path, monkeypatch, ground_truth, harness, profile):
        monkeypatch.setenv("CREATIVEGATE_CACHE_DIR", str(tmp_path / "cache"))
        import creativegate.rungs.predictor as pred_mod
        monkeypatch.setattr(pred_mod, "_MODEL_CACHE", {})

        artifact = Artifact(id="x", modality=Modality.TEXT,
                            text="Meet your new favorite meal kits. Free shipping. Try it free.")
        engine = FunnelEngine(profile, ground_truth=ground_truth, harness=harness)
        v1 = engine.evaluate(artifact, record_predictions=False)
        pickles = list((tmp_path / "cache").glob("predictor-*.pkl"))
        assert len(pickles) == 1  # trained model written to disk

        # Simulate a process restart: empty in-memory cache, model loads from
        # disk and produces identical scores.
        monkeypatch.setattr(pred_mod, "_MODEL_CACHE", {})
        engine2 = FunnelEngine(profile, ground_truth=ground_truth, harness=harness)
        v2 = engine2.evaluate(artifact, record_predictions=False)
        assert v1.score == v2.score

    def test_corrupt_cache_falls_back_to_retraining(self, tmp_path, monkeypatch, ground_truth, harness, profile):
        monkeypatch.setenv("CREATIVEGATE_CACHE_DIR", str(tmp_path / "cache"))
        import creativegate.rungs.predictor as pred_mod
        monkeypatch.setattr(pred_mod, "_MODEL_CACHE", {})
        (tmp_path / "cache").mkdir()
        artifact = Artifact(id="x", modality=Modality.TEXT,
                            text="Meet your new favorite meal kits. Free shipping. Try it free.")
        engine = FunnelEngine(profile, ground_truth=ground_truth, harness=harness)
        v1 = engine.evaluate(artifact, record_predictions=False)

        for p in (tmp_path / "cache").glob("predictor-*.pkl"):
            p.write_bytes(b"not a pickle")
        monkeypatch.setattr(pred_mod, "_MODEL_CACHE", {})
        v2 = engine.evaluate(artifact, record_predictions=False)
        assert v1.score == v2.score  # retrained deterministically

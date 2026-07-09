"""Provider chain invariants: fallback order, cooldown, terminal heuristic,
honest fidelity reporting, and env-driven resolution — all offline."""

import pytest

from creativegate.envfile import load_env_file
from creativegate.providers import FallbackLLM, NullLLM, OpenAICompatibleLLM, resolve_llm
from creativegate.providers.llm import LLMProvider, PROVIDER_SPECS


class Working(LLMProvider):
    fidelity = "full"

    def __init__(self, name="working", answer="A"):
        self.name = name
        self.answer = answer
        self.calls = 0

    def compare(self, prompt, a, b, seed):
        self.calls += 1
        return self.answer


class Broken(LLMProvider):
    fidelity = "full"
    name = "broken"

    def __init__(self):
        self.calls = 0

    def compare(self, prompt, a, b, seed):
        self.calls += 1
        raise ConnectionError("provider down")


class TestFallbackChain:
    def test_primary_answers_when_healthy(self):
        primary, backup = Working("primary"), Working("backup", answer="B")
        chain = FallbackLLM([primary, backup])
        assert chain.compare("p", "a", "b", 7) == "A"
        assert backup.calls == 0
        assert chain.fidelity == "full" and chain.name == "primary"

    def test_failure_falls_through_and_cools_down(self):
        broken, backup = Broken(), Working("backup", answer="B")
        chain = FallbackLLM([broken, backup])
        assert chain.compare("p", "a", "b", 7) == "B"
        assert broken.calls == 1
        # Cooldown: the broken provider is not retried on the next call.
        assert chain.compare("p", "a", "b", 8) == "B"
        assert broken.calls == 1
        assert chain.fidelity == "full"       # an API provider still answered
        assert chain.name == "backup"

    def test_all_apis_down_degrades_to_heuristic_never_fails(self):
        chain = FallbackLLM([Broken(), Broken()])
        answer = chain.compare("p", "Shop our great sale now", "meh", 7)
        assert answer in ("A", "B")
        assert chain.fidelity == "degraded"   # heuristic served the comparison
        assert "null-heuristic" in chain.name

    def test_mixed_run_reports_degraded(self):
        # First call served by API, then it breaks mid-run is simulated by a
        # chain where the API is already cooling: fidelity must be honest
        # about the worst thing that served any comparison.
        broken = Broken()
        chain = FallbackLLM([broken])
        chain.compare("p", "a", "b", 7)       # falls to heuristic
        assert chain.fidelity == "degraded"


class TestEnvResolution:
    def test_no_keys_returns_bare_heuristic(self):
        assert isinstance(resolve_llm(), NullLLM)

    def test_keys_build_chain_in_preference_order(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        monkeypatch.setenv("GEMINI_API_KEY", "aiza_test")
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        chain = resolve_llm()
        assert isinstance(chain, FallbackLLM)
        names = [p.name for p in chain.chain]
        assert names[0].startswith("openai-compatible:llama")   # groq preferred
        assert names[-1] == "null-heuristic"                     # terminal rung
        assert len(chain.chain) == 4                             # 3 APIs + null

    def test_custom_endpoint_ranks_first(self, monkeypatch):
        monkeypatch.setenv("CREATIVEGATE_LLM_API_KEY", "k")
        monkeypatch.setenv("CREATIVEGATE_LLM_BASE_URL", "https://my-gateway.example/v1")
        monkeypatch.setenv("CREATIVEGATE_LLM_MODEL", "my-model")
        monkeypatch.setenv("OPENAI_API_KEY", "sk_test")
        chain = resolve_llm()
        assert chain.chain[0].base_url == "https://my-gateway.example/v1"
        assert chain.chain[0].model == "my-model"

    def test_explicit_rung_config_wins(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
        chain = resolve_llm({"api_key": "cfg-key", "model": "cfg-model"})
        assert len(chain.chain) == 2                             # config + null only
        assert chain.chain[0].model == "cfg-model"

    def test_every_spec_has_distinct_env_and_url(self):
        keys = [s[1] for s in PROVIDER_SPECS]
        urls = [s[4] for s in PROVIDER_SPECS]
        assert len(set(keys)) == len(keys) and len(set(urls)) == len(urls)


class TestEnvFile:
    def test_loads_without_overriding(self, tmp_path, monkeypatch):
        env = tmp_path / ".env"
        env.write_text("# comment\nFOO_A=file\nFOO_B='quoted'\nBROKEN LINE\n")
        monkeypatch.setenv("FOO_A", "shell")
        monkeypatch.delenv("FOO_B", raising=False)
        loaded = load_env_file(env)
        import os
        assert loaded == 1
        assert os.environ["FOO_A"] == "shell"   # existing env wins
        assert os.environ["FOO_B"] == "quoted"
        monkeypatch.delenv("FOO_B")

    def test_missing_file_is_noop(self, tmp_path):
        assert load_env_file(tmp_path / "absent.env") == 0

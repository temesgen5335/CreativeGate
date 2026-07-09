import pytest

from creativegate.calibration import CalibrationHarness, SyntheticWorld
from creativegate.profiles import default_profile
from creativegate.storage import Repository

_PROVIDER_ENV = [
    "CREATIVEGATE_LLM_API_KEY", "CREATIVEGATE_LLM_PROVIDER", "LLM_PROVIDER",
    "OPENAI_API_KEY", "GROQ_API_KEY", "GEMINI_API_KEY",
    "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
]


@pytest.fixture(autouse=True)
def _offline_suite(monkeypatch):
    """The suite must stay fully offline: any LLM key in the developer's
    shell would otherwise route judge comparisons to a live API."""
    for var in _PROVIDER_ENV:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def repo(tmp_path):
    r = Repository(tmp_path / "test.db")
    yield r
    r.close()


@pytest.fixture
def harness(repo):
    return CalibrationHarness(repo)


@pytest.fixture
def world():
    return SyntheticWorld(seed=7)


@pytest.fixture
def ground_truth(world):
    return world.generate_set(80)


@pytest.fixture
def profile():
    return default_profile(seed=7)

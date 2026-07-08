import pytest

from creativegate.calibration import CalibrationHarness, SyntheticWorld
from creativegate.profiles import default_profile
from creativegate.storage import Repository


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

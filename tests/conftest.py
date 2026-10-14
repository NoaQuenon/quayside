from pathlib import Path

import pytest

SCENARIOS = Path(__file__).resolve().parents[1] / "scenarios"


@pytest.fixture
def scenarios_dir() -> Path:
    return SCENARIOS

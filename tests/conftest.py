import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "mers-qatar-2026" / "assessment.json"


@pytest.fixture(scope="session")
def example_data() -> dict:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


@pytest.fixture
def data(example_data) -> dict:
    """A fresh deep copy of the worked example that tests may mutate."""
    return copy.deepcopy(example_data)

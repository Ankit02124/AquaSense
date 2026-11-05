import sys
from pathlib import Path

import pytest
import yaml

APP = Path(__file__).resolve().parents[1] / "app" / "python"
sys.path.insert(0, str(APP))


class Clock:
    def __init__(self, t=1_790_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def cfg():
    return yaml.safe_load((APP / "config.yaml").read_text())

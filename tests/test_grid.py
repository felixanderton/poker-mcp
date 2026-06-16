import json
from pathlib import Path

import pytest

from engine.adapter import _extract
from rendering.grid import GridMetric, render_grid

FIXTURE = Path(__file__).parent / "fixtures" / "output_result.json"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _oop_strategy() -> dict[str, dict[str, float]]:
    tree = json.loads(FIXTURE.read_text())
    oop, _, _, _ = _extract(tree)
    return oop


@pytest.mark.parametrize("metric", ["bet", "check", "fold", "blended"])
def test_render_grid_returns_png(metric: GridMetric) -> None:
    png = render_grid(_oop_strategy(), metric, title="test")
    assert png.startswith(_PNG_MAGIC)
    assert len(png) > 1000


def test_render_grid_handles_empty_strategy() -> None:
    png = render_grid({}, "bet", title="empty")
    assert png.startswith(_PNG_MAGIC)

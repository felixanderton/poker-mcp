import json
from pathlib import Path

import pytest

from engine.adapter import _extract
from rendering.grid import GridMetric, class_grid, render_grid

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


def test_class_grid_aggregates_by_class() -> None:
    grid = class_grid(_oop_strategy())
    # AsAh/AsAc both map to class "AA"; fixture has them betting 0.80.
    assert "AA" in grid
    assert grid["AA"]["bet"] == 0.80
    assert grid["AA"]["check"] == 0.20
    assert set(grid["AA"]["actions"]) == {"CHECK", "BET 50"}
    # AhKh (AKs) and AhKs (AKo) are distinct classes.
    assert grid["AKs"]["bet"] == 0.50
    assert grid["AKo"]["bet"] == 0.30

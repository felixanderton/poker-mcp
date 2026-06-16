"""Render a solved strategy as a 13x13 starting-hand grid PNG.

The grid is the standard hand matrix (rank A top-left, pairs on the diagonal,
suited above, offsuit below). Each cell aggregates the chosen metric over the
concrete combos of that hand class present in the solver output.
"""

from __future__ import annotations

import io
from typing import Literal, TypedDict

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from engine.models import ComboStrategy
from engine.ranges import RANKS, combo_to_class, grid_class

type GridMetric = Literal["bet", "check", "fold", "blended"]

_N = len(RANKS)
_CLASS_POS: dict[str, tuple[int, int]] = {
    grid_class(r, c): (r, c) for r in range(_N) for c in range(_N)
}
_METRIC_CMAP: dict[str, str] = {"bet": "Reds", "check": "Greens", "fold": "Blues"}
_AGGRESSIVE = ("BET", "RAISE", "ALLIN", "DONK")
_PASSIVE = ("CHECK", "CALL")


def _category_fractions(actions: dict[str, float]) -> tuple[float, float, float]:
    """Return ``(aggressive, passive, fold)`` probability mass for one combo."""
    agg = passive = fold = 0.0
    for action, prob in actions.items():
        upper = action.upper()
        if upper.startswith(_AGGRESSIVE):
            agg += prob
        elif upper.startswith(_PASSIVE):
            passive += prob
        elif upper.startswith("FOLD"):
            fold += prob
    return agg, passive, fold


class ClassCell(TypedDict):
    """Per-hand-class aggregate used by the interactive grid app."""

    bet: float
    check: float
    fold: float
    actions: dict[str, float]


type ClassGrid = dict[str, ClassCell]


def class_grid(strategy: ComboStrategy) -> ClassGrid:
    """Aggregate a combo strategy into per-169-class cells for the interactive UI."""
    bet: dict[str, float] = {}
    check: dict[str, float] = {}
    fold: dict[str, float] = {}
    count: dict[str, int] = {}
    actions: dict[str, dict[str, float]] = {}
    for combo, combo_actions in strategy.items():
        cls = combo_to_class(combo)
        agg, passive, folded = _category_fractions(combo_actions)
        bet[cls] = bet.get(cls, 0.0) + agg
        check[cls] = check.get(cls, 0.0) + passive
        fold[cls] = fold.get(cls, 0.0) + folded
        count[cls] = count.get(cls, 0) + 1
        acc = actions.setdefault(cls, {})
        for label, freq in combo_actions.items():
            acc[label] = acc.get(label, 0.0) + freq
    grid: ClassGrid = {}
    for cls, n in count.items():
        grid[cls] = ClassCell(
            bet=round(bet[cls] / n, 4),
            check=round(check[cls] / n, 4),
            fold=round(fold[cls] / n, 4),
            actions={k: round(v / n, 4) for k, v in actions[cls].items()},
        )
    return grid


def _scalar(actions: dict[str, float], metric: GridMetric) -> float:
    agg, passive, fold = _category_fractions(actions)
    match metric:
        case "bet":
            return agg
        case "check":
            return passive
        case "fold":
            return fold
        case "blended":
            raise ValueError("blended metric has no scalar value")


def _aggregate_scalar(strategy: ComboStrategy, metric: GridMetric) -> np.ndarray:
    totals = np.zeros((_N, _N))
    counts = np.zeros((_N, _N))
    for combo, actions in strategy.items():
        row, col = _CLASS_POS[combo_to_class(combo)]
        totals[row, col] += _scalar(actions, metric)
        counts[row, col] += 1
    grid = np.full((_N, _N), np.nan)
    mask = counts > 0
    grid[mask] = totals[mask] / counts[mask]
    return grid


def _aggregate_rgb(strategy: ComboStrategy) -> tuple[np.ndarray, np.ndarray]:
    rgb_totals = np.zeros((_N, _N, 3))
    counts = np.zeros((_N, _N))
    for combo, actions in strategy.items():
        row, col = _CLASS_POS[combo_to_class(combo)]
        agg, passive, fold = _category_fractions(actions)
        # R = aggressive, G = passive (check/call), B = fold.
        rgb_totals[row, col] += (agg, passive, fold)
        counts[row, col] += 1
    image = np.ones((_N, _N, 3))  # empty cells render white
    mask = counts > 0
    image[mask] = rgb_totals[mask] / counts[mask][:, None]
    return image, counts


def render_grid(
    strategy: ComboStrategy,
    metric: GridMetric,
    title: str,
) -> bytes:
    """Render ``strategy`` as a 13x13 grid PNG and return the raw bytes."""
    fig, ax = plt.subplots(figsize=(8, 8))

    if metric == "blended":
        image, counts = _aggregate_rgb(strategy)
        ax.imshow(image, interpolation="nearest")
        present = counts > 0
        values: np.ndarray | None = None
    else:
        grid = _aggregate_scalar(strategy, metric)
        ax.imshow(grid, cmap=_METRIC_CMAP[metric], vmin=0.0, vmax=1.0, interpolation="nearest")
        present = ~np.isnan(grid)
        values = grid

    for row in range(_N):
        for col in range(_N):
            if not present[row, col]:
                continue
            label = grid_class(row, col)
            if values is not None:
                label = f"{label}\n{values[row, col] * 100:.0f}%"
            ax.text(
                col,
                row,
                label,
                ha="center",
                va="center",
                fontsize=6,
                color="black",
            )

    ax.set_xticks(range(_N), list(RANKS), fontsize=8)
    ax.set_yticks(range(_N), list(RANKS), fontsize=8)
    ax.set_xlabel("second card")
    ax.set_ylabel("first card")
    subtitle = "R=bet/raise  G=check/call  B=fold" if metric == "blended" else f"{metric} frequency"
    ax.set_title(f"{title}\n{subtitle}", fontsize=10)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=130)
    plt.close(fig)
    return buffer.getvalue()

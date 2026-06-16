"""Pydantic models shared between the MCP tool layer and the solver engine.

All solver input is validated here before any subprocess is spawned.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator

from engine.ranges import normalize_range

_CARD_RE = re.compile(r"^[2-9TJQKA][cdhs]$")

# combo (e.g. "AhKh") -> action label (e.g. "BET 50") -> probability in [0, 1]
type ComboStrategy = dict[str, dict[str, float]]


class SolveRequest(BaseModel):
    """A fully validated postflop spot ready to be serialised for the solver."""

    model_config = ConfigDict(frozen=True)

    oop_range: str = Field(description="Out-of-position range, solver syntax e.g. 'AA,KK,AKs:0.5'")
    ip_range: str = Field(description="In-position range, solver syntax")
    board: str = Field(description="3-5 board cards, e.g. 'Qs Jh 2h' (turn/river add cards)")
    pot: float = Field(gt=0, description="Pot size at the start of the modelled street")
    effective_stack: float = Field(gt=0, description="Effective stack behind for both players")

    bet_sizes: list[float] = Field(
        default_factory=lambda: [50.0],
        description="Bet/donk sizes as percent of pot, applied on every street",
    )
    raise_sizes: list[float] = Field(
        default_factory=lambda: [60.0],
        description="Raise sizes as percent of the facing bet",
    )
    include_allin: bool = Field(default=True, description="Add an all-in action on every street")
    allin_threshold: float = Field(
        default=0.67,
        ge=0,
        le=1,
        description="Collapse a bet to all-in when it exceeds this fraction of the stack",
    )

    accuracy: float = Field(
        default=1.0,
        gt=0,
        description="Target exploitability as percent of pot; solving stops once reached. "
        "Lower is more precise but slower; ~1-2% is plenty for most analysis.",
    )
    max_iterations: int = Field(
        default=100,
        ge=1,
        le=2000,
        description="Cap on solver iterations; it always returns the best strategy reached.",
    )
    time_limit_s: float = Field(
        default=180.0,
        gt=0,
        le=540,
        description="Hard wall-clock safety cap. Hitting it kills the solve with no result, so "
        "prefer bounding via accuracy/max_iterations; this is only a backstop.",
    )
    threads: int = Field(default=0, ge=0, description="Solver threads; 0 selects all cores")
    use_isomorphism: bool = Field(default=True)

    @field_validator("oop_range", "ip_range")
    @classmethod
    def _validate_range(cls, value: str) -> str:
        return normalize_range(value)

    @field_validator("board")
    @classmethod
    def _validate_board(cls, value: str) -> str:
        cards = [c.strip() for c in re.split(r"[,\s]+", value) if c.strip()]
        if not 3 <= len(cards) <= 5:
            raise ValueError("Board must have between 3 and 5 cards")
        for card in cards:
            if not _CARD_RE.match(card):
                raise ValueError(f"Malformed board card: {card!r}")
        if len(set(cards)) != len(cards):
            raise ValueError("Board contains duplicate cards")
        return ",".join(cards)

    @field_validator("bet_sizes", "raise_sizes")
    @classmethod
    def _validate_sizes(cls, value: list[float]) -> list[float]:
        if not value:
            raise ValueError("At least one size is required")
        if any(size <= 0 for size in value):
            raise ValueError("Sizes must be positive")
        return value

    @property
    def board_cards(self) -> list[str]:
        return self.board.split(",")


class SolveResult(BaseModel):
    """Normalised solver output for one spot."""

    board: str
    pot: float
    effective_stack: float
    iterations: int | None = None
    exploitability_pct: float | None = Field(
        default=None, description="Final exploitability reached, as percent of pot"
    )
    solve_time_s: float
    converged: bool = Field(description="Whether the accuracy target was reached before limits")

    oop_root_actions: list[str]
    ip_actions_facing_check: list[str]
    # Per-combo strategies used for the grid and per-hand lookups.
    oop_strategy: ComboStrategy
    ip_strategy: ComboStrategy

"""Range parsing helpers and preflop presets.

The solver consumes range strings in its own syntax (e.g. ``"AA,KK,AKs:0.5"``),
so most user-supplied ranges are passed straight through. This module provides:

* validation/normalisation of a range string,
* mapping a concrete combo from the solver output (e.g. ``"AhKh"``) to its
  169-class label (e.g. ``"AKs"``),
* the canonical 13x13 grid layout, and
* named preflop presets so an LLM can fill ranges without enumerating combos.
"""

from __future__ import annotations

import re

RANKS: str = "AKQJT98765432"
SUITS: str = "cdhs"
_RANK_INDEX: dict[str, int] = {r: i for i, r in enumerate(RANKS)}

# A concrete combo as dumped by the solver, e.g. "AhKh" or "7c7d".
_COMBO_RE = re.compile(r"^([2-9TJQKA])([cdhs])([2-9TJQKA])([cdhs])$")
# A single range token, e.g. "AA", "AKs", "QJo", "T9s:0.5", "99:0.75", "ATs+".
# A trailing "+" means "this hand and stronger", per the solver's range syntax.
_TOKEN_RE = re.compile(r"^[2-9TJQKA]{2}[so]?\+?(:\d*\.?\d+)?$")

type HandClass = str
type RangeString = str


def combo_to_class(combo: str) -> HandClass:
    """Map a concrete combo like ``"AhKh"`` to its 169-class label like ``"AKs"``."""
    match = _COMBO_RE.match(combo)
    if match is None:
        raise ValueError(f"Not a valid combo: {combo!r}")
    r1, s1, r2, s2 = match.groups()
    if _RANK_INDEX[r1] <= _RANK_INDEX[r2]:
        high, low, high_suit, low_suit = r1, r2, s1, s2
    else:
        high, low, high_suit, low_suit = r2, r1, s2, s1
    if high == low:
        return f"{high}{low}"
    suited = "s" if high_suit == low_suit else "o"
    return f"{high}{low}{suited}"


def grid_class(row: int, col: int) -> HandClass:
    """Return the hand class at grid position ``(row, col)``.

    Diagonal is pairs, upper triangle (``col > row``) is suited, lower triangle
    is offsuit -- the standard hand-matrix layout with rank A in the top-left.
    """
    hi, lo = RANKS[row], RANKS[col]
    if row == col:
        return f"{hi}{lo}"
    if col > row:
        return f"{hi}{lo}s"
    return f"{RANKS[col]}{RANKS[row]}o"


def normalize_range(range_str: str) -> str:
    """Validate a comma-separated range string and return it trimmed.

    Raises ``ValueError`` on the first malformed token so bad input is rejected
    at the system boundary before the solver subprocess is spawned.
    """
    tokens = [t.strip() for t in range_str.split(",") if t.strip()]
    if not tokens:
        raise ValueError("Range is empty")
    for token in tokens:
        if not _TOKEN_RE.match(token):
            raise ValueError(f"Malformed range token: {token!r}")
    return ",".join(tokens)


# Named preflop presets. Deliberately compact, ~100bb cash-game style defaults
# that an LLM can pick by name; users can always pass a custom range instead.
PRESETS: dict[str, RangeString] = {
    "RFI_UTG": ("77+,AJs+,KQs,AKo,AQo,ATs+,KJs+,QJs,JTs,T9s,98s"),
    "RFI_CO": ("55+,A2s+,K9s+,Q9s+,J9s+,T8s+,97s+,87s,76s,65s,54s," "ATo+,KJo+,QJo,AKo,AQo"),
    "RFI_BTN": (
        "22+,A2s+,K5s+,Q7s+,J7s+,T7s+,96s+,86s+,75s+,64s+,54s,43s,"
        "A2o+,K9o+,Q9o+,J9o+,T9o,98o,87o"
    ),
    "3BET_VALUE": "QQ+,AKs,AKo,AQs",
    "3BET_BLUFF": "A5s,A4s,A3s,KJs,QTs,JTs,T9s,98s,76s",
    "BB_DEFEND_VS_BTN": (
        "22+,A2s+,K2s+,Q4s+,J6s+,T6s+,96s+,85s+,74s+,64s+,53s+,43s,"
        "A2o+,K7o+,Q8o+,J8o+,T8o+,97o+,87o,76o,65o"
    ),
}


def list_presets() -> dict[str, RangeString]:
    """Return the available preflop presets keyed by name."""
    return dict(PRESETS)

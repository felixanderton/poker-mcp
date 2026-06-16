"""FastMCP server exposing the TexasSolver GTO engine over streamable-http.

Tools:
    * ``solve_spot``   -- solve a postflop spot, return frequencies/EV + a 13x13 grid image
    * ``explain_hand`` -- solve a spot and explain one specific hand's strategy
    * ``list_presets`` -- list the built-in preflop range presets

Auth is a static bearer token read from ``SOLVER_TOKEN`` and enforced by an ASGI
middleware before any tool runs. The token is injected at runtime from Google
Secret Manager on Cloud Run.
"""

from __future__ import annotations

import hmac
import logging
import os
from typing import Literal

from fastmcp import FastMCP
from fastmcp.utilities.types import Image
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from engine.adapter import solve
from engine.models import ComboStrategy, SolveRequest, SolveResult
from engine.ranges import combo_to_class, list_presets
from rendering.grid import GridMetric, render_grid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("poker_mcp")

TOKEN_ENV = "SOLVER_TOKEN"
_HEALTH_PATH = "/healthz"

mcp: FastMCP = FastMCP(
    "poker-mcp",
    instructions=(
        "Solve postflop Texas Hold'em spots with a GTO solver. Provide ranges in solver "
        "syntax (e.g. 'AA,KK,AKs:0.5'), a 3-5 card board, pot, and effective stack. Tools "
        "return action frequencies, exploitability, and a 13x13 starting-hand strategy grid."
    ),
)


@mcp.custom_route(_HEALTH_PATH, methods=["GET"])
async def healthz(_: Request) -> Response:
    return JSONResponse({"status": "ok"})


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Reject requests whose bearer token does not match ``SOLVER_TOKEN``."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        super().__init__(app)
        self._token = token

    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.url.path == _HEALTH_PATH:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(presented, self._token):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def _build_request(**kwargs: object) -> SolveRequest:
    return SolveRequest.model_validate(kwargs)


def _overall(strategy: ComboStrategy) -> dict[str, float]:
    """Average action frequencies across every combo in a strategy."""
    if not strategy:
        return {}
    totals: dict[str, float] = {}
    for actions in strategy.values():
        for action, prob in actions.items():
            totals[action] = totals.get(action, 0.0) + prob
    n = len(strategy)
    return {action: round(total / n, 4) for action, total in totals.items()}


def _class_breakdown(strategy: ComboStrategy, hand: str) -> dict[str, float]:
    """Aggregate action frequencies for all combos belonging to ``hand``'s class."""
    target = hand if len(hand) <= 3 else combo_to_class(hand)
    combos = {c: a for c, a in strategy.items() if combo_to_class(c) == target}
    return _overall(combos)


def _fmt_freqs(freqs: dict[str, float]) -> str:
    if not freqs:
        return "  (no actions / hand not in range)"
    return "\n".join(f"  {action}: {prob * 100:.1f}%" for action, prob in freqs.items())


def _summary(result: SolveResult) -> str:
    conv = "yes" if result.converged else "no (stopped at iteration/time limit)"
    expl = (
        f"{result.exploitability_pct:.3f}% of pot"
        if result.exploitability_pct is not None
        else "unknown"
    )
    return (
        f"Board {result.board} | pot {result.pot:g} | stack {result.effective_stack:g}\n"
        f"Solved in {result.solve_time_s:g}s, {result.iterations} iterations | "
        f"exploitability {expl} | converged: {conv}\n\n"
        f"OOP first-action frequencies (averaged over range):\n"
        f"{_fmt_freqs(_overall(result.oop_strategy))}\n\n"
        f"IP frequencies facing a check:\n"
        f"{_fmt_freqs(_overall(result.ip_strategy))}"
    )


@mcp.tool
def solve_spot(
    oop_range: str,
    ip_range: str,
    board: str,
    pot: float,
    effective_stack: float,
    bet_sizes: list[float] | None = None,
    raise_sizes: list[float] | None = None,
    accuracy: float = 0.5,
    max_iterations: int = 150,
    time_limit_s: float = 60.0,
    grid_for: Literal["oop", "ip"] = "oop",
    grid_metric: GridMetric = "bet",
) -> list[str | Image]:
    """Solve a postflop spot and return GTO frequencies plus a 13x13 strategy grid.

    Ranges use solver syntax, e.g. ``"AA,KK,QQ,AKs,AKo:0.5"``. Board is 3-5 cards like
    ``"Qs Jh 2h"`` (flop) or ``"Qs Jh 2h 8d"`` (turn). ``bet_sizes``/``raise_sizes`` are
    percentages (of pot / of the facing bet); defaults are ``[50]`` and ``[60]`` plus all-in.
    ``grid_for`` chooses whose strategy to plot (``oop`` = first to act, ``ip`` = facing a
    check); ``grid_metric`` is ``bet``, ``check``, ``fold`` or ``blended`` (RGB mix).

    Returns a text summary followed by the grid image rendered inline.
    """
    request = _build_request(
        oop_range=oop_range,
        ip_range=ip_range,
        board=board,
        pot=pot,
        effective_stack=effective_stack,
        bet_sizes=bet_sizes or [50.0],
        raise_sizes=raise_sizes or [60.0],
        accuracy=accuracy,
        max_iterations=max_iterations,
        time_limit_s=time_limit_s,
    )
    result = solve(request)
    strategy = result.oop_strategy if grid_for == "oop" else result.ip_strategy
    who = "OOP (first to act)" if grid_for == "oop" else "IP (facing check)"
    title = f"{who} - {result.board}"
    png = render_grid(strategy, grid_metric, title)
    return [_summary(result), Image(data=png, format="png")]


@mcp.tool
def explain_hand(
    hand: str,
    oop_range: str,
    ip_range: str,
    board: str,
    pot: float,
    effective_stack: float,
    bet_sizes: list[float] | None = None,
    raise_sizes: list[float] | None = None,
    accuracy: float = 0.5,
    max_iterations: int = 150,
    time_limit_s: float = 60.0,
) -> str:
    """Solve a spot and explain one hand's strategy (e.g. ``hand="AKs"`` or ``"AhKh"``).

    Note: this re-runs the solve, so it costs a full solve. Parameters mirror ``solve_spot``.
    Returns the hand's OOP first-action frequencies and IP-facing-check frequencies.
    """
    request = _build_request(
        oop_range=oop_range,
        ip_range=ip_range,
        board=board,
        pot=pot,
        effective_stack=effective_stack,
        bet_sizes=bet_sizes or [50.0],
        raise_sizes=raise_sizes or [60.0],
        accuracy=accuracy,
        max_iterations=max_iterations,
        time_limit_s=time_limit_s,
    )
    result = solve(request)
    return (
        f"Hand {hand} on {result.board}:\n\n"
        f"As OOP (first to act):\n{_fmt_freqs(_class_breakdown(result.oop_strategy, hand))}\n\n"
        f"As IP (facing a check):\n{_fmt_freqs(_class_breakdown(result.ip_strategy, hand))}"
    )


@mcp.tool
def list_range_presets() -> dict[str, str]:
    """Return built-in preflop range presets (RFI/3bet/blind-defense) keyed by name."""
    return list_presets()


def build_app() -> ASGIApp:
    """Build the streamable-http ASGI app with bearer-token auth."""
    token = os.environ.get(TOKEN_ENV)
    if not token:
        raise RuntimeError(f"{TOKEN_ENV} must be set to a non-empty bearer token")
    middleware = [Middleware(BearerTokenMiddleware, token=token)]
    # stateless_http: each request is self-contained, so no in-memory session has to
    # survive across Cloud Run instances (which have no session affinity by default).
    return mcp.http_app(middleware=middleware, stateless_http=True)


def main() -> None:
    import uvicorn

    app = build_app()
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()

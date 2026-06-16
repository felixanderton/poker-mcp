"""FastMCP server exposing the TexasSolver GTO engine over streamable-http.

Tools:
    * ``solve_spot``   -- solve a postflop spot, return frequencies/EV + a 13x13 grid image
    * ``explain_hand`` -- solve a spot and explain one specific hand's strategy
    * ``list_presets`` -- list the built-in preflop range presets

Auth is Google OAuth via FastMCP's ``GoogleProvider``: the server is an OAuth-protected
resource that logs users in with Google, so OAuth-only MCP clients (e.g. the claude.ai
custom connector) can connect with no custom headers. Credentials come from the
``GOOGLE_CLIENT_ID`` / ``GOOGLE_CLIENT_SECRET`` env vars (secret from Secret Manager on
Cloud Run); ``OAUTH_BASE_URL`` is the public service URL. If ``GOOGLE_CLIENT_ID`` is unset
the server runs unauthenticated, which is convenient for local development.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections import OrderedDict
from typing import Literal

from fastmcp import Context, FastMCP
from fastmcp.apps.config import AppConfig, ResourceCSP
from fastmcp.server.auth.providers.google import GoogleProvider
from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image
from mcp.types import TextContent
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from engine.adapter import solve
from engine.models import ComboStrategy, SolveRequest, SolveResult
from engine.ranges import combo_to_class, list_presets
from rendering.grid import GridMetric, class_grid, render_grid
from ui.grid_app import GRID_APP_HTML

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("poker_mcp")

_HEALTH_PATH = "/healthz"
# Redirect URIs the claude.ai / claude.com custom connectors use to receive the auth code.
_CLAUDE_REDIRECT_URIS = [
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
]


def _build_auth() -> GoogleProvider | None:
    """Build the Google OAuth provider from env, or None to run unauthenticated."""
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    if not client_id:
        logger.warning("GOOGLE_CLIENT_ID not set; running without authentication")
        return None
    return GoogleProvider(
        client_id=client_id,
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        base_url=os.environ.get("OAUTH_BASE_URL", "http://localhost:8080"),
        required_scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"],
        allowed_client_redirect_uris=_CLAUDE_REDIRECT_URIS,
        require_authorization_consent=False,
    )


mcp: FastMCP = FastMCP(
    "poker-mcp",
    instructions=(
        "Solve postflop Texas Hold'em spots with a GTO solver. Provide ranges in solver "
        "syntax (e.g. 'AA,KK,AKs:0.5'), a 3-5 card board, pot, and effective stack. Tools "
        "return action frequencies, exploitability, and a 13x13 starting-hand strategy grid."
    ),
    auth=_build_auth(),
)


@mcp.custom_route(_HEALTH_PATH, methods=["GET"])
async def healthz(_: Request) -> Response:
    return JSONResponse({"status": "ok"})


# Some MCP clients (e.g. the claude.ai web connector) don't render image content returned
# from a tool, so we also host each rendered grid at an unguessable public URL and hand that
# URL back in the tool's text. Kept in a small in-memory LRU on the (single) instance.
_GRID_CACHE: OrderedDict[str, bytes] = OrderedDict()
_GRID_CACHE_MAX = 50
_PUBLIC_BASE_URL = os.environ.get("OAUTH_BASE_URL", "").rstrip("/")


def _store_grid(png: bytes) -> str:
    grid_id = f"{uuid.uuid4().hex}.png"
    _GRID_CACHE[grid_id] = png
    while len(_GRID_CACHE) > _GRID_CACHE_MAX:
        _GRID_CACHE.popitem(last=False)
    return f"{_PUBLIC_BASE_URL}/grid/{grid_id}"


@mcp.custom_route("/grid/{grid_id}", methods=["GET"])
async def get_grid(request: Request) -> Response:
    png = _GRID_CACHE.get(request.path_params["grid_id"])
    if png is None:
        return Response(status_code=404)
    return Response(content=png, media_type="image/png")


# Interactive 13x13 grid rendered inline by the claude.ai connector (MCP Apps extension).
# The HTML View loads the ext-apps SDK from esm.sh, so the iframe CSP must allow it.
_GRID_UI_URI = "ui://poker-mcp/grid"


@mcp.resource(
    _GRID_UI_URI,
    mime_type="text/html",
    app=AppConfig(
        csp=ResourceCSP(
            resource_domains=["https://esm.sh"],
            connect_domains=["https://esm.sh"],
        )
    ),
)
def grid_ui() -> str:
    return GRID_APP_HTML


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


@mcp.tool(app=AppConfig(resource_uri=_GRID_UI_URI))
async def solve_spot(
    ctx: Context,
    oop_range: str,
    ip_range: str,
    board: str,
    pot: float,
    effective_stack: float,
    bet_sizes: list[float] | None = None,
    raise_sizes: list[float] | None = None,
    accuracy: float = 1.0,
    max_iterations: int = 100,
    time_limit_s: float = 180.0,
    grid_for: Literal["oop", "ip"] = "oop",
    grid_metric: GridMetric = "bet",
) -> ToolResult:
    """Solve a postflop spot; returns an interactive 13x13 grid plus GTO frequencies.

    Range syntax (comma-separated): pairs like ``QQ``, suited/offsuit like ``AKs``/``AKo``,
    ``+`` for "and better" (``QQ+``, ``ATs+``, ``A2s+``), and weights like ``AKo:0.5``. The
    ``+`` shorthand IS supported -- do not pre-expand it. Example:
    ``"QQ+,AKs,AKo,AJs+,KQs,A5s"``.

    Board is 3-5 cards separated by spaces or commas, e.g. ``"Jh 9c 5d"`` (flop) or
    ``"Jh 9c 5d 2s"`` (turn); ranks ``23456789TJQKA``, suits ``cdhs``.

    ``bet_sizes``/``raise_sizes`` are percentages (of pot / of the facing bet); defaults are
    ``[50]`` and ``[60]`` plus all-in. ``grid_for`` chooses whose strategy to plot
    (``oop`` = first to act, ``ip`` = facing a check); ``grid_metric`` is ``bet``, ``check``,
    ``fold`` or ``blended`` (RGB mix).

    Presentation: lead with the grid visualization first, then give a short explanation of the
    notable mixed/pure regions -- do not restate every cell.
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

    async def on_progress(iteration: int | None, exploitability: float | None) -> None:
        message = f"iteration {iteration or 0}/{max_iterations}"
        if exploitability is not None:
            message += f", exploitability {exploitability:.2f}% of pot"
        await ctx.report_progress(
            progress=float(iteration or 0), total=float(max_iterations), message=message
        )

    result = await solve(request, on_progress)
    strategy = result.oop_strategy if grid_for == "oop" else result.ip_strategy
    who = "OOP (first to act)" if grid_for == "oop" else "IP (facing check)"
    title = f"{who} - {result.board}"
    png = render_grid(strategy, grid_metric, title)
    url = _store_grid(png)
    summary = (
        f"{_summary(result)}\n\n"
        f"13x13 {grid_for} {grid_metric} grid: {url}\n"
        f"![grid]({url})\n"
        "(An interactive grid also renders inline; this URL is a fallback.)"
    )
    payload: dict[str, object] = {
        "board": result.board,
        "pot": result.pot,
        "exploitability_pct": result.exploitability_pct,
        "grid_for": grid_for,
        "grid_metric": grid_metric,
        "players": {
            "oop": class_grid(result.oop_strategy),
            "ip": class_grid(result.ip_strategy),
        },
    }
    # Lead with the visual (image/app artifact), then the text explanation.
    return ToolResult(
        content=[
            Image(data=png, format="png").to_image_content(),
            TextContent(type="text", text=summary),
        ],
        structured_content=payload,
    )


@mcp.tool
async def explain_hand(
    hand: str,
    oop_range: str,
    ip_range: str,
    board: str,
    pot: float,
    effective_stack: float,
    bet_sizes: list[float] | None = None,
    raise_sizes: list[float] | None = None,
    accuracy: float = 1.0,
    max_iterations: int = 100,
    time_limit_s: float = 180.0,
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
    result = await solve(request)
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
    """Build the streamable-http ASGI app (OAuth, if configured, is on the FastMCP server)."""
    # stateless_http: each MCP request carries its own OAuth bearer token and is verified
    # statelessly (JWT), so no per-session state has to survive across Cloud Run instances.
    return mcp.http_app(stateless_http=True)


def main() -> None:
    import uvicorn

    app = build_app()
    port = int(os.environ.get("PORT", "8080"))
    # proxy_headers/forwarded_allow_ips let the app trust Cloud Run's X-Forwarded-Proto so it
    # builds https (not http) URLs for OAuth redirects and metadata.
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()

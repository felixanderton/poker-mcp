"""TexasSolver ``console_solver`` adapter.

Serialises a validated :class:`SolveRequest` into the solver's text input format,
runs the binary as a bounded subprocess, and parses ``output_result.json`` into a
:class:`SolveResult`. The binary location is configured via environment variables
so the same code runs locally and in the Cloud Run image.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from engine.models import ComboStrategy, SolveRequest, SolveResult

logger = logging.getLogger(__name__)

# Called as the solver streams progress: (iteration, exploitability_pct), either may be None.
type ProgressCallback = Callable[[int | None, float | None], Awaitable[None]]

# Where to find the compiled binary and its ``resources/`` directory. The solver
# loads lookup tables by a path relative to its working directory, so it must be
# run with cwd set to the directory that contains ``resources/``.
SOLVER_PATH_ENV = "CONSOLE_SOLVER_PATH"
SOLVER_ROOT_ENV = "CONSOLE_SOLVER_ROOT"

_STREETS = ("flop", "turn", "river")
# TexasSolver prints e.g. "Total exploitability 1.25 precent" (sic) as a percent of pot.
_EXPLOIT_RE = re.compile(r"Total exploitability\s+([0-9]*\.?[0-9]+)", re.IGNORECASE)
_ITER_RE = re.compile(r"iter[^0-9]*([0-9]+)", re.IGNORECASE)
_PASSIVE_PREFIXES = ("CHECK", "CALL")


def _sizes(values: list[float]) -> str:
    return ",".join(f"{v:g}" for v in values)


def build_solver_input(req: SolveRequest, dump_path: Path) -> str:
    """Render the solver input file for ``req``, dumping results to ``dump_path``."""
    threads = req.threads or (os.cpu_count() or 1)
    lines: list[str] = [
        f"set_pot {req.pot:g}",
        f"set_effective_stack {req.effective_stack:g}",
        f"set_board {req.board}",
        f"set_range_ip {req.ip_range}",
        f"set_range_oop {req.oop_range}",
    ]
    for street in _STREETS:
        for player in ("oop", "ip"):
            lines.append(f"set_bet_sizes {player},{street},bet,{_sizes(req.bet_sizes)}")
            if player == "oop" and street != "flop":
                lines.append(f"set_bet_sizes {player},{street},donk,{_sizes(req.bet_sizes)}")
            lines.append(f"set_bet_sizes {player},{street},raise,{_sizes(req.raise_sizes)}")
            if req.include_allin:
                lines.append(f"set_bet_sizes {player},{street},allin")
    lines += [
        f"set_allin_threshold {req.allin_threshold:g}",
        "build_tree",
        f"set_thread_num {threads}",
        f"set_accuracy {req.accuracy:g}",
        f"set_max_iteration {req.max_iterations}",
        "set_print_interval 5",
        f"set_use_isomorphism {1 if req.use_isomorphism else 0}",
        "start_solve",
        "set_dump_rounds 2",
        f"dump_result {dump_path}",
    ]
    return "\n".join(lines) + "\n"


def _node_strategy(node: dict[str, Any]) -> tuple[list[str], dict[str, list[float]]] | None:
    """Extract ``(actions, {combo: [probs]})`` from an action node.

    Handles both the nested form (``node["strategy"]`` holds ``actions`` and a
    ``strategy`` map) and the flat form (``actions`` and ``strategy`` sit directly
    on the node). Returns ``None`` for chance/terminal nodes.
    """
    strat = node.get("strategy")
    if isinstance(strat, dict) and "actions" in strat and isinstance(strat.get("strategy"), dict):
        return list(strat["actions"]), strat["strategy"]
    if isinstance(strat, dict) and isinstance(node.get("actions"), list):
        return list(node["actions"]), strat
    return None


def _children(node: dict[str, Any]) -> dict[str, dict[str, Any]]:
    children = node.get("childrens")
    return children if isinstance(children, dict) else {}


def _to_combo_strategy(actions: list[str], strat: dict[str, list[float]]) -> ComboStrategy:
    result: ComboStrategy = {}
    for combo, probs in strat.items():
        result[combo] = {actions[i]: float(p) for i, p in enumerate(probs) if i < len(actions)}
    return result


def _passive_child(node: dict[str, Any]) -> dict[str, Any] | None:
    for action, child in _children(node).items():
        if action.upper().startswith(_PASSIVE_PREFIXES):
            return child
    return None


def _extract(tree: dict[str, Any]) -> tuple[ComboStrategy, ComboStrategy, list[str], list[str]]:
    """Pull the OOP root strategy and IP's strategy facing a check from the tree."""
    oop = _node_strategy(tree)
    if oop is None:
        raise ValueError("Solver output root is not an action node")
    oop_actions, oop_strat = oop

    ip_strategy: ComboStrategy = {}
    ip_actions: list[str] = []
    ip_node = _passive_child(tree)
    if ip_node is not None:
        ip = _node_strategy(ip_node)
        if ip is not None:
            ip_actions, ip_raw = ip
            ip_strategy = _to_combo_strategy(ip_actions, ip_raw)

    return _to_combo_strategy(oop_actions, oop_strat), ip_strategy, oop_actions, ip_actions


def _parse_progress(stdout: str) -> tuple[float | None, int | None]:
    exploits = _EXPLOIT_RE.findall(stdout)
    iters = _ITER_RE.findall(stdout)
    exploitability = float(exploits[-1]) if exploits else None
    iterations = int(iters[-1]) if iters else None
    return exploitability, iterations


def _solver_command(input_path: Path) -> tuple[list[str], Path]:
    binary = os.environ.get(SOLVER_PATH_ENV, "console_solver")
    root = os.environ.get(SOLVER_ROOT_ENV)
    cwd = Path(root) if root else Path(binary).resolve().parent
    return [binary, "-i", str(input_path)], cwd


async def solve(req: SolveRequest, on_progress: ProgressCallback | None = None) -> SolveResult:
    """Run the solver for ``req``, streaming progress, and return the parsed result.

    ``on_progress`` is awaited each time the solver reports a new iteration or
    exploitability value, so callers can surface live progress to the client.
    """
    with TemporaryDirectory(prefix="poker-mcp-") as tmp:
        tmp_path = Path(tmp)
        input_path = tmp_path / "input.txt"
        dump_path = tmp_path / "output_result.json"
        input_path.write_text(build_solver_input(req, dump_path), encoding="utf-8")

        command, cwd = _solver_command(input_path)
        logger.info("Running solver: %s (cwd=%s)", " ".join(command), cwd)
        start = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        last_iter: int | None = None
        last_expl: float | None = None
        recent: deque[str] = deque(maxlen=40)

        async def _read() -> None:
            nonlocal last_iter, last_expl
            assert proc.stdout is not None
            async for raw in proc.stdout:
                line = raw.decode("utf-8", "replace")
                recent.append(line)
                match_iter = _ITER_RE.search(line)
                match_expl = _EXPLOIT_RE.search(line)
                if match_iter:
                    last_iter = int(match_iter.group(1))
                if match_expl:
                    last_expl = float(match_expl.group(1))
                if on_progress is not None and (match_iter or match_expl):
                    await on_progress(last_iter, last_expl)

        try:
            await asyncio.wait_for(_read(), timeout=req.time_limit_s)
            await asyncio.wait_for(proc.wait(), timeout=10)
        except TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise RuntimeError(
                f"Solver exceeded time_limit_s={req.time_limit_s}s. Lower max_iterations, "
                "raise accuracy, or shrink the bet-size tree."
            ) from exc
        elapsed = time.monotonic() - start

        if proc.returncode != 0:
            raise RuntimeError(f"Solver exited {proc.returncode}: {''.join(recent).strip()[:500]}")
        if not dump_path.exists():
            raise RuntimeError("Solver finished but produced no output_result.json")

        tree = json.loads(dump_path.read_text(encoding="utf-8"))
        oop_strategy, ip_strategy, oop_actions, ip_actions = _extract(tree)

    return SolveResult(
        board=req.board,
        pot=req.pot,
        effective_stack=req.effective_stack,
        iterations=last_iter,
        exploitability_pct=last_expl,
        solve_time_s=round(elapsed, 2),
        converged=last_expl is not None and last_expl <= req.accuracy,
        oop_root_actions=oop_actions,
        ip_actions_facing_check=ip_actions,
        oop_strategy=oop_strategy,
        ip_strategy=ip_strategy,
    )

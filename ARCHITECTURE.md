# Architecture

## Overview

poker-mcp is a Model Context Protocol server that gives LLMs a structured interface to TexasSolver, an open-source postflop GTO poker solver. The server receives a validated tool call (board, pot, stacks, ranges, bet-sizing tree), serialises it into the format expected by the `console_solver` C++ binary, runs the binary as a bounded subprocess, parses the resulting `output_result.json`, and returns structured frequencies/EV/exploitability back to the LLM. A second capability renders a 13×13 starting-hand strategy grid as a matplotlib PNG and returns it inline as MCP `ImageContent`. The server runs on GCP Cloud Run with scale-to-zero and concurrency=1; auth is a static bearer token stored in Google Secret Manager.

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.12 |
| MCP framework | FastMCP (streamable-http transport) |
| Tool input validation | pydantic v2 |
| GTO engine | TexasSolver `console_solver` (C++ binary, subprocess) |
| Grid rendering | matplotlib + numpy |
| Containerisation | Docker (multi-stage build) |
| Cloud runtime | GCP Cloud Run (scale-to-zero, concurrency=1) |
| Secrets | Google Secret Manager |

## Project Structure

```
poker-mcp/
  .claude/              # Claude Code config (agents, rules, settings)
  src/
    server.py           # FastMCP app, tool registration, bearer-token middleware
    engine/
      adapter.py        # Build console_solver input, run subprocess, parse output_result.json
      ranges.py         # Range string parsing, RFI/3bet/blind-defense presets
    rendering/
      grid.py           # 13x13 hand-grid PNG renderer (matplotlib)
  tests/
    test_adapter.py     # Config builder unit tests
    test_ranges.py      # Range parsing unit tests
    test_grid.py        # Grid renderer against captured fixture JSON
  Dockerfile            # Multi-stage build (builder stage compiles console_solver, runtime stage is slim)
  CLAUDE.md             # Claude Code instructions
  ARCHITECTURE.md       # This file
```

## Key Components

### Engine Adapter (`src/engine/adapter.py`)
Accepts a validated pydantic model, serialises it to the text format consumed by `console_solver`, spawns the binary as a subprocess with `time_limit`, `max_iterations`, and `accuracy` bounds, waits for completion, and parses `output_result.json` into a structured response dict.

### Range Parser (`src/engine/ranges.py`)
Converts human-readable range strings (e.g. `"AA,KK,AKs"`) to the hand-matrix format the solver expects. Ships named presets for common preflop situations (RFI by position, 3-bet calling ranges, big-blind defense).

### Grid Renderer (`src/rendering/grid.py`)
Takes a strategy frequency dict keyed by hand combo and renders a 13×13 grid using matplotlib. Supports bet/check/fold as distinct colours, blended cells for mixed strategies, and a legend. Returns a PNG `bytes` object wrapped in `FastMCP Image`.

### FastMCP Server (`src/server.py`)
Registers three tools: `solve_spot`, `explain_hand`, `list_presets`. Authenticates users with Google via FastMCP's `GoogleProvider` (OAuth), so OAuth-only clients like the claude.ai connector can sign in with no custom headers. `GOOGLE_CLIENT_ID` / `OAUTH_BASE_URL` are env vars and `GOOGLE_CLIENT_SECRET` is injected from Secret Manager; when `GOOGLE_CLIENT_ID` is unset the server runs unauthenticated for local dev.

## Data Flow

```
LLM tool call
    │
    ▼
FastMCP (streamable-http)
    │  bearer-token check
    ▼
pydantic validation
    │
    ▼
engine adapter
    │  writes config to temp dir
    ▼
console_solver subprocess (bounded)
    │  reads output_result.json
    ▼
response serialisation
    │
    ▼
LLM receives frequencies / EV / exploitability
         (or PNG ImageContent for grid tools)
```

## Decision Log

| Date | Decision | Rationale |
|---|---|---|
| 2026-06-16 | TexasSolver `console_solver` as GTO engine | Open-source, battle-tested, exposes a clean CLI and JSON output. `postflop-solver` (Rust crate) is a viable alternative but requires FFI or a Rust extension — higher integration cost for no clear accuracy gain at this stage. |
| 2026-06-16 | Bounded synchronous solve (time_limit + max_iterations + accuracy caps) | Cloud Run has a hard request timeout; unbounded solves would cause 504s and unpredictable costs. Caps keep p99 latency within the timeout budget. |
| 2026-06-16 | Cloud Run concurrency=1 | `console_solver` is single-threaded and writes to temp files; multiplexing within one instance risks file collisions and solver corruption. Scale-out is handled by Cloud Run spawning additional instances. |
| 2026-06-16 | Public repository (AGPL compliance) | TexasSolver is AGPL-licensed. Running it inside a network service without making the enclosing source available would violate the AGPL. A public repo satisfies the source-available requirement. |
| 2026-06-16 | Google OAuth (FastMCP GoogleProvider) instead of a static bearer token | The claude.ai custom connector only supports OAuth, not custom headers. GoogleProvider makes the server an OAuth resource that logs users in with Google; `max-instances 1` keeps the in-memory OAuth handshake state on one instance, and the JWT signing key is derived from the client secret so tokens survive cold starts. |

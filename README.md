# poker-mcp

An [MCP](https://modelcontextprotocol.io) server that wraps the open-source
[TexasSolver](https://github.com/bupticybee/TexasSolver) GTO engine so an LLM can solve
postflop Texas Hold'em spots and get back **bet/check/fold frequencies, exploitability**,
and a **13×13 starting-hand strategy grid rendered inline in the chat**.

Runs on **Google Cloud Run** with scale-to-zero. The solver runs as a bounded subprocess;
auth is a static bearer token enforced in-app.

## Tools

| Tool | Purpose |
|---|---|
| `solve_spot` | Solve a spot; returns a text summary + an inline 13×13 grid image |
| `explain_hand` | Solve a spot and explain one hand's strategy (e.g. `"AKs"`) |
| `list_range_presets` | List built-in preflop range presets (RFI / 3bet / blind-defense) |

### `solve_spot` parameters

- `oop_range`, `ip_range` — solver syntax, e.g. `"AA,KK,QQ,AKs,AKo:0.5,ATs+"`
- `board` — 3–5 cards, e.g. `"Qs Jh 2h"` (flop) or `"Qs Jh 2h 8d"` (turn)
- `pot`, `effective_stack` — chip amounts
- `bet_sizes` (% of pot, default `[50]`), `raise_sizes` (% of facing bet, default `[60]`); all-in is always added
- `accuracy` — target exploitability as % of pot (default `0.5`)
- `max_iterations` (default `150`), `time_limit_s` (hard cap, default `60`)
- `grid_for` — `"oop"` (first to act) or `"ip"` (facing a check)
- `grid_metric` — `"bet"`, `"check"`, `"fold"`, or `"blended"` (RGB: red=bet/raise, green=check/call, blue=fold)

## Local development

```bash
uv sync
uv run pytest              # unit tests (no solver binary required)
uv run ruff check . && uv run black --check . && uv run mypy .
```

The solver binary is only needed to actually run a solve. Set its location via env vars:

```bash
export CONSOLE_SOLVER_PATH=/path/to/console_solver
export CONSOLE_SOLVER_ROOT=/path/to/dir-containing-resources
export SOLVER_TOKEN=$(openssl rand -hex 32)
PYTHONPATH=src uv run python src/server.py   # serves streamable-http on :8080
```

Build `console_solver` from the TexasSolver `console` branch (`cmake .. && make console_solver`);
the binary lands in `build/` and its `resources/` directory sits at the repo root.

## Docker

```bash
docker build -t poker-mcp .
docker run -p 8080:8080 -e SOLVER_TOKEN=secret poker-mcp
```

The multi-stage build compiles `console_solver` (stage 1) and copies it plus `resources/`
into a slim Python runtime (stage 2).

## Deploy to Cloud Run

```bash
# 1. Store the bearer token
echo -n "$(openssl rand -hex 32)" | gcloud secrets create poker-mcp-token --data-file=-

# 2. Build + deploy (Cloud Build compiles the Dockerfile)
gcloud run deploy poker-mcp \
  --source . \
  --region europe-west1 \
  --memory 4Gi --cpu 4 \
  --concurrency 1 \
  --min-instances 0 --max-instances 3 \
  --timeout 300 \
  --allow-unauthenticated \
  --set-secrets SOLVER_TOKEN=poker-mcp-token:latest
```

`--allow-unauthenticated` exposes a public URL; the in-app bearer token is what actually
gates access. `concurrency 1` because each solve is CPU-bound. Bump `--memory` / `--cpu`
if large trees run out of memory.

## Connect an MCP client

Point your MCP client at `https://<service-url>/mcp` (no trailing slash) with the bearer token:

```json
{
  "mcpServers": {
    "poker": {
      "url": "https://poker-mcp-xxxx.run.app/mcp",
      "headers": { "Authorization": "Bearer <your-token>" }
    }
  }
}
```

> Use `/mcp` **without** a trailing slash. `/mcp/` issues a redirect that, behind Cloud Run's
> TLS termination, downgrades to `http://` — and HTTP clients strip the `Authorization` header
> across that redirect, causing a 401.

## Architecture & decisions

See [ARCHITECTURE.md](ARCHITECTURE.md). Key points: bounded synchronous solves
(accuracy / max-iterations / time caps), defensive parsing of the solver's strategy-tree
JSON, and scale-to-zero with concurrency 1.

## Licensing

TexasSolver is **AGPL-3.0**. This server invokes it over a network, so this repository is
public to satisfy the AGPL's network-use source-availability requirement.

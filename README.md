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
# Leave GOOGLE_CLIENT_ID unset locally to run without auth (convenient for dev).
PYTHONPATH=src uv run python src/server.py   # serves streamable-http on :8080
```

Build `console_solver` from the TexasSolver `console` branch (`cmake .. && make console_solver`);
the binary lands in `build/` and its `resources/` directory sits at the repo root.

## Docker

```bash
docker build -t poker-mcp .
docker run -p 8080:8080 poker-mcp
```

The multi-stage build compiles `console_solver` (stage 1) and copies it plus `resources/`
into a slim Python runtime (stage 2).

## Authentication (Google OAuth)

The server authenticates users with Google via FastMCP's `GoogleProvider`, so OAuth-only MCP
clients (such as the **claude.ai custom connector**) can connect with no custom headers — the
client is redirected to "Log in with Google".

One-time Google setup (in the [Google Cloud Console](https://console.cloud.google.com)):

1. **APIs & Services → OAuth consent screen** — User type **External**; add your account as a
   **Test user** (leave it in *Testing* so only listed users can sign in); scopes `openid`,
   `email`, `profile`.
2. **APIs & Services → Credentials → Create OAuth client ID → Web application** — add the
   **Authorized redirect URI**: `https://<service-url>/auth/callback`.
3. Copy the **Client ID** and **Client secret**.

## Deploy to Cloud Run

```bash
# 1. Store the Google OAuth client secret
printf '%s' "<google-client-secret>" | \
  gcloud secrets create google-oauth-client-secret --data-file=-

# 2. Build the image (high-CPU machine: the C++ solver compile is slow on 1 vCPU)
gcloud builds submit . \
  --tag europe-west2-docker.pkg.dev/<project>/poker-mcp/poker-mcp:v1 \
  --machine-type e2-highcpu-8 --timeout 2400s

# 3. Deploy
gcloud run deploy poker-mcp \
  --image europe-west2-docker.pkg.dev/<project>/poker-mcp/poker-mcp:v1 \
  --region europe-west2 \
  --memory 4Gi --cpu 4 \
  --concurrency 10 \
  --min-instances 0 --max-instances 1 \
  --timeout 600 \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_CLIENT_ID=<client-id>,OAUTH_BASE_URL=https://<service-url> \
  --set-secrets GOOGLE_CLIENT_SECRET=google-oauth-client-secret:latest
```

`--allow-unauthenticated` only opens the network — OAuth is what actually gates access.
`max-instances 1` keeps the brief OAuth handshake state on a single instance (FastMCP's
client/transaction store is in-memory); scale-to-zero is preserved via `min-instances 0`, and
access tokens stay valid across cold starts because the JWT signing key is derived
deterministically from the client secret.

## Connect from claude.ai

Settings → **Connectors** → **Add custom connector**, then enter the URL
`https://<service-url>/mcp` (no trailing slash). claude.ai discovers the OAuth metadata and
redirects you to **Log in with Google**; approve, and the poker tools appear in chat.

> Use `/mcp` **without** a trailing slash. `/mcp/` issues a redirect that, behind Cloud Run's
> TLS termination, downgrades to `http://`, which breaks header/redirect handling.

## Architecture & decisions

See [ARCHITECTURE.md](ARCHITECTURE.md). Key points: bounded synchronous solves
(accuracy / max-iterations / time caps), defensive parsing of the solver's strategy-tree
JSON, Google-OAuth auth for connector clients, and scale-to-zero on Cloud Run.

## Licensing

TexasSolver is **AGPL-3.0**. This server invokes it over a network, so this repository is
public to satisfy the AGPL's network-use source-availability requirement.

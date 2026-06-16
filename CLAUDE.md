# CLAUDE.md

## Project

**Name**: poker-mcp
**Description**: An MCP (Model Context Protocol) server that wraps TexasSolver's `console_solver` C++ binary as a subprocess so an LLM like Claude can solve postflop poker spots and retrieve GTO calculations — bet/check/fold frequencies, EV, and exploitability. Also renders a 13×13 starting-hand strategy grid as a PNG returned inline via MCP ImageContent. Deployed to GCP Cloud Run with scale-to-zero. Auth is a static bearer token enforced at the application layer.
**Stack**: Python 3.12, FastMCP (streamable-http transport), matplotlib + numpy (grid rendering), pydantic (tool input validation), TexasSolver console build (C++ engine via subprocess), Docker (multi-stage), GCP Cloud Run, Google Secret Manager
**Repo**: https://github.com/felixanderton/poker-mcp
**Project board**: https://github.com/users/felixanderton/projects/6

## Agents

| Agent | Purpose |
|---|---|
| `reviewer` | Read-only code review — run before committing |
| `feature-writer` | Implements features from a spec |
| `test-writer` | Writes tests matching project conventions |
| `issue-writer` | Files GitHub issues for bugs and features |

## Workflow

1. Pick a deliverable from the project board
2. Create a worktree: `claude --worktree <feature-name>`
3. Invoke `feature-writer` with the issue description
4. Invoke `test-writer` to add coverage
5. Invoke `reviewer` before committing
6. Open a PR — one worktree per branch per PR

## Conventions

- Make the minimum change needed; do not refactor beyond the task scope
- Read existing code before modifying anything
- Never hardcode secrets — use environment variables (token sourced from Google Secret Manager in Cloud Run)
- Run `reviewer` before committing non-trivial changes
- The solver subprocess must always be bounded: respect `time_limit`, `max_iterations`, and `accuracy` caps — never let it run unbounded
- All solver input is validated with pydantic before the subprocess is spawned
- PNG grid responses use FastMCP `Image` return type so they arrive as MCP `ImageContent`
- Concurrency on Cloud Run is set to 1 — the solver binary is single-threaded and not safe to multiplex per instance

## Key Architecture Decisions

| Decision | Rationale |
|---|---|
| TexasSolver console binary as the GTO engine | Open-source, battle-tested postflop solver with JSON output; `console_solver` exposes a clean CLI interface suitable for subprocess wrapping. `postflop-solver` (Rust) is a noted alternative but requires deeper FFI integration. |
| Bounded synchronous solve | Cloud Run requests have a hard timeout; accuracy/max_iterations/time_limit caps prevent runaway solves and keep p99 latency predictable. |
| scale-to-zero + concurrency=1 | Minimises cost for low-traffic workloads; concurrency=1 avoids solver race conditions within a single instance. |
| AGPL licence consideration | TexasSolver is AGPL-licensed; shipping it inside a service that is not source-available creates licence risk. Keeping the repo public satisfies the source-available requirement. |
| Static bearer token (app-layer) | Simpler than GCP IAM for LLM-client use cases; token is injected at runtime via Google Secret Manager and never committed. |

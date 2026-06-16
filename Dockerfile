# syntax=docker/dockerfile:1

# ---- Stage 1: build the TexasSolver console_solver binary ----
FROM debian:bookworm-slim AS solver-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git python3-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pin the solver to a branch/commit for reproducible builds.
ARG SOLVER_REPO=https://github.com/bupticybee/TexasSolver.git
ARG SOLVER_REF=console
WORKDIR /build
RUN git clone --branch "${SOLVER_REF}" --depth 1 --recurse-submodules "${SOLVER_REPO}" TexasSolver

WORKDIR /build/TexasSolver/build
RUN cmake .. -DCMAKE_BUILD_TYPE=Release \
    && make console_solver -j"$(nproc)"
# Binary -> /build/TexasSolver/build/console_solver
# Resources (hand-rank lookups) -> /build/TexasSolver/resources

# ---- Stage 2: python runtime ----
FROM python:3.12-slim AS runtime

# libgomp1 is the OpenMP runtime the solver links against.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Install Python deps first for layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

COPY src ./src
COPY --from=solver-builder /build/TexasSolver/build/console_solver /app/console_solver
COPY --from=solver-builder /build/TexasSolver/resources /app/resources

ENV CONSOLE_SOLVER_PATH=/app/console_solver \
    CONSOLE_SOLVER_ROOT=/app \
    PYTHONPATH=/app/src \
    PORT=8080

EXPOSE 8080
CMD ["/app/.venv/bin/python", "src/server.py"]

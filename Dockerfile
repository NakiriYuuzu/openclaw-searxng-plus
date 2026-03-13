FROM python:3.12-slim-bookworm AS base

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

# Copy dependency spec first for layer caching
COPY pyproject.toml ./

# Install production dependencies
RUN uv sync --no-dev --no-install-project

# Copy application code
COPY gateway/ gateway/

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]

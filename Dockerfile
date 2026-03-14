FROM python:3.12-slim-bookworm AS base

WORKDIR /app

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

# Copy dependency spec first for layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies
RUN uv sync --no-dev --no-install-project

# Copy application code and config
COPY gateway/ gateway/
COPY config/ config/

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uv", "run", "uvicorn", "gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]

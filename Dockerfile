# Synthetic API (FastAPI + web UI). Build: docker build -t synthetic .
# Run:   docker run -p 8000:8000 -v synthetic-var:/app/var synthetic
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy SYNTHETIC_DATA_DIR=/app/var
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra postgres
COPY src ./src
COPY examples ./examples
RUN uv sync --frozen --no-dev --extra postgres

RUN useradd --create-home --uid 10001 synthetic && mkdir -p /app/var && chown synthetic /app/var
USER synthetic
EXPOSE 8000
CMD ["/app/.venv/bin/synthetic", "serve", "--host", "0.0.0.0", "--port", "8000"]

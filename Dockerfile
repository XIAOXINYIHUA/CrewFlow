# Stage 1: Build
FROM python:3.11-slim AS builder
WORKDIR /app

RUN pip install --no-cache-dir uv
COPY pyproject.toml .
RUN uv sync --no-dev

# Stage 2: Run
FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY . .

RUN mkdir -p output data/artifacts data/migrations
RUN python -c "from src.database import init_db; init_db()" || true

EXPOSE 8000

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]

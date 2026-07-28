# Stage 1: Build
FROM python:3.11-slim AS builder
WORKDIR /app

RUN pip install --no-cache-dir uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --extra server --extra web --no-editable

# Stage 2: Run
FROM python:3.11-slim
WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

COPY . .

RUN mkdir -p output data/artifacts data/migrations

EXPOSE 8000 7860

CMD ["uvicorn", "src.api:app", "--host", "0.0.0.0", "--port", "8000"]

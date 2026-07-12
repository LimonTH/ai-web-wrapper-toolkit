FROM python:3.14-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen

COPY src ./src

RUN uv run python -m playwright install chromium

EXPOSE 8000

CMD ["uv", "run", "python", "-m", "src.main"]
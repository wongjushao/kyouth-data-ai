FROM python:3-bookworm

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.8.22 /uv /uvx /bin/

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY src ./src

EXPOSE 8000

ENTRYPOINT ["uv", "run", "uvicorn"]
CMD ["src.app:app", "--host", "0.0.0.0", "--port", "8000"]

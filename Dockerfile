# --- build stage ---
FROM python:3.12-slim AS builder
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN uv sync --no-dev --no-editable

# --- runtime stage ---
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src ./src
COPY config.example.toml ./config.toml
# config.toml is meant to be overridden via volume mount at runtime
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/admin/health', timeout=3); sys.exit(0)" || exit 1
CMD ["python", "-m", "depu_img_mcp"]

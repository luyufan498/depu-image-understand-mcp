# --- build stage ---
FROM python:3.12-slim AS builder
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --no-dev --no-editable --frozen

# --- runtime stage ---
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    # Config lives in its own dir so the host can mount a directory (not a single
    # file). Mounting a single file breaks when the host file doesn't exist yet —
    # Docker creates a directory in its place and the server crashes on read.
    DEPU_CONFIG_DIR=/app/conf \
    DEPU_CONFIG_PATH=/app/conf/config.toml \
    # Run as a non-root user so files written to mounted volumes (config, data)
    # are owned by a normal uid (1000) instead of root — the host user can then
    # edit them outside the container. Override PUID/PGID in the entrypoint to
    # match the host user if 1000 isn't right.
    PUID=1000 \
    PGID=1000
RUN apt-get update && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src ./src
# Bundled default template; entrypoint copies it to the config dir on first start.
COPY config.example.toml ./config.example.toml
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# Pre-create the runtime user and the mount dirs with sane ownership.
RUN groupadd -g 1000 depu && useradd -u 1000 -g 1000 -d /app -s /usr/sbin/nologin depu \
    && mkdir -p /app/conf /app/data && chown -R depu:depu /app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8080/admin/health', timeout=3); sys.exit(0)" || exit 1
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "-m", "depu_img_mcp"]

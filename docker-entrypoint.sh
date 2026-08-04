#!/bin/sh
# Entrypoint: runs as root, fixes ownership of mounted volumes, seeds a default
# config on first start, then drops privileges to the non-root `depu` user.
#
# Why root at the start: bind-mounted dirs arrive owned by the host user (often
# not uid 1000). We chown them to the runtime user so the server can write, and
# so the generated config is owned by a normal uid the host user can edit.
set -e

CONF_DIR="${DEPU_CONFIG_DIR:-/app/conf}"
CONF_FILE="${DEPU_CONFIG_PATH:-$CONF_DIR/config.toml}"
TEMPLATE="/app/config.example.toml"
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

# Recreate the runtime user/group to match requested PUID/PGID (so files written
# to mounts land with the host user's uid). Defaults to 1000:1000.
if [ "$PUID" != "1000" ] || [ "$PGID" != "1000" ]; then
    groupmod -o -g "$PGID" depu 2>/dev/null || true
    usermod -o -u "$PUID" depu 2>/dev/null || true
fi

# Fix ownership of mount points so the non-root process can read/write them.
chown -R depu:depu "$CONF_DIR" 2>/dev/null || true
mkdir -p "$CONF_DIR"
chown -R depu:depu /app/data 2>/dev/null || true

# Seed a default config on first start (empty mount dir).
if [ ! -f "$CONF_FILE" ]; then
    echo "[entrypoint] no config found at $CONF_FILE — seeding from bundled default"
    cp "$TEMPLATE" "$CONF_FILE"
    chown depu:depu "$CONF_FILE"
fi

# Drop privileges and run the server as depu.
exec gosu depu "$@"

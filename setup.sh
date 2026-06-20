#!/usr/bin/env bash
# Creates the directories docker-compose.yml bind-mounts, and copies the
# example config into place, before the first `docker compose up`. Without
# this, Docker creates any missing mount target itself as root, which the
# container's non-root app user (uid 1000) then can't write into.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

mkdir -p config cache library logs adb_keys artwork spotify_cache

if [ ! -f config/config.yaml ]; then
    cp config.example.yaml config/config.yaml
    echo "Created config/config.yaml - edit it with your devices' IPs/credentials."
else
    echo "config/config.yaml already exists, leaving it alone."
fi

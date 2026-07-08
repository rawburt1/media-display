#!/usr/bin/env bash
# Creates the directories docker-compose.yml bind-mounts, and copies the
# starter config into place, before the first `docker compose up`. Without
# this, Docker creates any missing mount target itself as root, which the
# container's non-root app user (uid 1000) then can't write into.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

mkdir -p config cache library logs adb_keys artwork spotify_cache overrides

if [ ! -f config/config.yaml ]; then
    cp config.starter.yaml config/config.yaml
    echo "Created config/config.yaml - after 'docker compose up -d', open"
    echo "http://<this-machine>:8094 to add your sources/displays from the"
    echo "browser (see config.example.yaml for the full option reference if"
    echo "you'd rather edit YAML by hand)."
else
    echo "config/config.yaml already exists, leaving it alone."
fi

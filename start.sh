#!/usr/bin/env bash
# Start media-display and all supporting services.
# Safe to re-run: setup.sh is idempotent, `docker compose up -d` is a no-op
# for containers that are already running and up to date.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

bash setup.sh
docker compose --profile autoheal up -d

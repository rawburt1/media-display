#!/usr/bin/env bash
# Runs vinyl_recognizer using the venv/config set up by ./install.sh.
# Must invoke `python -m vinyl_recognizer` with the *parent* directory of
# this folder as cwd - its modules import each other as
# `from vinyl_recognizer.x import y`, and Python only resolves that
# package name one level up (same reason the Dockerfile uses
# WORKDIR /app + COPY . ./vinyl_recognizer). Extra args are passed
# through, e.g. ./start.sh --list-devices.
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -x "$script_dir/.venv/bin/python" ]; then
    echo "No .venv found - run ./install.sh first." >&2
    exit 1
fi

if [ ! -f "$script_dir/config.yaml" ]; then
    echo "No config.yaml found - run ./install.sh first, then edit it." >&2
    exit 1
fi

cd "$script_dir/.."
exec "$script_dir/.venv/bin/python" -m vinyl_recognizer --config "$script_dir/config.yaml" "$@"

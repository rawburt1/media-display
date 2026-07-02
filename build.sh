#!/bin/bash
# Workaround for docker compose build v5 not correctly transferring the build
# context when using BuildKit bake. Use docker build directly instead.
set -e
docker build --no-cache -t media-display-mediainfo:latest .
echo "Build complete. Run 'docker compose restart mediainfo' to apply."

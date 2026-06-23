#!/usr/bin/env bash
# Installs vinyl_recognizer's system + Python dependencies and creates
# config.yaml from the example if it doesn't exist yet. Run once per
# machine before the first ./start.sh. See README.md for what each
# recognition_provider needs and why.
#
# Pass --with-vibra to also build the "vibra" provider's CLI binary from
# source (https://github.com/BayernMuller/vibra) - skipped by default
# since it requires compiling C++ and most providers don't need it.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

with_vibra=0
for arg in "$@"; do
    case "$arg" in
        --with-vibra) with_vibra=1 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

echo "==> Installing system packages (sounddevice/acoustid/shazam need these)..."
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
    libportaudio2 libchromaprint-tools ffmpeg

if [ "$with_vibra" -eq 1 ]; then
    if command -v vibra >/dev/null 2>&1; then
        echo "==> vibra already on PATH, skipping build."
    else
        echo "==> Building vibra (https://github.com/BayernMuller/vibra) from source..."
        sudo apt-get install -y --no-install-recommends \
            git cmake build-essential libcurl4-openssl-dev
        vibra_src="$(mktemp -d)"
        git clone --depth 1 https://github.com/BayernMuller/vibra.git "$vibra_src"
        cmake -S "$vibra_src" -B "$vibra_src/build" \
            -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF
        cmake --build "$vibra_src/build" -j"$(nproc)"
        sudo install -m 755 "$vibra_src/build/cli/vibra" /usr/local/bin/vibra
        rm -rf "$vibra_src"
    fi
fi

echo "==> Setting up Python virtualenv (.venv)..."
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
    echo "==> Created config.yaml - edit recognition_provider/credentials/input_device before starting."
else
    echo "==> config.yaml already exists, leaving it alone."
fi

cat <<'EOF'

Setup complete. Next steps:
  1. .venv/bin/python -m vinyl_recognizer --list-devices   (find your UCA202)
  2. edit config.yaml: input_device, recognition_provider, and its credentials
  3. ./start.sh
EOF

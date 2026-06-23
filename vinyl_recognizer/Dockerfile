# --- Build vibra (native Shazam-recognition CLI used by the "vibra"
# provider - see vibra.py) from source. Not packaged for apt, so it's
# compiled here and only the resulting binary is copied into the final
# image. -DBUILD_TESTING=OFF skips fetching/building vibra's own
# GoogleTest suite (CMakeLists.txt's `include(CTest)` defaults that ON).
FROM debian:bookworm-slim AS vibra-builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    git cmake build-essential libcurl4-openssl-dev ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/BayernMuller/vibra.git /vibra-src
RUN cmake -S /vibra-src -B /vibra-src/build \
        -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
    && cmake --build /vibra-src/build -j"$(nproc)"

FROM python:3.12-slim

WORKDIR /app

# sounddevice needs PortAudio's runtime library; the "acoustid" provider
# needs the fpcalc binary (Chromaprint) to compute fingerprints; the
# "shazam" provider needs ffmpeg for shazamio's own audio decoding; the
# "vibra" provider's binary (copied in below) is dynamically linked
# against libcurl4.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libportaudio2 libchromaprint-tools ffmpeg libcurl4 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=vibra-builder /vibra-src/build/cli/vibra /usr/local/bin/vibra

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./vinyl_recognizer

EXPOSE 8091

CMD ["python", "-m", "vinyl_recognizer", "--config", "config.yaml"]

FROM python:3.12-slim

WORKDIR /app

# sounddevice needs PortAudio's runtime library.
RUN apt-get update && apt-get install -y --no-install-recommends libportaudio2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./vinyl_recognizer

EXPOSE 8091

CMD ["python", "-m", "vinyl_recognizer", "--config", "config.yaml"]

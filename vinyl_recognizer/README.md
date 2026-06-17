# vinyl_recognizer

Identifies whatever's currently playing on a turntable by listening to its
audio, and serves the result over HTTP for `pixoo_media`'s `vinyl` source to
poll.

Runs as a separate, standalone service on whichever machine your audio
interface is connected to (it does not need to be the same machine that runs
the main `pixoo_media` app/container).

## Hardware setup

- Connect your turntable's output to a **Behringer UCA202** (or similar USB
  audio interface) via its line-in/RCA inputs.
- Connect the UCA202 to this machine via USB.
- The turntable's output should *also* still go to your Sonos (or other
  amp/speakers) as normal - the UCA202 is just an extra tap so this service
  can "listen in".

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Find your UCA202's device name/index:
python -m vinyl_recognizer --list-devices

cp config.example.yaml config.yaml
# edit config.yaml: set audd_api_key and input_device

python -m vinyl_recognizer --config config.yaml
```

On Linux, `sounddevice` requires the `libportaudio2` system package
(`sudo apt install libportaudio2`).

## Configuration

See `config.example.yaml` for all options. Key things to fill in:

- **`audd_api_key`**: API token from https://dashboard.audd.io/ (free tier
  is ~300 requests/day).
- **`input_device`**: a substring of your UCA202's name (e.g. `"UCA202"`)
  as shown by `--list-devices`, or its numeric index. Empty uses the
  system default input device.
- **`recognition_interval_seconds`**: minimum time between AudD requests
  while audio is playing. Keep this high enough (default 60s) to stay
  within AudD's free tier over a few hours of listening.
- **`silence_threshold`** / **`silence_grace_seconds`**: control when the
  service decides nothing is playing (so it stops calling AudD and reports
  an empty result).

## How it works

A background loop wakes up every `poll_interval_seconds` and records a
short clip to check for signal (RMS amplitude). If the turntable is silent,
nothing is sent anywhere. Once signal is detected, and at least
`recognition_interval_seconds` has passed since the last attempt, it records
a longer clip and sends it to AudD. The most recent successful result
(title/artist/album/artwork) is cached and served at:

```
GET /now-playing
```

returning either `{}` (nothing currently playing) or:

```json
{
  "title": "Comfortably Numb",
  "artist": "Pink Floyd",
  "album": "The Wall",
  "artwork_url": "https://..."
}
```

## Running with Docker

```bash
cp config.example.yaml config.yaml
# edit config.yaml
docker compose up -d --build
```

This passes `/dev/snd` through to the container so it can access the
UCA202. If the container can't open the audio device, try running it
without Docker instead (USB audio passthrough can be finicky).

## Running tests

```bash
pip install pytest
pytest vinyl_recognizer/tests
```

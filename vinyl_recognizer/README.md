# vinyl_recognizer

Identifies whatever's currently playing on a turntable by listening to its
audio, and serves the result over HTTP for `mediainfo`'s `vinyl` source to
poll.

Runs as a separate, standalone service on whichever machine your audio
interface is connected to (it does not need to be the same machine that runs
the main `mediainfo` app/container).

## Hardware setup

- Connect your turntable's output to a **Behringer UCA202** (or similar USB
  audio interface) via its line-in/RCA inputs.
- Connect the UCA202 to this machine via USB.
- The turntable's output should *also* still go to your Sonos (or other
  amp/speakers) as normal - the UCA202 is just an extra tap so this service
  can "listen in".

## Setup

```bash
./install.sh
# add --with-vibra too if you want the "vibra" provider (see below) -
# skipped by default since it has to be compiled from source

# Find your UCA202's device name/index:
./start.sh --list-devices

# edit config.yaml: set input_device, and the API key/credentials for
# whichever recognition_provider you pick (see Configuration below)

./start.sh
```

`install.sh` installs the system packages every built-in provider except
`"vibra"` needs (`libportaudio2` for `sounddevice`, `libchromaprint-tools`
for AcoustID's `fpcalc`, `ffmpeg` for Shazam), creates a Python virtualenv
in `.venv` and installs `requirements.txt` into it, and copies
`config.example.yaml` to `config.yaml` if one doesn't exist yet. It's
idempotent - safe to re-run any time (e.g. after a `git pull`) to pick up
new dependencies; it won't touch an existing `config.yaml`.

`start.sh` runs the service using that venv/config (passing through any
extra args, e.g. `--list-devices`). Both scripts expect to be run from
within this `vinyl_recognizer/` directory.

The `"vibra"` provider needs the native `vibra` binary
(https://github.com/BayernMuller/vibra) on PATH, which isn't packaged for
apt - `./install.sh --with-vibra` builds and installs it (requires `git`,
`cmake`, `build-essential`, `libcurl4-openssl-dev`, all installed
automatically by the flag).

## Configuration

See `config.example.yaml` for all options. Key things to fill in:

- **`recognition_provider`**: `"audd"` (default), `"acrcloud"`,
  `"acoustid"`, `"shazam"`, or `"vibra"` - which API to send recognition
  clips to.
- **`audd_api_key`**: API token from https://dashboard.audd.io/ (free tier
  is ~300 requests/day). Only used when `recognition_provider: audd`.
- **`acrcloud_host`** / **`acrcloud_access_key`** / **`acrcloud_access_secret`**:
  project credentials from https://console.acrcloud.com/ (create a free
  "Audio & Video Recognition" project, then copy these from its console
  page). Only used when `recognition_provider: acrcloud`.
- **`acoustid_api_key`**: API key from https://acoustid.org/my-applications
  (free). Only used when `recognition_provider: acoustid` - and only works
  if the `fpcalc` binary is installed, since that's what computes the
  fingerprint AcoustID matches against (no raw audio is sent to AcoustID
  at all). AcoustID has no cover art of its own, so `artwork_url` is
  always empty for this provider.
- **`"shazam"`** needs no API key or credentials at all - it talks to
  Shazam's own backend via the `shazamio` library, the same way the
  mobile app does. Only requires `ffmpeg` to be installed.
- **`"vibra"`** also needs no API key - it talks to the same Shazam
  backend as `"shazam"`, but via the native `vibra` binary instead of
  the Python `shazamio` library (no ffmpeg/asyncio involved). Requires
  building https://github.com/BayernMuller/vibra from source yourself
  and putting the binary on PATH.
- **`input_device`**: a substring of your UCA202's name (e.g. `"UCA202"`)
  as shown by `--list-devices`, or its numeric index. Empty uses the
  system default input device.
- **`recognition_interval_seconds`**: minimum time between recognition
  requests while audio is playing. Keep this high enough (default 60s) to
  stay within your provider's free tier over a few hours of listening.
- **`silence_threshold`** / **`silence_grace_seconds`**: control when the
  service decides nothing is playing (so it stops calling AudD and reports
  an empty result).

## How it works

A background loop wakes up every `poll_interval_seconds` and records a
short clip to check for signal (RMS amplitude). If the turntable is silent,
nothing is sent anywhere. Once signal is detected, and at least
`recognition_interval_seconds` has passed since the last attempt, it records
a longer clip and sends it to whichever provider `recognition_provider`
selects (AudD, ACRCloud, AcoustID, Shazam, or vibra). The most recent
successful result (title/artist/album/artwork) is cached and served at:

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

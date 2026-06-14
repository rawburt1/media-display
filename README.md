# Pixoo64 Media Art Display

Polls "now playing" media sources on your network and shows the current
album art / poster on a [Divoom Pixoo64](https://divoom.com/) LED display
and on a simple local web page.

## Status

Currently implemented:

- **Sources**: Kodi (movie/episode posters, music), Sonos (album art)
- **Outputs**: Pixoo64 (local HTTP API), web page (`http://<host>:8090/`)
- Disk cache for downloaded artwork (each image is only fetched once)

Planned (add as new `MediaSource` plugins, see "Extending" below):
Spotify, Plex, Emby, Jellyfin.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml
# edit config.yaml with your devices' IPs/credentials

python -m pixoo_media --config config.yaml
```

The web page is then available at `http://<this-machine>:8090/`.

## Configuration

See `config.example.yaml` for all options. Key things to fill in:

- **`priority`**: ordered list of source names. When more than one source
  is active at once, the first one in this list wins.
- **`sources.kodi`**: Kodi host/port and credentials. In Kodi, enable
  *Settings → Services → Control → Allow remote control via HTTP*.
- **`sources.sonos`**: IP address of any Sonos speaker on your network
  (find it in the Sonos app under speaker settings, or your router's
  device list).
- **`outputs.pixoo`**: IP address of your Pixoo64 (Divoom app → device
  settings).
- **`outputs.web`**: host/port for the local web page.
- **`cache.dir`**: where downloaded artwork is stored.

## Extending with new sources/outputs

1. Add a config dataclass in `pixoo_media/config.py` and register it in
   `SOURCE_CONFIG_TYPES` (or `OUTPUT_CONFIG_TYPES`).
2. Add a new module under `pixoo_media/sources/` (or `outputs/`) that
   implements `MediaSource.get_now_playing()` (or `Output.update()` /
   `on_idle()`), returning a `pixoo_media.models.NowPlaying`.
3. Register the class in `SOURCE_CLASSES` (or `OUTPUT_CLASSES`) in
   `pixoo_media/__main__.py`.
4. Add it to `priority` (sources) or `outputs` (outputs) in your
   `config.yaml`.

Each source's `get_now_playing()` must catch its own connection errors and
return `None` rather than raising, so one unreachable source never breaks
the polling loop.

## Running tests

```bash
pip install pytest
pytest
```

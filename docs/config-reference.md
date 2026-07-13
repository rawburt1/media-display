# Config reference

Generated from the config dataclasses' own field metadata (name, type, default, required, secret, help text) - see `scripts/generate_config_reference.py`. Never hand-edit this file; re-run that script instead.

For a narrative, worked-example config with prose explanations and cross-references, see `config.example.yaml` in the project root instead - this file is a flat lookup table, not a guide.

## General settings

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `poll_interval_seconds` | int | `5` |  |  |  |
| `rotation_interval_seconds` | int | `30` |  |  |  |
| `priority` | list | `[]` |  |  |  |
| `idle_priority` | list | `[]` |  |  |  |
| `idle_mode` | str | `'priority'` |  |  | One of: priority, random. |
| `backoff_initial_seconds` | int | `30` |  |  |  |
| `backoff_max_seconds` | int | `300` |  |  |  |
| `nothing_playing_grace_seconds` | float | `2` |  |  |  |

## Cache

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `dir` | str | `'./cache'` |  |  | A folder path on this machine (inside the container, if running under Docker). |
| `max_age_days` | int | `30` |  |  |  |
| `idle_max_age_hours` | int | `48` |  |  |  |
| `min_width` | int | `640` |  |  |  |
| `min_height` | int | `480` |  |  |  |
| `max_music_mb` | int | `500` |  |  |  |

## Playback History

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `True` |  |  | Turn this on to start using it. |
| `db_path` | str | `'./library/history.db'` |  |  |  |
| `max_entries` | int | `1000` |  |  |  |
| `dedupe_window_seconds` | int | `600` |  |  |  |

## Music Library Cache

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `db_path` | str | `'./library/library.db'` |  |  |  |
| `max_age_days` | int | `30` |  |  |  |

## Artwork Overrides

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `True` |  |  | Turn this on to start using it. |
| `dir` | str | `'./overrides'` |  |  | A folder path on this machine (inside the container, if running under Docker). |

## Poster Store

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `True` |  |  | Turn this on to start using it. |
| `dir` | str | `'./posters'` |  |  | A folder path on this machine (inside the container, if running under Docker). |

## Alerts

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `webhook_url` | str | `''` |  |  |  |
| `error_threshold_seconds` | int | `300` |  |  |  |
| `repeat_interval_seconds` | int | `3600` |  |  |  |

## Authentication

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `username` | str | `''` |  |  | Login username, if this service requires one. |
| `password` | str | `` |  | ✓ | Login password, if this service requires one. |

## Logging

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `level` | str | `'INFO'` |  |  | One of: DEBUG, INFO, WARNING, ERROR, CRITICAL. |
| `file` | str | `''` |  |  |  |
| `max_bytes` | int | `1000000` |  |  |  |
| `backup_count` | int | `3` |  |  |  |

## Unified Media Data Cache

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `path` | str | `'./mediadata'` |  |  |  |
| `cache_first` | bool | `True` |  |  |  |
| `max_disk_mb` | int | `2000` |  |  |  |

## Media sources

### Sources → Apple TV

Detects what's playing on an Apple TV via tvOS's now-playing API. Needs a one-time pairing (below).

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `''` |  |  | The device or server's hostname or IP address on your network. |
| `companion_credentials` | str | `` |  | ✓ |  |
| `mrp_credentials` | str | `` |  | ✓ |  |
| `airplay_credentials` | str | `` |  | ✓ |  |

### Sources → Browser extension

Receives now-playing info pushed by the companion browser extension (YouTube, Spotify Web, Netflix, Disney+, SVT Play, Plex Web) over a WebSocket connection.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `'0.0.0.0'` |  |  | The device or server's hostname or IP address on your network. |
| `port` | int | `8096` |  |  | The network port it listens on - the default is usually correct. |
| `token` | str | `` |  | ✓ | An access token from the service's own website or app. |
| `timeout` | float | `10.0` |  |  |  |

### Sources → Chromecast / Google Cast

Polls Cast-compatible devices (Chromecasts, Google/Android TVs, smart speakers) directly by IP address.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `device_ips` | list | `[]` |  |  | One IP address per line. |
| `ignore_apps` | list | `[]` |  |  | Cast app names to ignore (e.g. screensaver apps). Also list any Nest Hub used as an output here, to avoid it detecting its own cast image as "now playing". |

### Sources → Emby

Reads now-playing sessions from an Emby media server.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `''` | ✓ |  | The device or server's hostname or IP address on your network. |
| `port` | int | `8096` |  |  | The network port it listens on - the default is usually correct. |
| `api_key` | str | `` | ✓ | ✓ | A credential from the service's own website or app - see its help text below for where to get one. |

### Sources → foobar2000

Reads now-playing info from foobar2000 via the Beefweb Remote Control plugin.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `'localhost'` |  |  | The device or server's hostname or IP address on your network. |
| `port` | int | `8888` |  |  | The network port it listens on - the default is usually correct. |
| `api_type` | str | `'beefweb'` |  |  |  |
| `timeout` | float | `5.0` |  |  |  |

### Sources → Home Assistant

Tracks media_player entity state from Home Assistant over its WebSocket API - useful for a device HA already tracks that mediainfo can't read directly.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `''` | ✓ |  | The device or server's hostname or IP address on your network. |
| `port` | int | `8123` |  |  | The network port it listens on - the default is usually correct. |
| `use_ssl` | bool | `False` |  |  |  |
| `token` | str | `` | ✓ | ✓ | An access token from the service's own website or app. |
| `entity_id` | str | `''` |  |  | The media_player entity to track, e.g. media_player.apple_tv_4k - find it under Settings → Devices & Services → Entities in Home Assistant. Leave blank to track every media_player entity and report whichever one is playing. |

### Sources → Jellyfin

Reads now-playing sessions from a Jellyfin media server.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `''` | ✓ |  | The device or server's hostname or IP address on your network. |
| `port` | int | `8096` |  |  | The network port it listens on - the default is usually correct. |
| `api_key` | str | `` | ✓ | ✓ | A credential from the service's own website or app - see its help text below for where to get one. |

### Sources → Kodi

Reads now-playing info from a Kodi media center over its JSON-RPC API.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `''` | ✓ |  | The device or server's hostname or IP address on your network. |
| `port` | int | `8080` |  |  | The network port it listens on - the default is usually correct. |
| `username` | str | `''` |  |  | Login username, if this service requires one. |
| `password` | str | `` |  | ✓ | Login password, if this service requires one. |

### Sources → Logitech Media Server

Reads now-playing info from a Logitech Media Server (Squeezebox) via its JSON-RPC API. Set player_id if you have more than one player.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `'localhost'` |  |  | The device or server's hostname or IP address on your network. |
| `port` | int | `9000` |  |  | The network port it listens on - the default is usually correct. |
| `player_id` | str | `''` |  |  |  |
| `timeout` | float | `5.0` |  |  |  |

### Sources → Mopidy

Reads now-playing info from a Mopidy music server over its JSON-RPC API - works regardless of which Mopidy backend (Spotify, local files, ...) is actually playing.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `'localhost'` |  |  | The device or server's hostname or IP address on your network. |
| `port` | int | `6680` |  |  | The network port it listens on - the default is usually correct. |
| `timeout` | float | `5.0` |  |  |  |

### Sources → MPD (Music Player Daemon)

Reads now-playing info from an MPD server, and its embedded/folder cover art when available.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `'localhost'` |  |  | The device or server's hostname or IP address on your network. |
| `port` | int | `6600` |  |  | The network port it listens on - the default is usually correct. |
| `password` | str | `` |  | ✓ | Login password, if this service requires one. |
| `timeout` | float | `5.0` |  |  |  |

### Sources → Plex

Reads now-playing sessions from a Plex Media Server.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `''` | ✓ |  | The device or server's hostname or IP address on your network. |
| `port` | int | `32400` |  |  | The network port it listens on - the default is usually correct. |
| `token` | str | `` | ✓ | ✓ | An access token from the service's own website or app. |

### Sources → Nvidia Shield (Android TV)

Reads the foreground app on an Android TV device (e.g. Nvidia Shield) over ADB.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `''` | ✓ |  | The device or server's hostname or IP address on your network. |
| `port` | int | `5555` |  |  | The network port it listens on - the default is usually correct. |
| `adb_key_path` | str | `` |  | ✓ | Generated automatically on first run if missing - accept the authorization prompt on the device's screen. |

### Sources → Sonos

Reads what's playing on Sonos speakers on your network.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `speaker_ips` | list | `[]` |  |  | One IP address per line - any single speaker can reveal your whole Sonos household. |
| `blacklist` | list | `[]` |  |  |  |

### Sources → Spotify

Reads your current Spotify playback via the Spotify Web API.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `client_id` | str | `''` | ✓ |  |  |
| `client_secret` | str | `` | ✓ | ✓ |  |
| `redirect_uri` | str | `'http://localhost:8888/callback'` |  |  | Must exactly match the redirect URI registered in your Spotify developer dashboard app. |
| `cache_path` | str | `'./spotify_cache/token.json'` |  |  |  |

### Sources → Vinyl recognition

Identifies vinyl records played through a connected turntable, via the vinyl_recognizer service.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `''` | ✓ |  | The device or server's hostname or IP address on your network. |
| `port` | int | `8091` |  |  | The network port it listens on - the default is usually correct. |

### Sources → VLC

Reads now-playing info from VLC media player via its built-in web/HTTP interface.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `'localhost'` |  |  | The device or server's hostname or IP address on your network. |
| `port` | int | `8080` |  |  | The network port it listens on - the default is usually correct. |
| `password` | str | `` | ✓ | ✓ | Login password, if this service requires one. |
| `timeout` | float | `5.0` |  |  |  |

### Sources → YouTube (Android TV)

Reads the YouTube app's now-playing state on an Android TV device over ADB.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `''` | ✓ |  | The device or server's hostname or IP address on your network. |
| `port` | int | `5555` |  |  | The network port it listens on - the default is usually correct. |
| `adb_key_path` | str | `` |  | ✓ | Generated automatically on first run if missing. Use a different key file than sources.shield if pointed at the same device. |


## Idle screen sources

### Idle → Art pictures

Shows public-domain artworks from the Art Institute of Chicago's open collection while idle - no API key needed.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `rotation_interval_seconds` | int | `300` |  |  |  |
| `batch_size` | int | `10` |  |  |  |

### Idle → Last.fm scrobble history

Shows album art from your recent Last.fm listening history while idle.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `api_key` | str | `` |  | ✓ | A credential from the service's own website or app - see its help text below for where to get one. |
| `username` | str | `''` |  |  | Login username, if this service requires one. |
| `batch_size` | int | `10` |  |  |  |
| `rotation_interval_seconds` | int | `300` |  |  |  |

### Idle → Local music library

Shows album art for random albums from your local music library while idle.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `batch_size` | int | `10` |  |  |  |
| `rotation_interval_seconds` | int | `300` |  |  |  |

### Idle → Local folder

Shows pictures from a local folder (e.g. your own photos) while idle.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `dir` | str | `'./wallpapers'` |  |  | Each subfolder here is treated as one destination - one is picked at random each refresh. |
| `rotation_interval_seconds` | int | `300` |  |  |  |
| `batch_size` | int | `15` |  |  | Number of pictures to pick per refresh, from within the chosen destination. |

### Idle → Pexels photos

Shows photos from Pexels matching your search queries while idle.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `queries` | str | `''` |  |  | Comma-separated search terms, e.g. "nature,ocean,mountains". |
| `rotation_interval_seconds` | int | `300` |  |  |  |
| `batch_size` | int | `10` |  |  |  |
| `api_key` | str | `` |  | ✓ | A credential from the service's own website or app - see its help text below for where to get one. |

### Idle → Unsplash photos

Shows photos from Unsplash matching your search queries while idle.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `queries` | str | `''` |  |  | Comma-separated search terms, e.g. "nature,ocean,mountains". |
| `rotation_interval_seconds` | int | `300` |  |  |  |
| `batch_size` | int | `10` |  |  |  |
| `access_key` | str | `` |  | ✓ |  |


## Displays & outputs

### Outputs → Configuration UI

This web page - lets you edit configuration and check status from a browser.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `ui` | str | `'form'` |  |  | One of: form, dashboard. |

### Outputs → RSS/Atom feed

Publishes now-playing info as an RSS/Atom feed for podcast/feed readers.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `title` | str | `'Now Playing'` |  |  |  |

### Outputs → Folder export

Mirrors the current artwork/poster into a local folder, for other tools to pick up.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `dir` | str | `'./artwork'` |  |  | A folder path on this machine (inside the container, if running under Docker). |

### Outputs → Info page

A simple full-screen now-playing info page in a browser.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `transition_exclude` | list | `[]` |  |  | One of: fade, slide-left, slide-right, slide-up, slide-down, zoom. |

### Outputs → MQTT

Publishes now-playing events to an MQTT broker - handy for a Home Assistant integration.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `'localhost'` |  |  | The device or server's hostname or IP address on your network. |
| `port` | int | `1883` |  |  | The network port it listens on - the default is usually correct. |
| `topic` | str | `'mediainfo/now_playing'` |  |  | The MQTT topic to publish now-playing events to. |
| `client_id` | str | `'mediainfo'` |  |  |  |
| `username` | str | `''` |  |  | Login username, if this service requires one. |
| `password` | str | `` |  | ✓ | Login password, if this service requires one. |
| `qos` | int | `0` |  |  | 0 = at most once, 1 = at least once, 2 = exactly once. 0 is fine for most setups. |
| `retain` | bool | `True` |  |  |  |
| `ha_discovery` | bool | `False` |  |  | Automatically add a mediainfo device with now-playing sensors to Home Assistant. |
| `ha_discovery_prefix` | str | `'homeassistant'` |  |  |  |

### Outputs → Google Nest Hub

Casts the current artwork to a Google Nest Hub or other Cast-compatible display.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `device_ip` | str | `''` | ✓ |  | The device's IP address on your network. |
| `server_host` | str | `''` | ✓ |  |  |

### Outputs → Divoom Pixoo

Sends the current artwork to a Divoom Pixoo LED matrix display.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `ip` | str | `''` | ✓ |  | The device's IP address on your network. |
| `size` | int | `64` |  |  | 64 for the Pixoo64 (most common), 16 for the 16×16 Pixel Art LED Frame. |
| `preview_path` | str | `''` |  |  |  |
| `screen_off_hours` | str | `''` |  |  | Turn the panel off during this daily window, e.g. 23:00-07:00. Leave both times empty to always keep it on. |
| `brightness_schedule` | list | `[]` |  |  |  |
| `crop_strategy` | str | `'automatic'` |  |  | How to pick the square crop before downscaling. "automatic" biases toward the top third for portrait sources (posters/covers) and centers otherwise. One of: automatic, center, poster_top. |
| `palette_size` | int | `24` |  |  | Number of colours in the final image's palette. Lower (8-16) gives bolder pixel-art blocks; higher (24-32) allows subtler gradients. |
| `dithering` | str | `'none'` |  |  | "none" gives bold, clean colour blocks (recommended for small displays). "ordered" is subtler; "floyd_steinberg" is heavier and can look noisy at 16×16. One of: none, ordered, floyd_steinberg. |
| `contrast_boost` | str | `'medium'` |  |  | Contrast applied before downscaling, so colours stay punchy at low resolution. One of: off, low, medium, high. |
| `saturation_boost` | str | `'medium'` |  |  | Saturation applied before downscaling. One of: off, low, medium, high. |
| `dark_image_boost` | bool | `True` |  |  | Lift brightness on naturally dark artwork so it isn't mostly black on the LEDs. |
| `pixel_art_mode` | bool | `True` |  |  | Downsample in two stages for crisp, intentional pixel blocks instead of a single blurrier resize. |
| `text_detection_enabled` | bool | `False` |  |  | Detect and remove small poster/cover text (credits, subtitles) before downscaling. Requires text_detection_model_path. |
| `text_detection_model_path` | str | `''` |  |  | Path to a frozen_east_text_detection.pb file (OpenCV's EAST text detector) - not bundled, you'll need to provide your own. |
| `remove_small_text` | bool | `True` |  |  | Remove small, non-essential detected text (credits, subtitles, track listings). |
| `preserve_large_logos` | bool | `True` |  |  | Keep large titles/logos that remain legible at the final LED size instead of removing them. |
| `text_removal_method` | str | `'inpaint'` |  |  | "inpaint" gives the best reconstruction; "soft_fill" needs no extra dependency; "crop_preference" nudges the crop to avoid text instead of editing pixels. One of: inpaint, soft_fill, crop_preference. |
| `max_logo_area_percent` | float | `25.0` |  |  | A detected text region larger than this is treated as too big to be a normal logo and left alone. |

### Outputs → Display Themes

A separate full-screen display (its own port) that layers selectable visual effects - color palette, blurred background, glow, and more - on top of the current artwork. Pick which themes to enable below.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `transition_exclude` | list | `[]` |  |  | One of: fade, slide-left, slide-right, slide-up, slide-down, zoom. |

### Outputs → Ulanzi TC001 / AWTRIX3

Sends now-playing text and graphics to a Ulanzi TC001 or other AWTRIX3 device.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `device_ip` | str | `''` | ✓ |  | The device's IP address on your network. |
| `app_name` | str | `'now_playing'` |  |  |  |
| `username` | str | `''` |  |  | Login username, if this service requires one. |
| `password` | str | `` |  | ✓ | Login password, if this service requires one. |
| `screen_off_hours` | str | `''` |  |  | Turn the display off during this daily window, e.g. 23:00-07:00. Leave both times empty to always keep it on. |
| `brightness_schedule` | list | `[]` |  |  |  |

### Outputs → Video display

Shows looping idle background video (Pexels/Pixabay) plus now-playing artwork in a browser.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `source` | str | `'pexels'` |  |  | Which stock video provider to pull idle background clips from. One of: pexels, pixabay. |
| `queries` | str | `'nature,ocean,mountains'` |  |  | Comma-separated search queries; one is picked at random per refresh. |
| `refresh_interval_seconds` | int | `3600` |  |  |  |
| `batch_size` | int | `15` |  |  |  |
| `pexels_api_key` | str | `` |  | ✓ |  |
| `pixabay_api_key` | str | `` |  | ✓ |  |
| `transition_exclude` | list | `[]` |  |  | One of: fade, slide-left, slide-right, slide-up, slide-down, zoom. |

### Outputs → Web display

A full-screen now-playing display in any browser, with image transitions.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `transition_exclude` | list | `[]` |  |  | One of: fade, slide-left, slide-right, slide-up, slide-down, zoom. |


### Content filters (every output type)

Every output listed above also accepts these fields, in addition to its own - see config.example.yaml's "Per-output content filters" section for how they interact.


| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `allow_media_types` | list | `[]` |  |  | Leave empty to show every media type. One of: music, movie, episode. |
| `deny_media_types` | list | `[]` |  |  | Leave empty to not block any media type. One of: music, movie, episode. |
| `allow_sources` | list | `[]` |  |  | Leave empty to show every source. One of: appletv, browser, chromecast, emby, foobar2000, homeassistant, jellyfin, kodi, lms, mopidy, mpd, plex, shield, sonos, spotify, vinyl, vlc, youtube. |
| `deny_sources` | list | `[]` |  |  | Leave empty to not block any source. One of: appletv, browser, chromecast, emby, foobar2000, homeassistant, jellyfin, kodi, lms, mopidy, mpd, plex, shield, sonos, spotify, vinyl, vlc, youtube. |
| `idle_when_filtered` | bool | `False` |  |  | When on, this display switches to its idle screen instead of just freezing on the last item, whenever the rules above block what's currently playing. |
| `active_hours` | str | `''` |  |  | Example: 08:00 to 22:00 keeps this display active only during the day. Leave both empty for always-on. |
| `label` | str | `''` |  |  | Optional - shown instead of "Instance #2" etc. when there's more than one of this type. |

## Artwork & metadata enrichers

### Enrichers → ai_artwork

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `'localhost'` |  |  | The device or server's hostname or IP address on your network. |
| `port` | int | `7860` |  |  | The network port it listens on - the default is usually correct. |
| `steps` | int | `20` |  |  |  |
| `width` | int | `512` |  |  |  |
| `height` | int | `512` |  |  |  |
| `timeout_seconds` | int | `120` |  |  |  |

### Enrichers → Discogs

Looks up album cover art on Discogs.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `token` | str | `` | ✓ | ✓ | An access token from the service's own website or app. |

### Enrichers → Fanart.tv

Fetches high-quality movie/TV backdrops and posters.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `api_key` | str | `` | ✓ | ✓ | A credential from the service's own website or app - see its help text below for where to get one. |

### Enrichers → Audio fingerprinting

Identifies vinyl audio via the vinyl_recognizer service's fingerprint matching.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `'localhost'` |  |  | The device or server's hostname or IP address on your network. |
| `port` | int | `8091` |  |  | The network port it listens on - the default is usually correct. |
| `max_age_seconds` | int | `120` |  |  |  |

### Enrichers → Last.fm

Fetches artist photos from Last.fm.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `api_key` | str | `` | ✓ | ✓ | A credential from the service's own website or app - see its help text below for where to get one. |

### Enrichers → Local music library

Looks up cached metadata from mediainfo's own local music library, avoiding repeat external lookups.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `True` |  |  | Turn this on to start using it. |

### Enrichers → Lidarr

Adds a discography list from your Lidarr library.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `''` | ✓ |  | The device or server's hostname or IP address on your network. |
| `port` | int | `8686` |  |  | The network port it listens on - the default is usually correct. |
| `api_key` | str | `` | ✓ | ✓ | A credential from the service's own website or app - see its help text below for where to get one. |
| `max_discography_items` | int | `50` |  |  | Cap on how many tracks to list for a prolific artist. |

### Enrichers → mediadata

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |

### Enrichers → MusicBrainz

Looks up album cover art via the free Cover Art Archive - no API key needed.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |

### Enrichers → OMDb

Adds movie/show ratings from OMDb.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `api_key` | str | `` | ✓ | ✓ | A credential from the service's own website or app - see its help text below for where to get one. |

### Enrichers → Radarr

Confirms movie details against your Radarr library.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `''` | ✓ |  | The device or server's hostname or IP address on your network. |
| `port` | int | `7878` |  |  | The network port it listens on - the default is usually correct. |
| `api_key` | str | `` | ✓ | ✓ | A credential from the service's own website or app - see its help text below for where to get one. |

### Enrichers → Sonarr

Confirms TV show/episode details against your Sonarr library.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `''` | ✓ |  | The device or server's hostname or IP address on your network. |
| `port` | int | `8989` |  |  | The network port it listens on - the default is usually correct. |
| `api_key` | str | `` | ✓ | ✓ | A credential from the service's own website or app - see its help text below for where to get one. |

### Enrichers → SVT Play

Resolves Swedish SVT Play titles, so other enrichers can find matching artwork.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `True` |  |  | Turn this on to start using it. |
| `sonarr_host` | str | `''` |  |  |  |
| `sonarr_port` | int | `8989` |  |  |  |
| `sonarr_api_key` | str | `` |  | ✓ |  |

### Enrichers → TheTVDB

Fetches TV show/episode artwork and details.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `api_key` | str | `` | ✓ | ✓ | A credential from the service's own website or app - see its help text below for where to get one. |
| `pin` | str | `` |  | ✓ | Only needed for "user-supported" TheTVDB API keys. |
| `max_search_candidates` | int | `5` |  |  |  |

### Enrichers → TMDB

Fetches movie/TV artwork and ratings from The Movie Database.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `api_key` | str | `` | ✓ | ✓ | A credential from the service's own website or app - see its help text below for where to get one. |
| `fetch_cast` | bool | `False` |  |  | Fetch top-billed cast (name, character, headshot) for the Cast/Crew Mosaic Display Theme. Off by default - one extra TMDb API call per new movie/TV item. |
| `cast_size` | int | `8` |  |  | Cap on how many top-billed cast members to store. |

### Enrichers → Wikipedia

Adds a short plot or artist summary from Wikipedia - no API key needed.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |


## Lyrics & text enrichers

### Text enrichers → LRCLIB

Free, public time-synced lyrics lookup - no API key needed.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |

### Text enrichers → Local Media Data Cache (lyrics)

Checks the local unified media-data cache for lyrics before falling back to LRCLIB.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |

### Text enrichers → Ollama (local AI text)

Generates text via a local Ollama instance.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `host` | str | `'localhost'` |  |  | The device or server's hostname or IP address on your network. |
| `port` | int | `11434` |  |  | The network port it listens on - the default is usually correct. |
| `model` | str | `'llama3.2'` |  |  |  |
| `timeout_seconds` | int | `30` |  |  |  |


## Display Themes

### Themes → Artist Spotlight

A portrait card with the current artist's photo and a short bio blurb.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `corner` | str | `'bottom-left'` |  |  | Where the artist card appears on screen. One of: bottom-right, bottom-left, top-right, top-left, center. |
| `size_vw` | int | `25` |  |  | Max width as a percentage of screen width. |
| `show_bio` | bool | `True` |  |  | Show a short bio snippet below the artist name. |

### Themes → Blurred Background

Fills the screen behind the artwork with a heavily blurred, darkened copy of it.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `blur_radius` | int | `40` |  |  | How heavily to blur the background - higher is softer. |
| `brightness` | float | `0.6` |  |  | 1.0 = unchanged, below 1 darkens (keeps foreground text/art readable), above 1 brightens. |

### Themes → Cast/Crew Mosaic

A grid of top-billed cast headshots for the current movie/TV item. Needs enrichers.tmdb.fetch_cast enabled.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `corner` | str | `'top-right'` |  |  | Where the cast grid appears on screen. One of: bottom-right, bottom-left, top-right, top-left, center. |
| `size_vw` | int | `30` |  |  | Max width as a percentage of screen width. |
| `max_cast` | int | `6` |  |  | Cap on how many cast members to show - further capped by enrichers.tmdb.cast_size. |

### Themes → Color Palette

Shows the current artwork's dominant colors as a strip of swatches.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `swatch_count` | int | `5` |  |  | How many color swatches to show, most-prevalent first. |
| `swatch_position` | str | `'bottom'` |  |  | Where the swatch strip appears on screen. One of: bottom, top, side. |

### Themes → Equalizer

A decorative bar/wave animation suggesting audio activity. Music only - not a real audio visualizer, since no source exposes an actual audio signal.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `style` | str | `'bars'` |  |  | "bars" shows a row of animated bars; "wave" shows a scrolling waveform ribbon. Purely decorative - not driven by real audio. One of: bars, wave. |
| `position` | str | `'bottom'` |  |  | Which screen edge the strip runs along - all four corners are already used by other themes' defaults. One of: bottom, top. |
| `bar_count` | int | `24` |  |  | Number of bars, style="bars" only. |
| `opacity` | float | `0.7` |  |  | How visible the effect is, from 0 (invisible) to 1 (fully visible). |

### Themes → Glow

A soft, slowly pulsing ambient glow behind the artwork, colored from it.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `intensity` | float | `0.6` |  |  | How visible the glow is at its peak, from 0 (invisible) to 1 (fully visible). |
| `color_source` | str | `'album_art'` |  |  | "album_art" colors the glow from the artwork's own dominant color; "fixed" always uses fixed_color below. One of: album_art, fixed. |
| `fixed_color` | str | `'#ffffff'` |  |  | A CSS color (e.g. #ff8800) used when color_source is "fixed". |
| `pulse` | bool | `True` |  |  | Slowly grow and shrink the glow on a loop, instead of staying a fixed size. |

### Themes → Ken Burns

A slow, continuous pan/zoom on the artwork - the classic documentary-style effect.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `duration_seconds` | int | `20` |  |  | Seconds for one full pan/zoom cycle - lower is more noticeable motion. |
| `opacity` | float | `0.5` |  |  | How visible the animated layer is, from 0 (invisible) to 1 (fully visible). |

### Themes → Lyrics Ticker

A karaoke-style ticker highlighting the current line of time-synced lyrics. Music only - needs synced lyrics available (e.g. via text_enrichers.lrclib).

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `position` | str | `'top'` |  |  | Which screen edge the ticker runs along. One of: bottom, top. |
| `show_next_line` | bool | `True` |  |  | Show the upcoming line, faded, below the current one. |

### Themes → Media Mosaic

A grid of related artwork (other albums, other posters/fanart) alongside the current pick.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `corner` | str | `'top-right'` |  |  | Where the mosaic appears on screen. One of: bottom-right, bottom-left, top-right, top-left, center. |
| `size_vw` | int | `30` |  |  | Max width as a percentage of screen width. |
| `max_tiles` | int | `6` |  |  | Cap on how many tiles to include - only artwork already available for the current item (other albums, posters, fanart) is used, never fetched specially. |

### Themes → Now Playing Progress

A real-data full-width playback progress border along one screen edge. Works for music, movies, and TV whenever position/duration are known.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `position` | str | `'bottom'` |  |  | Which screen edge the progress border runs along. One of: bottom, top. |
| `thickness_px` | int | `6` |  |  | Height of the border in pixels. |
| `color` | str | `'#ffffff'` |  |  | A CSS color (e.g. #ff8800) for the filled portion. |

### Themes → Timeline

A list of the artist's other albums alongside the current one. Music only - needs Lidarr configured, or just shows the current album.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `corner` | str | `'top-left'` |  |  | Where the album list appears on screen. One of: bottom-right, bottom-left, top-right, top-left, center. |
| `max_albums` | int | `8` |  |  | Cap on how many albums to list. Needs enrichers.lidarr configured with the playing artist in your Lidarr library - otherwise this just shows the current album. |

### Themes → Vinyl

Shows the album art as a spinning vinyl record. Music only.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `corner` | str | `'bottom-left'` |  |  | Where the record appears on screen. One of: bottom-right, bottom-left, top-right, top-left, center. |
| `size_vmin` | int | `40` |  |  | Diameter as a percentage of the shorter screen dimension. |
| `rotation_seconds` | int | `8` |  |  | Seconds for one full rotation - lower spins faster. Purely decorative - it can't stop on pause, since no source reports that state. |

### Themes → Word Cloud

Shows a word cloud built from the lyrics (music) or plot summary (movies/TV), colored from the artwork.

| Field | Type | Default | Required | Secret | Help |
|---|---|---|---|---|---|
| `enabled` | bool | `False` |  |  | Turn this on to start using it. |
| `corner` | str | `'bottom-right'` |  |  | Where the word cloud appears on screen. One of: bottom-right, bottom-left, top-right, top-left, center. |
| `size_vw` | int | `35` |  |  | Width as a percentage of screen width (it's square, so this sets its height too, capped to screen height). |


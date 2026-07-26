# Extending with new sources/outputs/enrichers

1. Add a config dataclass in `mediainfo/config/sources.py` (or `outputs.py`,
   `enrichers.py`, `idle.py`) and register it in that module's
   `SOURCE_CONFIG_TYPES` (or `OUTPUT_CONFIG_TYPES`, `ENRICHER_CONFIG_TYPES`,
   `IDLE_CONFIG_TYPES`).
2. Add a new module under `mediainfo/sources/` (or `outputs/`, or
   `idle/`) that implements `MediaSource.get_now_playing()` (or
   `Output.update()` / `on_idle()`, or
   `IdleWallpaperSource.get_wallpapers()`), returning a
   `mediainfo.models.NowPlaying` (or a list of `Artwork`).
3. Register it in `SOURCE_CLASSES` (or `OUTPUT_CLASSES`, `ENRICHER_CLASSES`,
   `IDLE_CLASSES`) in `mediainfo/registries.py`, as a dotted import-path
   string (e.g. `"mediainfo.sources.kodi.KodiSource"`) rather than the
   class itself - these are resolved lazily on first use, so adding a
   source doesn't force every plugin's own dependencies to be imported
   up front just to build this dict.
4. Add it to `priority` (sources), `outputs` (outputs), `enrichers`
   (enrichers), or `idle` (idle wallpaper sources) in your `config.yaml`.

Each source's `get_now_playing()` must catch its own connection errors and
return `None` rather than raising, so one unreachable source never breaks
the polling loop. Set `self.last_poll_failed = True` when that `None` was
caused by a connection failure (device unreachable), and `False` when it
connected fine and simply found nothing playing - the orchestrator uses
this to back off polling frequency (starting at `backoff_initial_seconds`
[default 30s], doubling up to `backoff_max_seconds` [default 5 minutes] -
both configurable at the top level of `config.yaml`) for sources whose
device is unreachable, without delaying detection for sources that are
just legitimately idle.

Enrichers still run one at a time, in the order they're listed, since
several rely on state an earlier one left on the item (e.g. checking
`now_playing.images` before deciding whether to add their own). Each one
gets `enrichment_deadline_seconds` (top-level, default 30s) to finish before
the tick gives up waiting and moves on to the next enricher, so one
hung/slow lookup can't block every display indefinitely - an enricher whose
own config exposes `timeout_seconds` (e.g. `ai_artwork`, `ollama_text`) uses
that instead, since those are already tuned for slower local inference.

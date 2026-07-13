# 0002. Unified on-disk media metadata/artwork/lyrics store: layout and freshness policy

## Status

Accepted. Extracted from `mediainfo/media_data_store.py`'s module
docstring during N6 (see `docs/architecture-usability-review-2026-07.md`);
no behavior changed.

## Context

`MediaDataStore` provides a unified on-disk cache for movie/series/album
artwork, artist photos, and music lyrics — a human-browsable folder per
movie/series/album (e.g. `movies/Alien (1979)/poster.jpg`), each with a
`metadata.json` tracking where each piece of content came from and when it
was last checked/updated. Several existing caches already covered pieces
of this (`mediainfo.cache.ImageCache`, `mediainfo.text_cache.TextCache`,
`mediainfo.poster_store.PosterStore`, `mediainfo.artwork_overrides.
ArtworkOverrideStore`), so the design needed to add unified,
audit-friendly storage without disrupting any of them.

## Decision

**Additive, not a replacement.** `MediaDataStore` is wired into the live
enrichment pipeline via `mediainfo/enrichers/mediadata.py` (artwork: music
album art + artist photo, movie/series posters+fanart, and a lyrics word
cloud) and `mediadata_lyrics.py` (music lyrics) — opt-in, off by default.
`ImageCache`, `TextCache`, `PosterStore`, and `ArtworkOverrideStore` are
all untouched and keep working exactly as before; nothing here replaces or
migrates them. `ImageCache` is reused internally for the actual artwork
download step (see `_download_bytes`).

**Provider fallback order.** Movie/series artwork is TMDb-first, falling
back to fanart.tv for movies only — fanart.tv's TV lookup needs a TVDB id
this store has no way to resolve (see `_fetch_series_artwork`'s
docstring). Artist photo is Wikipedia-first, falling back to Last.fm. A
lyrics word cloud (non-masked only, see `get_track_wordcloud`) is rendered
locally, not fetched, once both lyrics and album art are cached, behind
its own `enrichers.mediadata.wordcloud.enabled` switch.

**Directory layout:**

```
{path}/movies/{Title} ({Year})/poster.jpg
{path}/movies/{Title} ({Year})/fanart.jpg
{path}/movies/{Title} ({Year})/metadata.json
{path}/series/{Title} ({Year})/... (same shape as movies)
{path}/music/{Artist}/artist.jpg
{path}/music/{Artist}/metadata.json (artist-level: just artist_photo)
{path}/music/{Artist}/{Album} ({Year})/albumart.jpg
{path}/music/{Artist}/{Album} ({Year})/fanart.jpg
{path}/music/{Artist}/{Album} ({Year})/{Track Title}.lrc
{path}/music/{Artist}/{Album} ({Year})/{Track Title}.wordcloud_nomask.png
{path}/music/{Artist}/{Album} ({Year})/metadata.json
```

When year is unknown, the "(Year)" suffix is simply omitted from the
directory name until a later fetch resolves it (see
`_relocate_to_year_dir`).

**Explicit freshness timestamps, not file mtime.** `metadata.json` tracks
explicit ISO-8601 `last_checked`/`last_updated` timestamps per artwork/
lyrics entry, rather than relying on file mtime the way `ImageCache`/
`TextCache` do — the point of this store is auditable, inspectable
staleness state, and a file copy/backup bumping mtime shouldn't count as
"we just checked."

**Two-tier public API: cache-first `get_*`, force-fetch `refresh_*`.**

```
get_movie_poster(title, year) / get_movie_fanart(title, year)
get_series_poster(title, year) / get_series_fanart(title, year)
get_album_art(artist, album, year) / get_album_fanart(artist, album, year)
get_artist_photo(artist)
get_track_lyrics(artist, album, title, year=None)
get_track_wordcloud(artist, album, title, year=None)
refresh_movie(title, year) / refresh_series(title, year)
refresh_album(artist, album, year) / refresh_artist_photo(artist)
refresh_track_lyrics(artist, album, title, year=None)
refresh_track_wordcloud(artist, album, title, year=None)
```

Each `get_*` follows cache-first plus the per-media-type refresh policy in
`MediaDataConfig.refresh` (`movies_days`/`series_days`/`music_days`;
lyrics and the word cloud never auto-refresh by age). Each `refresh_*`
forces an immediate fetch (or, for the word cloud, regeneration) attempt
regardless of freshness — intended for a future config UI's "Refresh
poster"/"Refresh fanart"/"Refresh lyrics" buttons — and returns whether
anything was actually updated.

## Consequences

- A user can browse `{path}/movies/...` directly in a file manager and
  understand what's cached and when it was last checked, without needing
  to inspect `ImageCache`'s flat hash-named files.
- Four cache/store implementations now coexist deliberately
  (`ImageCache`, `TextCache`, `PosterStore`, `ArtworkOverrideStore`, plus
  `MediaDataStore` itself) rather than being consolidated — accepted
  complexity in exchange for not disrupting working, already-tested code
  paths. `docs/architecture-usability-review-2026-07.md`'s Phase 9 flags
  this module (935 lines: cache policy + fetch orchestration + path layout
  + wordcloud all in one class) as a complexity hotspot worth splitting
  fetchers from the store, independent of this ADR.
- Lyrics/word-cloud content never auto-expires by age (only movies/series/
  music artwork do) — a deliberate asymmetry, not an oversight: lyrics
  rarely change once published, and the word cloud is a local render, not
  a fetch, so there's nothing to go stale against.

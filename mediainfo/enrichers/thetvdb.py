"""thetvdb.com enricher: adds posters/backgrounds for TV shows.

Most sources (Kodi, Jellyfin/Emby, Plex) already supply a tvdb series id
from their own local library metadata. Sources that can't (e.g. the
Shield source, which only knows a title parsed from a generic Android
media session - see sources/shield.py) get a title-based fallback here:
thetvdb.com's own search API resolves a series name to its id, cached in
memory for the life of the process (same trade-off as the Wikipedia
enricher's cache - no persistence, but a given title is only looked up
once per run). The resolved id is written back into `now_playing.ids`,
so the fanart.tv enricher's TV branch (which also needs a tvdb id) gets
to use it too, if it runs afterward.

A bare title search is ambiguous for common show names ("Kingdom" matches
at least three unrelated series). When the search returns more than one
candidate, the episode subtitle (e.g. "5. När makten skiftar" - shield.py
and similar sources report it as "<number>. <episode title>") is used to
disambiguate: each candidate's episode list (in the subtitle's language,
where available) is checked for an episode whose name actually matches,
and only a verified match is used. If nothing can be verified, this
returns no artwork rather than guessing and attaching a wrong show's
poster - the original failure mode this exists to fix.
"""

from __future__ import annotations

import logging
import re
from typing import Any, List, Optional, Tuple

import requests

from mediainfo.config import TheTvDbConfig
from mediainfo.enrichers.base import ArtworkEnricher
from mediainfo.models import Artwork, NowPlaying

logger = logging.getLogger(__name__)

_BASE_URL = "https://api4.thetvdb.com/v4"

# Sources that report an episode subtitle as "<number>. <episode title>"
# (e.g. the Shield source, for SVT Play - see sources/shield.py).
_EPISODE_SUBTITLE_RE = re.compile(r"^\s*\d+\.\s*(.+)$")


class TheTvDbEnricher(ArtworkEnricher):
    name = "thetvdb"
    config_class = TheTvDbConfig

    def __init__(self, config: TheTvDbConfig):
        self.config = config
        self._token: Optional[str] = None
        # Artwork "type" ids for series posters/backgrounds, discovered from
        # /artwork/types on first use (these ids are not documented as fixed
        # constants, so look them up by name instead of hardcoding them).
        self._poster_type: Optional[int] = None
        self._background_type: Optional[int] = None
        # (title, subtitle) -> resolved series id (or None for "not
        # found"/"unverifiable"), for sources that only give us a name -
        # see module docstring. Keyed on subtitle too, since which series
        # is correct can depend on which episode is actually playing.
        self._series_search_cache: dict[Tuple[str, str], Optional[str]] = {}

    def enrich(self, now_playing: NowPlaying) -> None:
        if now_playing.media_type != "episode":
            return

        try:
            series_id = now_playing.ids.get("tvdb")
            if not series_id:
                if not now_playing.title:
                    return
                series_id = self._resolve_series_id(now_playing.title, now_playing.subtitle)
                # When the device title is a local translation (e.g. a Swedish
                # SVT title) and the primary search found nothing, try with the
                # original-language title if one was provided by a prior enricher
                # (e.g. SVT's own `originalProgramTitle` field via the SVT enricher).
                if not series_id and now_playing.original_title:
                    series_id = self._resolve_series_id(
                        now_playing.original_title, now_playing.subtitle
                    )
                if not series_id:
                    return
                now_playing.ids["tvdb"] = series_id

            if not self._ensure_artwork_types():
                return

            data = self._get(f"/series/{series_id}/artworks", params={"lang": "eng"})
            if not data:
                return

            artworks = data.get("artworks") or []
            self._append_best(now_playing, artworks, self._poster_type, "Poster (TheTVDB)")
            self._append_best(now_playing, artworks, self._background_type, "Fanart (TheTVDB)")
        except Exception:
            logger.exception("thetvdb.com enrichment error")

    def test_connection(self) -> Tuple[bool, str]:
        try:
            token = self._login()
            if token:
                return True, "Logged in successfully"
            return False, "Login failed - check api_key/pin"
        except Exception as exc:
            return False, f"Error: {exc}"

    def _resolve_series_id(self, title: str, subtitle: str) -> Optional[str]:
        cache_key = (title, subtitle)
        if cache_key in self._series_search_cache:
            return self._series_search_cache[cache_key]

        results = self._get("/search", params={"query": title, "type": "series"}) or []
        all_candidates = [str(r["tvdb_id"]) for r in results if r.get("tvdb_id")]
        candidates = all_candidates[: self.config.max_search_candidates]

        if len(all_candidates) <= 1:
            # Nothing to disambiguate - trust the only (or lack of a) match.
            series_id = candidates[0] if candidates else None
        else:
            series_id = self._disambiguate_by_episode(candidates, subtitle)
            if series_id is None:
                logger.info(
                    "thetvdb: could not verify any of %d candidate(s) for %r against "
                    "episode %r (of %d total search results) - no artwork added",
                    len(candidates),
                    title,
                    subtitle,
                    len(all_candidates),
                )

        self._series_search_cache[cache_key] = series_id
        return series_id

    def _disambiguate_by_episode(self, candidate_ids: List[str], subtitle: str) -> Optional[str]:
        """Among several same-titled series, return the one whose episode
        list actually contains an episode matching `subtitle` - or None if
        none can be verified (better no artwork than a wrong show's).
        """
        match = _EPISODE_SUBTITLE_RE.match(subtitle or "")
        if not match:
            logger.info(
                "thetvdb: %d candidates for an ambiguous title, but subtitle %r isn't in "
                "'<number>. <episode title>' form - can't disambiguate, no artwork added",
                len(candidate_ids),
                subtitle,
            )
            return None

        target = match.group(1).strip().casefold()
        if not target:
            return None

        # The episode title in `subtitle` may be in a language other than
        # whatever thetvdb's default/original-language episode names are
        # (e.g. Swedish for SVT Play) - try the default list, then fall
        # back to a Swedish-translated one, where thetvdb has it. Add more
        # languages here as _VIDEO_PACKAGES (sources/shield.py) grows.
        for params in (None, {"lang": "swe"}):
            for candidate_id in candidate_ids:
                data = self._get(f"/series/{candidate_id}/episodes/default", params=params)
                for episode in (data or {}).get("episodes") or []:
                    name = (episode.get("name") or "").strip().casefold()
                    if name and (name == target or target in name or name in target):
                        return candidate_id

        return None

    def _ensure_artwork_types(self) -> bool:
        if self._poster_type is not None and self._background_type is not None:
            return True

        types = self._get("/artwork/types")
        if not types:
            return False

        for entry in types:
            if entry.get("recordType") != "series":
                continue
            name = (entry.get("name") or "").strip().lower()
            if name == "poster":
                self._poster_type = entry.get("id")
            elif name in ("background", "fanart"):
                self._background_type = entry.get("id")

        return self._poster_type is not None and self._background_type is not None

    def _login(self) -> Optional[str]:
        payload: dict[str, str] = {"apikey": self.config.api_key}
        if self.config.pin:
            payload["pin"] = self.config.pin

        try:
            response = requests.post(f"{_BASE_URL}/login", json=payload, timeout=10)
            response.raise_for_status()
            return response.json().get("data", {}).get("token")
        except Exception:
            logger.exception("thetvdb.com login failed")
            return None

    def _get(self, path: str, params: Optional[dict] = None) -> Optional[Any]:
        if self._token is None:
            self._token = self._login()
            if self._token is None:
                return None

        url = f"{_BASE_URL}{path}"
        response = requests.get(
            url, headers={"Authorization": f"Bearer {self._token}"}, params=params, timeout=10
        )

        if response.status_code == 401:
            # Token likely expired (tokens last ~1 month); re-login once and retry.
            self._token = self._login()
            if self._token is None:
                return None
            response = requests.get(
                url, headers={"Authorization": f"Bearer {self._token}"}, params=params, timeout=10
            )

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return response.json().get("data")

    @staticmethod
    def _append_best(
        now_playing: NowPlaying, artworks: list, artwork_type: Optional[int], label: str
    ) -> None:
        if artwork_type is None:
            return

        candidates = [a for a in artworks if a.get("type") == artwork_type]
        if not candidates:
            return

        best = max(candidates, key=lambda entry: entry.get("score") or 0)
        url = best.get("image")
        if url and not any(image.url == url for image in now_playing.images):
            now_playing.images.append(Artwork(url=url, label=label))

"""Tests for per-output source routing (docs/per-output-routing.md):
outputs whose filters accept different content bind to different
simultaneously-active sources, instead of one global winner.
"""

from unittest.mock import MagicMock

from mediainfo.models import Artwork, NowPlaying
from mediainfo.orchestrator import Orchestrator


class _Source:
    """Returns whatever `item` currently is (set to None for idle)."""

    def __init__(self, name, item=None):
        self.name = name
        self.item = item

    def get_now_playing(self):
        return self.item


class _FilterConfig:
    def __init__(
        self,
        allow_media_types=None,
        deny_media_types=None,
        allow_sources=None,
        deny_sources=None,
        active_hours="",
        idle_when_filtered=False,
    ):
        self.allow_media_types = allow_media_types or []
        self.deny_media_types = deny_media_types or []
        self.allow_sources = allow_sources or []
        self.deny_sources = deny_sources or []
        self.active_hours = active_hours
        self.idle_when_filtered = idle_when_filtered


def _output(config=None):
    output = MagicMock()
    output.config = config if config is not None else _FilterConfig()
    output.handles_images = True
    output.music_album_art_only = False
    output.transform_pipeline = []
    return output


def _movie(source="kodi", title="Inception"):
    return NowPlaying(
        source=source, media_type="movie", title=title,
        images=[Artwork(url=f"http://example.com/{source}-{title}.jpg")],
    )


def _music(source="sonos", title="Song"):
    return NowPlaying(
        source=source, media_type="music", title=title,
        images=[Artwork(url=f"http://example.com/{source}-{title}.jpg")],
    )


def _orchestrator(sources, outputs, enrichers=None, idle_source=None, grace=0):
    return Orchestrator(
        sources=sources,
        enrichers=enrichers or [],
        outputs=outputs,
        cache=MagicMock(),
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
        idle_source=idle_source,
        nothing_playing_grace_seconds=grace,
    )


def _shown_items(output):
    """The distinct NowPlaying items pushed to an output via update()."""
    return [call.args[0] for call in output.update.call_args_list]


# ---------------------------------------------------------------------------
# Group construction
# ---------------------------------------------------------------------------

def test_outputs_without_filters_share_one_group():
    orch = _orchestrator([_Source("kodi")], [_output(), _output()])
    assert len(orch._groups) == 1
    assert orch._groups[0].output_indices == [0, 1]


def test_outputs_split_by_content_rules():
    orch = _orchestrator(
        [_Source("kodi")],
        [_output(), _output(_FilterConfig(allow_sources=["sonos"])), _output()],
    )
    assert len(orch._groups) == 2
    assert sorted(len(g.output_indices) for g in orch._groups) == [1, 2]


def test_rule_order_does_not_split_groups():
    a = _output(_FilterConfig(allow_sources=["sonos", "kodi"]))
    b = _output(_FilterConfig(allow_sources=["kodi", "sonos"]))
    orch = _orchestrator([_Source("kodi")], [a, b])
    assert len(orch._groups) == 1


def test_active_hours_does_not_split_groups():
    # active_hours gates display, not routing - an output that differs
    # only by active_hours shares its group (and its item).
    a = _output(_FilterConfig())
    b = _output(_FilterConfig(active_hours="00:00-23:59"))
    orch = _orchestrator([_Source("kodi")], [a, b])
    assert len(orch._groups) == 1


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

def test_outputs_bind_to_different_sources_simultaneously():
    movie = _movie(source="kodi")
    song = _music(source="sonos")
    everything = _output()
    sonos_only = _output(_FilterConfig(allow_sources=["sonos"]))
    orch = _orchestrator(
        [_Source("kodi", movie), _Source("sonos", song)],
        [everything, sonos_only],
    )

    orch._tick()

    everything.on_new_item.assert_called_once()
    assert everything.on_new_item.call_args.args[0].source == "kodi"
    sonos_only.on_new_item.assert_called_once()
    assert sonos_only.on_new_item.call_args.args[0].source == "sonos"


def test_media_type_filter_routes_past_higher_priority_source():
    movie = _movie(source="kodi")
    song = _music(source="sonos")
    music_only = _output(_FilterConfig(allow_media_types=["music"]))
    orch = _orchestrator(
        [_Source("kodi", movie), _Source("sonos", song)], [music_only]
    )

    orch._tick()

    music_only.on_new_item.assert_called_once()
    assert music_only.on_new_item.call_args.args[0].source == "sonos"


def test_group_with_no_acceptable_source_goes_idle():
    movie = _movie(source="kodi")
    sonos_only = _output(_FilterConfig(allow_sources=["sonos"]))
    orch = _orchestrator([_Source("kodi", movie)], [sonos_only])

    orch._tick()

    sonos_only.on_new_item.assert_not_called()
    sonos_only.on_idle.assert_called_once()


def test_group_keeps_item_when_another_source_starts():
    kodi = _Source("kodi", _movie(source="kodi"))
    sonos = _Source("sonos")
    everything = _output()
    sonos_only = _output(_FilterConfig(allow_sources=["sonos"]))
    orch = _orchestrator([kodi, sonos], [everything, sonos_only])

    orch._tick()
    sonos.item = _music(source="sonos")
    orch._tick()

    # The unfiltered group stays on the higher-priority kodi item; only
    # the sonos-only group picked up the new source.
    everything.on_new_item.assert_called_once()
    assert everything.on_new_item.call_args.args[0].source == "kodi"
    sonos_only.on_new_item.assert_called_once()
    assert sonos_only.on_new_item.call_args.args[0].source == "sonos"


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------

def test_shared_item_is_enriched_once():
    movie = _movie(source="kodi")
    enricher = MagicMock()
    everything = _output()
    kodi_only = _output(_FilterConfig(allow_sources=["kodi"]))
    orch = _orchestrator(
        [_Source("kodi", movie)], [everything, kodi_only], enrichers=[enricher]
    )
    assert len(orch._groups) == 2  # both groups pick the same kodi item

    orch._tick()

    enricher.enrich.assert_called_once()


def test_group_joining_running_item_reuses_enrichment():
    kodi = _Source("kodi", _movie(source="kodi"))
    sonos = _Source("sonos", _music(source="sonos"))
    enricher = MagicMock()
    everything = _output()
    no_music = _output(_FilterConfig(deny_media_types=["music"]))
    orch = _orchestrator([sonos, kodi], [everything, no_music], enrichers=[enricher])

    orch._tick()  # everything->sonos, no_music->kodi: 2 enrichments
    assert enricher.enrich.call_count == 2

    sonos.item = None
    orch._tick()  # everything falls through to kodi - already enriched

    assert enricher.enrich.call_count == 2
    assert everything.on_new_item.call_args.args[0].source == "kodi"


def test_distinct_items_are_each_enriched():
    enricher = MagicMock()
    orch = _orchestrator(
        [_Source("kodi", _movie()), _Source("sonos", _music())],
        [_output(), _output(_FilterConfig(allow_sources=["sonos"]))],
        enrichers=[enricher],
    )

    orch._tick()

    assert enricher.enrich.call_count == 2


# ---------------------------------------------------------------------------
# Grace period is per group
# ---------------------------------------------------------------------------

def test_source_blip_does_not_affect_other_group():
    kodi = _Source("kodi", _movie(source="kodi"))
    sonos = _Source("sonos", _music(source="sonos"))
    everything = _output()
    sonos_only = _output(_FilterConfig(allow_sources=["sonos"]))
    # Default-length grace so a single missed poll is tolerated.
    orch = _orchestrator([kodi, sonos], [everything, sonos_only], grace=2)

    orch._tick()
    sonos.item = None  # one-poll blip
    orch._tick()

    # Within the grace window: sonos_only keeps its display untouched,
    # and the kodi group never notices.
    sonos_only.on_idle.assert_not_called()
    assert all(item.source != "idle" for item in _shown_items(sonos_only))
    everything.on_idle.assert_not_called()


# ---------------------------------------------------------------------------
# Idle wallpapers are scoped to idle groups
# ---------------------------------------------------------------------------

class _FakeIdleSource:
    def __init__(self, artworks, rotation_interval_seconds=0):
        self.artworks = list(artworks)
        self.rotation_interval_seconds = rotation_interval_seconds

    def get_wallpapers(self):
        return list(self.artworks)


def _wallpapers():
    return [Artwork(url="http://example.com/wall1.jpg"),
            Artwork(url="http://example.com/wall2.jpg")]


def test_idle_wallpapers_go_only_to_idle_group():
    movie = _movie(source="kodi")
    everything = _output()
    sonos_only = _output(_FilterConfig(allow_sources=["sonos"]))
    orch = _orchestrator(
        [_Source("kodi", movie)],
        [everything, sonos_only],
        idle_source=_FakeIdleSource(_wallpapers()),
    )

    orch._tick()

    # The playing group's output never sees the idle batch...
    assert all(item.source == "kodi" for item in _shown_items(everything))
    everything.on_new_item.assert_called_once()
    # ...while the idle group's output shows wallpapers.
    assert any(item.source == "idle" for item in _shown_items(sonos_only))


def test_output_rejoining_idle_gets_wallpaper_without_waiting():
    sonos = _Source("sonos", _music(source="sonos"))
    sonos_only = _output(_FilterConfig(allow_sources=["sonos"]))
    everything = _output()
    orch = _orchestrator(
        [_Source("kodi", _movie()), sonos],
        [everything, sonos_only],
        idle_source=_FakeIdleSource(_wallpapers()),
    )

    orch._tick()
    sonos.item = None  # grace=0: sonos_only goes idle immediately
    orch._tick()

    # rotation_interval_seconds is 30 and no time has passed, but the
    # rejoining output must not sit on the dead item until then.
    assert _shown_items(sonos_only)[-1].source == "idle"


def test_output_joining_existing_batch_is_pushed_via_rotate():
    # Unlike the refetch-every-tick fake above, a long refetch interval
    # forces the mid-batch join to go through rotate()'s immediate-push
    # path rather than a fresh _push_current_batch. The joining output
    # must be kodi-only: an unfiltered one would just fall through to the
    # still-playing sonos source instead of ever going idle.
    kodi = _Source("kodi", _movie(source="kodi"))
    kodi_only = _output(_FilterConfig(allow_sources=["kodi"]))
    sonos_only = _output(_FilterConfig(allow_sources=["sonos"]))
    orch = _orchestrator(
        [kodi, _Source("sonos", _music(source="sonos"))],
        [kodi_only, sonos_only],
        idle_source=_FakeIdleSource(_wallpapers(), rotation_interval_seconds=3600),
    )

    orch._tick()  # both groups bound; no batch yet
    kodi.item = None
    orch._tick()  # kodi_only's group goes idle: batch fetched, pushed to it
    assert _shown_items(kodi_only)[-1].source == "idle"

    kodi.item = _movie(source="kodi", title="Tenet")
    orch._tick()  # bound again
    assert _shown_items(kodi_only)[-1].source == "kodi"
    kodi.item = None
    orch._tick()  # rejoins the *existing* batch (no refetch for 3600s)

    assert _shown_items(kodi_only)[-1].source == "idle"
    # The sonos group's output never saw the idle batch at any point.
    assert all(item.source == "sonos" for item in _shown_items(sonos_only))


def test_idle_batch_survives_until_every_group_plays():
    kodi = _Source("kodi")
    sonos = _Source("sonos")
    everything = _output()
    sonos_only = _output(_FilterConfig(allow_sources=["sonos"]))
    orch = _orchestrator(
        [kodi, sonos],
        [everything, sonos_only],
        idle_source=_FakeIdleSource(_wallpapers()),
    )

    orch._tick()  # both groups idle - batch fetched
    assert orch._idle.images

    kodi.item = _movie(source="kodi")
    orch._tick()  # sonos_only still idle - batch must survive
    assert orch._idle.images

    sonos.item = _music(source="sonos")
    orch._tick()  # everyone playing with artwork - now it clears
    assert not orch._idle.images


# ---------------------------------------------------------------------------
# Hitster-safe with routing
# ---------------------------------------------------------------------------

def test_hitster_safe_suppresses_music_but_not_lower_priority_movie():
    orch = _orchestrator(
        [_Source("spotify", _music(source="spotify")),
         _Source("kodi", _movie(source="kodi"))],
        [_output()],
    )
    orch.set_hitster_safe(True)

    orch._tick()

    output = orch.outputs[0]
    output.on_new_item.assert_called_once()
    assert output.on_new_item.call_args.args[0].source == "kodi"

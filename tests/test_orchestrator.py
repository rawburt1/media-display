"""Tests for Orchestrator idle wallpaper handling."""

import time
from unittest.mock import MagicMock, patch

import pytest

from mediainfo.cache import ImageCache
from mediainfo.models import Artwork, NowPlaying
from mediainfo.orchestrator import _DEFAULT_NOTHING_PLAYING_GRACE_SECONDS, Orchestrator


class _FakeSource:
    name = "fake"

    def get_now_playing(self):
        return None


class _StaticSource:
    """Always returns the same now-playing item."""
    name = "static"

    def __init__(self, item):
        self._item = item

    def get_now_playing(self):
        return self._item


class _FailingSource:
    """Simulates a device that can't be reached - sets last_poll_failed.
    Set `.fail = False` to simulate the device becoming reachable again.
    """
    name = "failing"

    def __init__(self):
        self.calls = 0
        self.fail = True
        self.last_poll_failed = False

    def get_now_playing(self):
        self.calls += 1
        self.last_poll_failed = self.fail
        return None


class _FakeClock:
    """Controllable stand-in for time.monotonic()."""

    def __init__(self, start=1000.0):
        self.now = start

    def __call__(self):
        return self.now


def _fake_shuffle(orders):
    """Returns a random.shuffle replacement that yields each of `orders` in
    turn (in place), one per call."""

    iterator = iter(orders)

    def shuffle(items):
        items[:] = next(iterator)

    return shuffle


class _FakeIdleSource:
    def __init__(self, artworks, rotation_interval_seconds=0):
        self.artworks = list(artworks)
        self.rotation_interval_seconds = rotation_interval_seconds
        self.calls = 0

    def get_wallpapers(self):
        self.calls += 1
        return list(self.artworks)


def _orchestrator(outputs, cache, idle_source=None):
    return Orchestrator(
        sources=[_FakeSource()],
        enrichers=[],
        outputs=outputs,
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
        idle_source=idle_source,
    )


def test_no_idle_source_calls_on_idle():
    output = MagicMock()
    orchestrator = _orchestrator(outputs=[output], cache=MagicMock())

    orchestrator._tick()

    output.on_idle.assert_called_once()
    output.update.assert_not_called()


# ---------------------------------------------------------------------------
# Nothing-playing grace period (tolerate a flaky source's brief gap)
# ---------------------------------------------------------------------------

def test_brief_gap_while_playing_does_not_trigger_idle():
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Inception", images=[
        Artwork(url="https://example.com/poster.jpg", label="Poster"),
    ])

    class _FlakySource:
        name = "flaky"

        def __init__(self):
            self.calls = 0

        def get_now_playing(self):
            self.calls += 1
            # Plays, then a single missed poll, then resumes.
            return None if self.calls == 2 else now_playing

    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/poster.jpg"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = Orchestrator(
        sources=[_FlakySource()],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )

    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock):
        orchestrator._tick()  # playing
        orchestrator._tick()  # one missed poll, within grace period
        orchestrator._tick()  # resumes before grace period elapses

    output.on_idle.assert_not_called()
    assert orchestrator._current is not None
    assert orchestrator._current.title == "Inception"


def test_gap_longer_than_grace_period_still_goes_idle():
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Inception", images=[
        Artwork(url="https://example.com/poster.jpg", label="Poster"),
    ])

    class _StoppedSource:
        name = "stopped"

        def __init__(self):
            self.calls = 0

        def get_now_playing(self):
            self.calls += 1
            return now_playing if self.calls == 1 else None

    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/poster.jpg"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = Orchestrator(
        sources=[_StoppedSource()],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )

    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock):
        orchestrator._tick()  # playing
        orchestrator._tick()  # nothing playing: grace period starts
        output.on_idle.assert_not_called()

        clock.now += _DEFAULT_NOTHING_PLAYING_GRACE_SECONDS + 1
        orchestrator._tick()  # grace period elapsed: now truly idle

    output.on_idle.assert_called_once()
    assert orchestrator._current is None


def test_idle_source_shows_wallpaper():
    output = MagicMock()
    cache = MagicMock()
    cache.download_temp.return_value = "/tmp/wallpaper.jpg"
    cache.get_transformed_path.side_effect = lambda path, _: path
    artwork = Artwork(url="https://i.redd.it/abc.jpg", label="r/wallpapers: Test")
    idle_source = _FakeIdleSource([artwork])

    orchestrator = _orchestrator(outputs=[output], cache=cache, idle_source=idle_source)
    orchestrator._tick()

    output.update.assert_called_once()
    _, used_artwork, image_path = output.update.call_args[0]
    assert used_artwork is artwork
    assert image_path == "/tmp/wallpaper.jpg"
    output.on_idle.assert_not_called()


def test_idle_wallpaper_does_not_refetch_before_interval():
    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/wallpaper.jpg"
    idle_source = _FakeIdleSource(
        [Artwork(url="https://i.redd.it/a.jpg"), Artwork(url="https://i.redd.it/b.jpg")],
        rotation_interval_seconds=1000,
    )

    orchestrator = _orchestrator(outputs=[output], cache=cache, idle_source=idle_source)
    orchestrator._tick()
    orchestrator._tick()

    assert idle_source.calls == 1
    assert output.update.call_count == 1


def test_no_wallpaper_available_calls_on_idle():
    output = MagicMock()
    cache = MagicMock()
    idle_source = _FakeIdleSource([])

    orchestrator = _orchestrator(outputs=[output], cache=cache, idle_source=idle_source)
    orchestrator._tick()

    output.on_idle.assert_called_once()
    output.update.assert_not_called()


def test_non_image_output_gets_on_idle_even_with_idle_source():
    # Outputs with handles_images=False (e.g. Ulanzi, VideoOutput) should
    # always receive on_idle() when truly idle, even if an idle image source
    # is configured (so they can clear text / start video).
    output = MagicMock()
    output.handles_images = False
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/wallpaper.jpg"
    artwork = Artwork(url="https://i.redd.it/abc.jpg", label="Wallpaper")
    idle_source = _FakeIdleSource([artwork])

    orchestrator = _orchestrator(outputs=[output], cache=cache, idle_source=idle_source)
    orchestrator._tick()

    output.on_idle.assert_called_once()
    # Wallpaper images are not routed to non-image outputs.
    output.update.assert_not_called()


def test_non_image_output_does_not_get_on_idle_when_playing_without_artwork():
    # When playing a no-artwork item, non-image outputs keep their last display
    # (text stays on Ulanzi, video keeps running on VideoOutput).
    idle_source = _FakeIdleSource(_idle_wallpapers(count=1), rotation_interval_seconds=300)
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Inception", images=[])

    class _TogglingSource:
        name = "toggling"

        def __init__(self):
            self.calls = 0

        def get_now_playing(self):
            self.calls += 1
            return now_playing if self.calls == 1 else None

    output = MagicMock()
    output.handles_images = False
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/wallpaper.jpg"

    orchestrator = Orchestrator(
        sources=[_TogglingSource()],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
        idle_source=idle_source,
    )

    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock):
        orchestrator._tick()  # playing without artwork: on_idle must NOT be called
        output.on_idle.assert_not_called()

        orchestrator._tick()  # source goes quiet, but within the grace period
        output.on_idle.assert_not_called()

        clock.now += _DEFAULT_NOTHING_PLAYING_GRACE_SECONDS + 1
        orchestrator._tick()  # grace period elapsed: now truly idle
        output.on_idle.assert_called_once()


def _idle_wallpapers(count=3):
    return [
        Artwork(url=f"https://example.com/{i}.jpg", label=f"Wallpaper {i}") for i in range(count)
    ]


def test_idle_batch_each_output_starts_on_a_different_picture():
    # Outputs share one shuffled order but start at different positions in
    # it, so - as long as there are at least as many images as outputs -
    # they never start on the same picture (previously each output shuffled
    # independently, which could coincidentally collide).
    idle_source = _FakeIdleSource(_idle_wallpapers(), rotation_interval_seconds=300)
    output_a = MagicMock()
    output_b = MagicMock()
    cache = MagicMock()
    cache.download_temp.side_effect = lambda artwork: f"/cache/{artwork.label}"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = _orchestrator(outputs=[output_a, output_b], cache=cache, idle_source=idle_source)

    with patch(
        "mediainfo.orchestrator.random.shuffle",
        side_effect=_fake_shuffle([[2, 0, 1]]),
    ):
        orchestrator._tick()

    _, artwork_a, path_a = output_a.update.call_args[0]
    _, artwork_b, path_b = output_b.update.call_args[0]
    assert artwork_a.label == "Wallpaper 2"  # shared order [2, 0, 1], position 0
    assert path_a == "/cache/Wallpaper 2"
    assert artwork_b.label == "Wallpaper 0"  # shared order [2, 0, 1], position 1
    assert path_b == "/cache/Wallpaper 0"
    assert artwork_a.label != artwork_b.label
    assert idle_source.calls == 1


def test_idle_batch_falls_through_pool_when_first_pick_fails_to_fetch():
    idle_source = _FakeIdleSource(_idle_wallpapers(), rotation_interval_seconds=300)
    output = MagicMock()
    cache = MagicMock()

    def download_temp(artwork):
        if artwork.label == "Wallpaper 2":
            return None  # rejected
        return f"/cache/{artwork.label}"

    cache.download_temp.side_effect = download_temp
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = _orchestrator(outputs=[output], cache=cache, idle_source=idle_source)

    with patch(
        "mediainfo.orchestrator.random.shuffle",
        side_effect=_fake_shuffle([[2, 0, 1]]),
    ):
        orchestrator._tick()

    _, artwork, path = output.update.call_args[0]
    assert artwork.label == "Wallpaper 0"  # skipped the rejected "Wallpaper 2"
    assert path == "/cache/Wallpaper 0"


def test_single_wallpaper_retries_output_that_previously_failed():
    idle_source = _FakeIdleSource(_idle_wallpapers(count=1), rotation_interval_seconds=300)
    output = MagicMock()
    output.update.side_effect = [RuntimeError("device unreachable"), None]
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/wallpaper.jpg"

    orchestrator = Orchestrator(
        sources=[_FakeSource()],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=0,
        idle_source=idle_source,
    )

    orchestrator._tick()  # initial idle push fails
    assert 0 in orchestrator.get_health()["output_errors"]

    orchestrator._tick()  # retried on the next rotation check and succeeds

    assert output.update.call_count == 2
    assert 0 not in orchestrator.get_health()["output_errors"]


def test_idle_batch_no_two_outputs_share_a_picture_when_enough_images():
    # Real (unmocked) shuffle - with >= as many images as outputs, no two
    # outputs should ever start on the same picture.
    idle_source = _FakeIdleSource(_idle_wallpapers(count=10), rotation_interval_seconds=300)
    outputs = [MagicMock() for _ in range(4)]
    cache = MagicMock()
    cache.get_path.side_effect = lambda artwork, **kwargs: f"/cache/{artwork.label}"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = _orchestrator(outputs=outputs, cache=cache, idle_source=idle_source)
    orchestrator._tick()

    labels = [o.update.call_args[0][1].label for o in outputs]
    assert len(set(labels)) == len(outputs)


def test_idle_wallpaper_displayed_without_caching_to_disk():
    # Idle images are downloaded to a temp file and never written to the
    # persistent cache directory - download_temp is used instead of get_path.
    idle_source = _FakeIdleSource(_idle_wallpapers(), rotation_interval_seconds=300)
    output = MagicMock()
    cache = MagicMock()
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = _orchestrator(outputs=[output], cache=cache, idle_source=idle_source)
    orchestrator._tick()

    cache.download_temp.assert_called_once()
    cache.get_path.assert_not_called()


def test_idle_rotation_state_staggers_initial_last_rotation_per_output():
    # Without staggering, every output's last_rotation is set to the exact
    # same instant, so they all become "due" to advance in lockstep forever
    # - this is what made independently-shuffled outputs look synchronized
    # (they all flip to a new image at the same moment).
    idle_source = _FakeIdleSource(_idle_wallpapers(), rotation_interval_seconds=300)
    output_a = MagicMock()
    output_b = MagicMock()
    cache = MagicMock()
    cache.get_path.side_effect = lambda artwork, **kwargs: f"/cache/{artwork.label}"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = _orchestrator(outputs=[output_a, output_b], cache=cache, idle_source=idle_source)

    with patch("mediainfo.orchestrator.random.uniform", side_effect=[5.0, 12.0]):
        orchestrator._tick()

    assert orchestrator._idle.rotation_state[0].last_rotation != orchestrator._idle.rotation_state[1].last_rotation
    diff = orchestrator._idle.rotation_state[1].last_rotation - orchestrator._idle.rotation_state[0].last_rotation
    assert diff == pytest.approx(5.0 - 12.0, abs=0.01)


def test_rotation_state_staggers_initial_last_rotation_per_output():
    now_playing = _multi_image_now_playing()
    output_a = MagicMock()
    output_b = MagicMock()
    cache = MagicMock()
    cache.get_path.side_effect = lambda artwork, **kwargs: f"/cache/{artwork.label}"

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output_a, output_b],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=10,
    )

    with patch("mediainfo.orchestrator.random.uniform", side_effect=[2.0, 8.0]):
        orchestrator._tick()

    assert orchestrator._rotation_state[0].last_rotation != orchestrator._rotation_state[1].last_rotation


def test_idle_rotation_advances_each_output_independently():
    idle_source = _FakeIdleSource(_idle_wallpapers(), rotation_interval_seconds=300)
    output_a = MagicMock()
    output_b = MagicMock()
    cache = MagicMock()
    cache.get_path.side_effect = lambda artwork, **kwargs: f"/cache/{artwork.label}"

    orchestrator = Orchestrator(
        sources=[_FakeSource()],
        enrichers=[],
        outputs=[output_a, output_b],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=10,
        idle_source=idle_source,
    )

    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock), patch(
        "mediainfo.orchestrator.random.shuffle",
        side_effect=_fake_shuffle([[0, 1, 2]]),
    ):
        orchestrator._tick()  # initial batch: order [0,1,2] -> a="Wallpaper 0", b="Wallpaper 1"

        output_a.update.reset_mock()
        output_b.update.reset_mock()

        clock.now += 100  # past rotation_interval_seconds, but not the batch refresh interval
        orchestrator._tick()

    _, artwork_a, _ = output_a.update.call_args[0]
    _, artwork_b, _ = output_b.update.call_args[0]
    assert artwork_a.label == "Wallpaper 1"  # position 0 -> 1
    assert artwork_b.label == "Wallpaper 2"  # position 1 -> 2
    assert idle_source.calls == 1


def test_idle_batch_refetched_after_interval():
    idle_source = _FakeIdleSource(_idle_wallpapers(count=1), rotation_interval_seconds=300)
    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/wallpaper.jpg"

    orchestrator = _orchestrator(outputs=[output], cache=cache, idle_source=idle_source)

    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock):
        orchestrator._tick()
        clock.now += 301
        orchestrator._tick()

    assert idle_source.calls == 2


def test_idle_batch_not_cleared_when_playing_without_artwork():
    # When a no-artwork item plays, idle wallpapers keep showing uninterrupted.
    # The existing batch is not discarded, so no extra fetch happens on return
    # to idle within the normal interval.
    idle_source = _FakeIdleSource(_idle_wallpapers(count=1), rotation_interval_seconds=300)
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Inception", images=[])

    class _TogglingSource:
        name = "toggling2"

        def __init__(self):
            self.calls = 0

        def get_now_playing(self):
            self.calls += 1
            return now_playing if self.calls == 2 else None

    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/wallpaper.jpg"

    orchestrator = Orchestrator(
        sources=[_TogglingSource()],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
        idle_source=idle_source,
    )

    orchestrator._tick()  # idle: fetch batch #1
    orchestrator._tick()  # no-artwork item plays; idle batch kept, wallpapers continue
    orchestrator._tick()  # back to idle: still within interval, no new fetch

    assert idle_source.calls == 1


def test_purges_expired_cache_once_then_waits_for_interval():
    cache = MagicMock()
    orchestrator = _orchestrator(outputs=[MagicMock()], cache=cache)

    orchestrator._tick()
    orchestrator._tick()

    cache.purge_expired.assert_called_once()


def test_new_item_calls_on_new_item_with_full_image_list():
    artwork = Artwork(url="https://example.com/poster.jpg", label="Poster")
    now_playing = NowPlaying(
        source="kodi", media_type="movie", title="Inception", images=[artwork]
    )

    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/poster.jpg"

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )
    orchestrator._tick()

    output.on_new_item.assert_called_once_with(now_playing, cache)


# ---------------------------------------------------------------------------
# Manual artwork overrides
# ---------------------------------------------------------------------------

def test_override_replaces_enriched_images():
    from mediainfo.artwork_overrides import ArtworkOverrideStore

    enriched = Artwork(url="https://example.com/enriched.jpg", label="Enriched")
    now_playing = NowPlaying(
        source="kodi", media_type="movie", title="Inception", images=[enriched]
    )

    overrides = MagicMock(spec=ArtworkOverrideStore)
    override_art = Artwork(url="file:///overrides/abc.jpg", label="Manual override")
    overrides.get.return_value = override_art

    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/overrides/abc.jpg"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
        overrides=overrides,
    )
    orchestrator._tick()

    overrides.get.assert_called_once_with("Inception", "")
    assert now_playing.images == [override_art]
    _, artwork, _ = output.update.call_args[0]
    assert artwork.label == "Manual override"


def test_no_override_match_leaves_enriched_images_untouched():
    from mediainfo.artwork_overrides import ArtworkOverrideStore

    enriched = Artwork(url="https://example.com/enriched.jpg", label="Enriched")
    now_playing = NowPlaying(
        source="kodi", media_type="movie", title="Inception", images=[enriched]
    )

    overrides = MagicMock(spec=ArtworkOverrideStore)
    overrides.get.return_value = None

    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/cache/enriched.jpg"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
        overrides=overrides,
    )
    orchestrator._tick()

    assert now_playing.images == [enriched]


def test_no_overrides_store_is_a_no_op():
    artwork = Artwork(url="https://example.com/poster.jpg", label="Poster")
    now_playing = NowPlaying(
        source="kodi", media_type="movie", title="Inception", images=[artwork]
    )

    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/cache/poster.jpg"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )  # overrides=None (default)
    orchestrator._tick()  # must not raise

    assert now_playing.images == [artwork]


def test_override_lookup_error_is_caught_and_does_not_block_display():
    from mediainfo.artwork_overrides import ArtworkOverrideStore

    artwork = Artwork(url="https://example.com/poster.jpg", label="Poster")
    now_playing = NowPlaying(
        source="kodi", media_type="movie", title="Inception", images=[artwork]
    )

    overrides = MagicMock(spec=ArtworkOverrideStore)
    overrides.get.side_effect = RuntimeError("disk error")

    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/cache/poster.jpg"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
        overrides=overrides,
    )
    orchestrator._tick()  # must not raise

    assert now_playing.images == [artwork]  # enriched images preserved on error


# ---------------------------------------------------------------------------
# Playback position refresh
# ---------------------------------------------------------------------------

def test_position_refreshes_on_same_item_ticks():
    artwork = Artwork(url="https://example.com/poster.jpg", label="Poster")

    class _AdvancingSource:
        name = "kodi"

        def __init__(self):
            self.position = 10.0

        def get_now_playing(self):
            self.position += 5.0
            return NowPlaying(
                source="kodi", media_type="music", title="Money", subtitle="Pink Floyd",
                images=[artwork], position_seconds=self.position, duration_seconds=383.0,
            )

    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/cache/poster.jpg"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = Orchestrator(
        sources=[_AdvancingSource()],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )

    orchestrator._tick()  # new item: position_seconds == 15.0
    assert orchestrator._current.position_seconds == 15.0

    orchestrator._tick()  # same item: position_seconds refreshed to 20.0
    assert orchestrator._current.position_seconds == 20.0

    orchestrator._tick()  # same item again: refreshed to 25.0
    assert orchestrator._current.position_seconds == 25.0


def test_music_artwork_is_fetched_as_permanent():
    artwork = Artwork(url="https://example.com/cover.jpg", label="Cover")
    now_playing = NowPlaying(
        source="spotify", media_type="music", title="Song", subtitle="Artist", images=[artwork]
    )

    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/cover.jpg"

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )
    orchestrator._tick()

    cache.get_path.assert_called_once_with(artwork, tier="music")


def test_movie_artwork_is_not_fetched_as_permanent():
    artwork = Artwork(url="https://example.com/poster.jpg", label="Poster")
    now_playing = NowPlaying(
        source="kodi", media_type="movie", title="Inception", images=[artwork]
    )

    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/poster.jpg"

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )
    orchestrator._tick()

    cache.get_path.assert_called_once_with(artwork, tier="default")


def _tick_with_now_playing(now_playing):
    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/art.jpg" if now_playing.images else None

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )
    orchestrator._tick()
    return orchestrator


def test_strips_parenthetical_from_music_title():
    now_playing = NowPlaying(source="kodi", media_type="music", title="Money (Live)")

    orchestrator = _tick_with_now_playing(now_playing)

    assert orchestrator._current.title == "Money"


def test_strips_multiple_parenthetical_groups_from_music_title():
    now_playing = NowPlaying(
        source="kodi", media_type="music", title="Imagine (Remastered 2010) (Mono Mix)"
    )

    orchestrator = _tick_with_now_playing(now_playing)

    assert orchestrator._current.title == "Imagine"


def test_does_not_strip_parenthetical_from_movie_title():
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Alien (1979)")

    orchestrator = _tick_with_now_playing(now_playing)

    assert orchestrator._current.title == "Alien (1979)"


def test_music_title_without_parenthetical_is_unchanged():
    now_playing = NowPlaying(source="kodi", media_type="music", title="Hey Jude")

    orchestrator = _tick_with_now_playing(now_playing)

    assert orchestrator._current.title == "Hey Jude"


def test_does_not_strip_leading_parenthetical_that_is_part_of_the_real_title():
    now_playing = NowPlaying(
        source="kodi", media_type="music", title="(I Can't Get No) Satisfaction"
    )

    orchestrator = _tick_with_now_playing(now_playing)

    assert orchestrator._current.title == "(I Can't Get No) Satisfaction"


def test_does_not_strip_mid_title_parenthetical_followed_by_more_text():
    now_playing = NowPlaying(source="kodi", media_type="music", title="Money (Live) - Edit")

    orchestrator = _tick_with_now_playing(now_playing)

    assert orchestrator._current.title == "Money (Live) - Edit"


def _multi_image_now_playing():
    artworks = [Artwork(url=f"https://example.com/{i}.jpg", label=f"Image {i}") for i in range(3)]
    return NowPlaying(source="kodi", media_type="movie", title="Inception", images=artworks)


def test_each_output_starts_on_a_different_picture():
    # Outputs share one shuffled order but start at different positions in
    # it, so they never start on the same picture (as long as there are at
    # least as many images as outputs).
    now_playing = _multi_image_now_playing()
    output_a = MagicMock()
    output_b = MagicMock()
    cache = MagicMock()
    cache.get_path.side_effect = lambda artwork, **kwargs: f"/cache/{artwork.label}"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output_a, output_b],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )

    with patch(
        "mediainfo.orchestrator.random.shuffle",
        side_effect=_fake_shuffle([[2, 0, 1]]),
    ):
        orchestrator._tick()

    _, artwork_a, path_a = output_a.update.call_args[0]
    _, artwork_b, path_b = output_b.update.call_args[0]
    assert artwork_a.label == "Image 2"  # shared order [2, 0, 1], position 0
    assert path_a == "/cache/Image 2"
    assert artwork_b.label == "Image 0"  # shared order [2, 0, 1], position 1
    assert path_b == "/cache/Image 0"
    assert artwork_a.label != artwork_b.label


def test_falls_through_pool_when_first_pick_fails_to_fetch():
    # An output's rotation position can land on an image the cache rejects
    # (e.g. below the minimum size) or fails to download - it should fall
    # through to the next image in its rotation order rather than showing
    # nothing until the next scheduled rotation.
    now_playing = _multi_image_now_playing()
    output = MagicMock()
    cache = MagicMock()

    def get_path(artwork, **kwargs):
        if artwork.label == "Image 2":
            return None  # rejected
        return f"/cache/{artwork.label}"

    cache.get_path.side_effect = get_path
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )

    with patch(
        "mediainfo.orchestrator.random.shuffle",
        side_effect=_fake_shuffle([[2, 0, 1]]),
    ):
        orchestrator._tick()

    _, artwork, path = output.update.call_args[0]
    assert artwork.label == "Image 0"  # skipped the rejected "Image 2"
    assert path == "/cache/Image 0"


def test_logs_warning_when_every_candidate_fails_to_fetch():
    now_playing = _multi_image_now_playing()
    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = None  # every candidate rejected

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )

    orchestrator._tick()

    output.update.assert_not_called()


def test_rotation_advances_each_output_independently():
    now_playing = _multi_image_now_playing()
    output_a = MagicMock()
    output_b = MagicMock()
    cache = MagicMock()
    cache.get_path.side_effect = lambda artwork, **kwargs: f"/cache/{artwork.label}"

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output_a, output_b],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=10,
    )

    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock), patch(
        "mediainfo.orchestrator.random.shuffle",
        side_effect=_fake_shuffle([[0, 1, 2]]),
    ):
        orchestrator._tick()  # initial image: order [0,1,2] -> a="Image 0", b="Image 1"

        output_a.update.reset_mock()
        output_b.update.reset_mock()

        clock.now += 100  # past rotation_interval_seconds
        orchestrator._tick()

    _, artwork_a, _ = output_a.update.call_args[0]
    _, artwork_b, _ = output_b.update.call_args[0]
    assert artwork_a.label == "Image 1"  # position 0 -> 1
    assert artwork_b.label == "Image 2"  # position 1 -> 2


def test_single_image_does_not_advance_but_still_repushes():
    # A single-image item has nothing to rotate *to* - but it must still
    # be periodically re-pushed (the same artwork each time) rather than
    # skipped outright, so a transient push failure to a physical output
    # (e.g. a Pixoo64 briefly unreachable) gets retried instead of leaving
    # that output frozen on stale content for as long as the item plays.
    artwork = Artwork(url="https://example.com/poster.jpg", label="Poster")
    now_playing = NowPlaying(
        source="kodi", media_type="movie", title="Inception", images=[artwork]
    )
    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/poster.jpg"

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=0,
    )

    orchestrator._tick()
    output.update.reset_mock()
    orchestrator._tick()

    output.update.assert_called_once()
    _, pushed_artwork, _ = output.update.call_args[0]
    assert pushed_artwork.label == "Poster"  # same artwork, not rotated to something else


def test_single_image_retries_output_that_previously_failed():
    artwork = Artwork(url="https://example.com/poster.jpg", label="Poster")
    now_playing = NowPlaying(
        source="kodi", media_type="movie", title="Inception", images=[artwork]
    )
    output = MagicMock()
    output.update.side_effect = [RuntimeError("device unreachable"), None]
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/poster.jpg"

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=0,
    )

    orchestrator._tick()  # initial push fails
    assert 0 in orchestrator.get_health()["output_errors"]

    orchestrator._tick()  # retried on the next rotation check and succeeds

    assert output.update.call_count == 2
    assert 0 not in orchestrator.get_health()["output_errors"]


# ---------------------------------------------------------------------------
# get_health()
# ---------------------------------------------------------------------------

def _health_orchestrator(sources=None, outputs=None, idle_source=None, alert_config=None):
    return Orchestrator(
        sources=sources or [_FakeSource()],
        enrichers=[],
        outputs=outputs or [MagicMock()],
        cache=MagicMock(),
        poll_interval_seconds=5,
        rotation_interval_seconds=30,
        idle_source=idle_source,
        alert_config=alert_config,
    )


def test_get_health_returns_dict():
    orch = _health_orchestrator()
    data = orch.get_health()
    assert isinstance(data, dict)
    assert "uptime_seconds" in data
    assert "poll_interval_seconds" in data


def test_get_health_uptime_increases():
    import time
    orch = _health_orchestrator()
    h1 = orch.get_health()
    time.sleep(0.05)
    h2 = orch.get_health()
    assert h2["uptime_seconds"] >= h1["uptime_seconds"]


def test_get_health_intervals_match_config():
    orch = _health_orchestrator()
    data = orch.get_health()
    assert data["poll_interval_seconds"] == 5
    assert data["rotation_interval_seconds"] == 30


def test_get_health_now_playing_none_when_idle():
    orch = _health_orchestrator()
    assert orch.get_health()["now_playing"] is None


def test_get_health_now_playing_after_tick():
    item = NowPlaying(source="kodi", media_type="music", title="Test", subtitle="Artist",
                      images=[Artwork(url="https://x.com/a.jpg")])
    orch = _health_orchestrator(sources=[_StaticSource(item)], outputs=[MagicMock()])
    orch._tick()
    np = orch.get_health()["now_playing"]
    assert np is not None
    assert np["title"] == "Test"
    assert np["source"] == "kodi"
    assert len(np["images"]) == 1


def test_get_health_active_source_set_after_tick():
    item = NowPlaying(source="kodi", media_type="music", title="Test", images=[])
    orch = _health_orchestrator(sources=[_StaticSource(item)], outputs=[MagicMock()])
    orch._tick()
    assert orch.get_health()["active_source"] == "static"


def test_get_health_active_source_none_when_idle():
    orch = _health_orchestrator()
    orch._tick()
    assert orch.get_health()["active_source"] is None


def test_get_health_source_polled_recorded():
    orch = _health_orchestrator()
    orch._tick()
    polled = orch.get_health()["source_last_polled_ago"]
    assert "fake" in polled
    assert polled["fake"] >= 0


def test_get_health_output_error_recorded():
    output = MagicMock()
    output.on_idle.side_effect = RuntimeError("gone")
    orch = _health_orchestrator(outputs=[output])
    orch._tick()  # calls on_idle → records error at index 0
    errors = orch.get_health()["output_errors"]
    assert 0 in errors
    assert "gone" in errors[0]["message"]


def test_get_health_output_error_cleared_on_success():
    calls = []

    class _FailThenSucceed:
        def on_idle(self):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("transient")
        def on_new_item(self, *a): pass
        def update(self, *a): pass
        handles_images = True
        transform_pipeline = []

    output = _FailThenSucceed()
    orch = _health_orchestrator(outputs=[output])
    orch._tick()  # first call raises → error recorded
    assert 0 in orch.get_health()["output_errors"]
    orch._tick()  # second call succeeds → error cleared
    assert 0 not in orch.get_health()["output_errors"]


# ---------------------------------------------------------------------------
# Alerting wiring (_maybe_check_alerts)
# ---------------------------------------------------------------------------

def test_alert_fires_after_threshold_via_tick():
    from mediainfo.config import AlertConfig

    output = MagicMock()
    output.on_idle.side_effect = RuntimeError("gone")
    alert_config = AlertConfig(
        enabled=True, webhook_url="https://example.com/hook",
        error_threshold_seconds=300, repeat_interval_seconds=3600,
    )
    orch = _health_orchestrator(outputs=[output], alert_config=alert_config)

    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock), patch(
        "mediainfo.alerting.requests.post"
    ) as mock_post:
        orch._tick()  # error starts; alert check runs but threshold not met
        mock_post.assert_not_called()

        clock.now += 301
        orch._tick()  # alert check interval elapsed and error streak past threshold

    mock_post.assert_called_once()


def test_alert_check_is_a_no_op_when_alerting_disabled():
    output = MagicMock()
    output.on_idle.side_effect = RuntimeError("gone")
    orch = _health_orchestrator(outputs=[output])  # alert_config=None -> disabled by default

    with patch("mediainfo.alerting.requests.post") as mock_post:
        orch._tick()

    mock_post.assert_not_called()


def test_get_health_idle_wallpapers_loaded():
    artwork = Artwork(url="https://example.com/wall.jpg", label="w")
    idle_source = _FakeIdleSource([artwork], rotation_interval_seconds=0)
    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/w.jpg"
    cache.get_transformed_path.side_effect = lambda p, _: p
    orch = Orchestrator(
        sources=[_FakeSource()],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
        idle_source=idle_source,
    )
    orch._tick()
    assert orch.get_health()["idle_wallpapers_loaded"] == 1


# ---------------------------------------------------------------------------
# Source backoff (MediaSource.last_poll_failed)
# ---------------------------------------------------------------------------

def _orchestrator_with_sources(sources, cache=None):
    return Orchestrator(
        sources=sources,
        enrichers=[],
        outputs=[MagicMock()],
        cache=cache or MagicMock(),
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )


def test_failed_poll_schedules_backoff():
    source = _FailingSource()
    orch = _orchestrator_with_sources([source])

    orch._poll_sources()

    assert "failing" in orch._health.source_backoff
    assert orch._health.source_backoff["failing"].delay > 0


def test_backed_off_source_is_skipped_until_next_attempt():
    source = _FailingSource()
    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock):
        orch = _orchestrator_with_sources([source])

        orch._poll_sources()
        assert source.calls == 1

        clock.now += 1  # well before the backoff delay elapses
        orch._poll_sources()
        assert source.calls == 1  # still skipped


def test_backed_off_source_is_retried_after_delay_elapses():
    source = _FailingSource()
    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock):
        orch = _orchestrator_with_sources([source])

        orch._poll_sources()
        delay = orch._health.source_backoff["failing"].delay

        clock.now += delay + 1
        orch._poll_sources()
        assert source.calls == 2


def test_backoff_delay_doubles_on_repeated_failures():
    source = _FailingSource()
    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock):
        orch = _orchestrator_with_sources([source])

        orch._poll_sources()
        first_delay = orch._health.source_backoff["failing"].delay

        clock.now += first_delay + 1
        orch._poll_sources()
        second_delay = orch._health.source_backoff["failing"].delay

        assert second_delay == first_delay * 2


def test_backoff_delay_caps_at_max():
    source = _FailingSource()
    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock):
        orch = _orchestrator_with_sources([source])

        for _ in range(15):
            orch._poll_sources()
            clock.now += orch._health.source_backoff["failing"].delay + 1

        assert orch._health.source_backoff["failing"].delay == orch.backoff_max_seconds


def test_custom_backoff_initial_and_max_seconds():
    source = _FailingSource()
    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock):
        orch = Orchestrator(
            sources=[source],
            enrichers=[],
            outputs=[MagicMock()],
            cache=MagicMock(),
            poll_interval_seconds=1,
            rotation_interval_seconds=30,
            backoff_initial_seconds=5,
            backoff_max_seconds=10,
        )

        orch._poll_sources()
        assert orch._health.source_backoff["failing"].delay == 5

        clock.now += 6
        orch._poll_sources()
        assert orch._health.source_backoff["failing"].delay == 10


def test_successful_poll_clears_backoff():
    source = _FailingSource()
    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock):
        orch = _orchestrator_with_sources([source])

        orch._poll_sources()
        delay = orch._health.source_backoff["failing"].delay
        clock.now += delay + 1

        source.fail = False  # device reachable again
        orch._poll_sources()

        assert "failing" not in orch._health.source_backoff


def test_idle_source_without_last_poll_failed_is_never_backed_off():
    # _FakeSource doesn't set last_poll_failed at all - getattr(..., False)
    # default must apply, not an AttributeError.
    source = _FakeSource()
    orch = _orchestrator_with_sources([source])

    orch._poll_sources()

    assert "fake" not in orch._health.source_backoff


def test_lower_priority_source_is_polled_when_higher_priority_is_backed_off():
    failing = _FailingSource()
    item = NowPlaying(source="static", media_type="music", title="Song", images=[])
    static = _StaticSource(item)
    orch = _orchestrator_with_sources([failing, static])

    result = orch._poll_sources()

    assert result == [item]


def test_backoff_does_not_affect_unrelated_source():
    failing = _FailingSource()
    item = NowPlaying(source="static", media_type="music", title="Song", images=[])
    static = _StaticSource(item)
    clock = _FakeClock()
    with patch("mediainfo.orchestrator.time.monotonic", clock):
        orch = _orchestrator_with_sources([failing, static])

        orch._poll_sources()
        clock.now += 1
        orch._poll_sources()

        # static source has no concept of backoff/calls tracking here, but
        # it must still be reachable (returns its item) on every tick.
        assert orch._poll_sources() == [item]


def test_get_health_includes_source_backoff_seconds():
    source = _FailingSource()
    orch = _orchestrator_with_sources([source])

    orch._poll_sources()

    backoff = orch.get_health()["source_backoff_seconds"]
    assert "failing" in backoff
    assert backoff["failing"] > 0


# ---------------------------------------------------------------------------
# Hitster-safe mode
# ---------------------------------------------------------------------------

def _music_item(title="Comfortably Numb"):
    return NowPlaying(source="static", media_type="music", title=title, subtitle="Pink Floyd")


def _movie_item(title="The Matrix"):
    return NowPlaying(source="static", media_type="movie", title=title)


def test_hitster_safe_defaults_to_disabled():
    orch = _orchestrator(outputs=[MagicMock()], cache=MagicMock())
    assert orch.get_hitster_safe() is False


def test_hitster_safe_suppresses_music_like_nothing_playing():
    output = MagicMock()
    source = _StaticSource(_music_item())
    orch = Orchestrator(
        sources=[source],
        enrichers=[],
        outputs=[output],
        cache=MagicMock(),
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )
    orch.set_hitster_safe(True)

    orch._tick()

    output.on_idle.assert_called_once()
    output.on_new_item.assert_not_called()
    output.update.assert_not_called()


def test_hitster_safe_does_not_suppress_movies():
    output = MagicMock()
    source = _StaticSource(_movie_item())
    orch = Orchestrator(
        sources=[source],
        enrichers=[],
        outputs=[output],
        cache=MagicMock(),
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )
    orch.set_hitster_safe(True)

    orch._tick()

    output.on_new_item.assert_called_once()


def test_disabling_hitster_safe_resumes_music_display():
    output = MagicMock()
    source = _StaticSource(_music_item())
    orch = Orchestrator(
        sources=[source],
        enrichers=[],
        outputs=[output],
        cache=MagicMock(),
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )
    orch.set_hitster_safe(True)
    orch._tick()
    output.reset_mock()

    orch.set_hitster_safe(False)
    orch._tick()

    output.on_new_item.assert_called_once()


def test_get_health_includes_hitster_safe_state():
    orch = _orchestrator(outputs=[MagicMock()], cache=MagicMock())
    orch.set_hitster_safe(True)
    assert orch.get_health()["hitster_safe"] is True


# ---------------------------------------------------------------------------
# _classify / _resolve_now_playing (pure decision logic, no mocked outputs)
# ---------------------------------------------------------------------------

def _orch_with_current(current):
    orch = _orchestrator(outputs=[MagicMock()], cache=MagicMock())
    orch._current = current
    return orch


def test_classify_new_item_when_nothing_was_playing():
    from mediainfo.orchestrator import _Transition

    orch = _orch_with_current(None)
    now_playing = _movie_item()
    assert orch._classify(orch._groups[0], now_playing) is _Transition.NEW_ITEM


def test_classify_new_item_when_identity_differs():
    orch = _orch_with_current(_movie_item(title="Old Movie"))
    now_playing = _movie_item(title="New Movie")
    from mediainfo.orchestrator import _Transition
    assert orch._classify(orch._groups[0], now_playing) is _Transition.NEW_ITEM


def test_classify_same_item_rotate_when_identity_matches_and_has_images():
    from mediainfo.orchestrator import _Transition

    current = NowPlaying(
        source="kodi", media_type="movie", title="Inception",
        images=[Artwork(url="https://example.com/p.jpg")],
    )
    orch = _orch_with_current(current)
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Inception")

    assert orch._classify(orch._groups[0], now_playing) is _Transition.SAME_ITEM_ROTATE


def test_classify_same_item_no_artwork_when_identity_matches_and_no_images():
    from mediainfo.orchestrator import _Transition

    current = NowPlaying(source="kodi", media_type="movie", title="Inception", images=[])
    orch = _orch_with_current(current)
    now_playing = NowPlaying(source="kodi", media_type="movie", title="Inception")

    assert orch._classify(orch._groups[0], now_playing) is _Transition.SAME_ITEM_NO_ARTWORK


def test_classify_does_not_mutate_state():
    current = _movie_item(title="Inception")
    orch = _orch_with_current(current)
    now_playing = _movie_item(title="Inception")

    orch._classify(orch._groups[0], now_playing)

    assert orch._current is current  # unchanged - classify is read-only


def test_resolve_now_playing_passes_through_when_hitster_safe_disabled():
    orch = _orchestrator(outputs=[MagicMock()], cache=MagicMock())
    orch.sources = [_StaticSource(_music_item())]
    assert orch._resolve_now_playing() is not None


def test_resolve_now_playing_returns_none_for_music_when_hitster_safe_enabled():
    orch = _orchestrator(outputs=[MagicMock()], cache=MagicMock())
    orch.sources = [_StaticSource(_music_item())]
    orch.set_hitster_safe(True)
    assert orch._resolve_now_playing() is None


def test_resolve_now_playing_ignores_hitster_safe_for_movies():
    orch = _orchestrator(outputs=[MagicMock()], cache=MagicMock())
    orch.sources = [_StaticSource(_movie_item())]
    orch.set_hitster_safe(True)
    assert orch._resolve_now_playing() is not None


# ---------------------------------------------------------------------------
# _idle.needs_refetch (pure) / _idle.refetch / _idle.rotate
# ---------------------------------------------------------------------------

def test_idle_batch_needs_refetch_when_no_batch_yet():
    idle_source = _FakeIdleSource([], rotation_interval_seconds=300)
    orch = _orchestrator(outputs=[MagicMock()], cache=MagicMock(), idle_source=idle_source)
    assert orch._idle.needs_refetch(time.monotonic()) is True


def test_idle_batch_does_not_need_refetch_before_interval_elapses():
    idle_source = _FakeIdleSource(_idle_wallpapers(), rotation_interval_seconds=1000)
    orch = _orchestrator(outputs=[MagicMock()], cache=MagicMock(), idle_source=idle_source)
    orch._idle.images = _idle_wallpapers()
    orch._idle.last_batch_fetch = time.monotonic()
    assert orch._idle.needs_refetch(time.monotonic()) is False


def test_idle_batch_needs_refetch_once_interval_elapses():
    idle_source = _FakeIdleSource(_idle_wallpapers(), rotation_interval_seconds=10)
    orch = _orchestrator(outputs=[MagicMock()], cache=MagicMock(), idle_source=idle_source)
    orch._idle.images = _idle_wallpapers()
    orch._idle.last_batch_fetch = 1000.0
    assert orch._idle.needs_refetch(1011.0) is True


def test_idle_batch_needs_refetch_does_not_mutate_state():
    idle_source = _FakeIdleSource(_idle_wallpapers(), rotation_interval_seconds=1000)
    orch = _orchestrator(outputs=[MagicMock()], cache=MagicMock(), idle_source=idle_source)
    orch._idle.images = _idle_wallpapers()
    orch._idle.last_batch_fetch = time.monotonic()
    before = orch._idle.images

    orch._idle.needs_refetch(time.monotonic())

    assert orch._idle.images is before  # unchanged - read-only
    assert idle_source.calls == 0  # never asked the source for anything


def test_refetch_idle_batch_returns_false_when_source_empty_and_no_previous_batch():
    idle_source = _FakeIdleSource([], rotation_interval_seconds=300)
    orch = _orchestrator(outputs=[MagicMock()], cache=MagicMock(), idle_source=idle_source)

    result = orch._idle.refetch(time.monotonic())

    assert result is False
    assert orch._idle.images == []


def test_refetch_idle_batch_falls_back_to_previous_batch_when_source_empty():
    # The idle source being unavailable (e.g. Unsplash down) shouldn't
    # blank outputs that already have a batch to show - whether retained
    # from earlier this process or loaded from disk at startup.
    idle_source = _FakeIdleSource([], rotation_interval_seconds=300)
    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/wallpaper.jpg"
    cache.get_transformed_path.side_effect = lambda path, _: path
    orch = _orchestrator(outputs=[output], cache=cache, idle_source=idle_source)
    orch._idle.images = _idle_wallpapers(count=1)

    result = orch._idle.refetch(time.monotonic())

    assert result is True
    assert orch._idle.images == _idle_wallpapers(count=1)  # untouched
    output.update.assert_called_once()  # the previous batch was still pushed


def test_refetch_idle_batch_leaves_an_already_shown_batch_alone():
    # If the batch was already pushed in this process (rotation_state
    # non-empty), a failed refetch should NOT re-push it - that's left to
    # the normal rotate()/timing path. The existing artwork stays
    # displayed either way (show()'s caller only blanks outputs when
    # self.images is empty), so there's nothing to re-push here.
    idle_source = _FakeIdleSource([], rotation_interval_seconds=300)
    output = MagicMock()
    cache = MagicMock()
    orch = _orchestrator(outputs=[output], cache=cache, idle_source=idle_source)
    orch._idle.images = _idle_wallpapers(count=1)
    orch._idle.rotation_state = {0: MagicMock()}

    result = orch._idle.refetch(time.monotonic())

    assert result is False
    output.update.assert_not_called()


# ---------------------------------------------------------------------------
# Idle batch persistence across restarts (falls back to it when the idle
# source is unavailable right after startup)
# ---------------------------------------------------------------------------

def test_successful_fetch_is_persisted_to_disk(tmp_path):
    images = _idle_wallpapers(count=2)
    idle_source = _FakeIdleSource(images, rotation_interval_seconds=300)
    cache = ImageCache(tmp_path)
    output = MagicMock()

    orch = Orchestrator(
        sources=[_FakeSource()],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
        idle_source=idle_source,
    )
    orch._tick()

    persist_path = cache.idle_dir / "last_idle_batch.json"
    assert persist_path.exists()
    import json
    saved = json.loads(persist_path.read_text())
    assert [item["url"] for item in saved] == [a.url for a in images]


def test_persisted_batch_is_loaded_on_construction_and_used_as_fallback(tmp_path):
    cache = ImageCache(tmp_path)
    persist_path = cache.idle_dir / "last_idle_batch.json"
    import json
    persist_path.write_text(json.dumps([{"url": "https://example.com/old.jpg", "label": "Old"}]))

    idle_source = _FakeIdleSource([], rotation_interval_seconds=300)  # unavailable
    output = MagicMock()
    cache.download_temp = MagicMock(return_value="/tmp/old.jpg")
    cache.get_transformed_path = MagicMock(side_effect=lambda path, _: path)

    orch = Orchestrator(
        sources=[_FakeSource()],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
        idle_source=idle_source,
    )
    orch._tick()

    # The persisted batch was loaded and shown despite the idle source
    # being unavailable - the output was never left blank.
    output.update.assert_called_once()
    output.on_idle.assert_not_called()
    _, artwork, _ = output.update.call_args[0]
    assert artwork.url == "https://example.com/old.jpg"


def test_no_persisted_batch_and_unavailable_source_falls_back_to_idle(tmp_path):
    cache = ImageCache(tmp_path)
    idle_source = _FakeIdleSource([], rotation_interval_seconds=300)
    output = MagicMock()

    orch = Orchestrator(
        sources=[_FakeSource()],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
        idle_source=idle_source,
    )
    orch._tick()

    output.on_idle.assert_called_once()
    output.update.assert_not_called()


def test_refetch_idle_batch_returns_true_and_updates_state():
    images = _idle_wallpapers()
    idle_source = _FakeIdleSource(images, rotation_interval_seconds=300)
    output = MagicMock()
    cache = MagicMock()
    cache.get_path.side_effect = lambda artwork, **kwargs: f"/cache/{artwork.label}"
    cache.get_transformed_path.side_effect = lambda path, _: path
    orch = _orchestrator(outputs=[output], cache=cache, idle_source=idle_source)

    result = orch._idle.refetch(time.monotonic())

    assert result is True
    assert orch._idle.images == images
    output.on_new_item.assert_called_once()
    output.update.assert_called_once()


# ---------------------------------------------------------------------------
# Output.music_album_art_only (e.g. PixooOutput) - skip artist photos
# ---------------------------------------------------------------------------

def test_music_album_art_only_output_skips_artist_photo():
    album_art = Artwork(url="https://example.com/album.jpg", label="Album art (Spotify)")
    artist_photo = Artwork(
        url="https://example.com/artist.jpg", label="Photo (Wikipedia)", is_artist_photo=True
    )
    now_playing = NowPlaying(
        source="spotify", media_type="music", title="Money",
        images=[artist_photo, album_art],
    )

    output = MagicMock()
    output.music_album_art_only = True
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/album.jpg"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )
    orchestrator._tick()

    output.update.assert_called_once()
    _, artwork, _ = output.update.call_args[0]
    assert artwork is album_art


def test_music_album_art_only_output_shows_nothing_when_only_artist_photos_available():
    artist_photo = Artwork(
        url="https://example.com/artist.jpg", label="Photo (Wikipedia)", is_artist_photo=True
    )
    now_playing = NowPlaying(
        source="spotify", media_type="music", title="Money", images=[artist_photo],
    )

    output = MagicMock()
    output.music_album_art_only = True
    cache = MagicMock()

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )
    orchestrator._tick()

    output.update.assert_not_called()


def test_regular_output_still_shows_artist_photo():
    artist_photo = Artwork(
        url="https://example.com/artist.jpg", label="Photo (Wikipedia)", is_artist_photo=True
    )
    now_playing = NowPlaying(
        source="spotify", media_type="music", title="Money", images=[artist_photo],
    )

    output = MagicMock()
    output.music_album_art_only = False
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/artist.jpg"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=30,
    )
    orchestrator._tick()

    output.update.assert_called_once()
    _, artwork, _ = output.update.call_args[0]
    assert artwork is artist_photo

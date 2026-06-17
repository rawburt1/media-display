"""Tests for Orchestrator idle wallpaper handling."""

from unittest.mock import MagicMock, patch

from pixoo_media.models import Artwork, NowPlaying
from pixoo_media.orchestrator import Orchestrator


class _FakeSource:
    def get_now_playing(self):
        return None


class _StaticSource:
    """Always returns the same now-playing item."""

    def __init__(self, item):
        self._item = item

    def get_now_playing(self):
        return self._item


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


def test_idle_source_shows_wallpaper():
    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/wallpaper.jpg"
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

    orchestrator._tick()  # playing without artwork: on_idle must NOT be called
    output.on_idle.assert_not_called()

    orchestrator._tick()  # back to idle: on_idle IS called
    output.on_idle.assert_called_once()


def _idle_wallpapers(count=3):
    return [
        Artwork(url=f"https://example.com/{i}.jpg", label=f"Wallpaper {i}") for i in range(count)
    ]


def test_idle_batch_each_output_gets_independently_shuffled_order():
    idle_source = _FakeIdleSource(_idle_wallpapers(), rotation_interval_seconds=300)
    output_a = MagicMock()
    output_b = MagicMock()
    cache = MagicMock()
    cache.get_path.side_effect = lambda artwork: f"/cache/{artwork.label}"
    cache.get_transformed_path.side_effect = lambda path, _: path

    orchestrator = _orchestrator(outputs=[output_a, output_b], cache=cache, idle_source=idle_source)

    with patch(
        "pixoo_media.orchestrator.random.shuffle",
        side_effect=_fake_shuffle([[2, 0, 1], [1, 2, 0]]),
    ):
        orchestrator._tick()

    _, artwork_a, path_a = output_a.update.call_args[0]
    _, artwork_b, path_b = output_b.update.call_args[0]
    assert artwork_a.label == "Wallpaper 2"
    assert path_a == "/cache/Wallpaper 2"
    assert artwork_b.label == "Wallpaper 1"
    assert path_b == "/cache/Wallpaper 1"
    assert idle_source.calls == 1


def test_idle_rotation_advances_each_output_independently():
    idle_source = _FakeIdleSource(_idle_wallpapers(), rotation_interval_seconds=300)
    output_a = MagicMock()
    output_b = MagicMock()
    cache = MagicMock()
    cache.get_path.side_effect = lambda artwork: f"/cache/{artwork.label}"

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
    with patch("pixoo_media.orchestrator.time.monotonic", clock), patch(
        "pixoo_media.orchestrator.random.shuffle",
        side_effect=_fake_shuffle([[0, 1, 2], [0, 2, 1]]),
    ):
        orchestrator._tick()  # initial batch: both outputs show "Wallpaper 0"

        output_a.update.reset_mock()
        output_b.update.reset_mock()

        clock.now += 100  # past rotation_interval_seconds, but not the batch refresh interval
        orchestrator._tick()

    _, artwork_a, _ = output_a.update.call_args[0]
    _, artwork_b, _ = output_b.update.call_args[0]
    assert artwork_a.label == "Wallpaper 1"  # order [0, 1, 2] -> position 1
    assert artwork_b.label == "Wallpaper 2"  # order [0, 2, 1] -> position 1
    assert idle_source.calls == 1


def test_idle_batch_refetched_after_interval():
    idle_source = _FakeIdleSource(_idle_wallpapers(count=1), rotation_interval_seconds=300)
    output = MagicMock()
    cache = MagicMock()
    cache.get_path.return_value = "/tmp/wallpaper.jpg"

    orchestrator = _orchestrator(outputs=[output], cache=cache, idle_source=idle_source)

    clock = _FakeClock()
    with patch("pixoo_media.orchestrator.time.monotonic", clock):
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


def _multi_image_now_playing():
    artworks = [Artwork(url=f"https://example.com/{i}.jpg", label=f"Image {i}") for i in range(3)]
    return NowPlaying(source="kodi", media_type="movie", title="Inception", images=artworks)


def test_each_output_gets_independently_shuffled_order():
    now_playing = _multi_image_now_playing()
    output_a = MagicMock()
    output_b = MagicMock()
    cache = MagicMock()
    cache.get_path.side_effect = lambda artwork: f"/cache/{artwork.label}"
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
        "pixoo_media.orchestrator.random.shuffle",
        side_effect=_fake_shuffle([[2, 0, 1], [1, 2, 0]]),
    ):
        orchestrator._tick()

    _, artwork_a, path_a = output_a.update.call_args[0]
    _, artwork_b, path_b = output_b.update.call_args[0]
    assert artwork_a.label == "Image 2"
    assert path_a == "/cache/Image 2"
    assert artwork_b.label == "Image 1"
    assert path_b == "/cache/Image 1"


def test_rotation_advances_each_output_independently():
    now_playing = _multi_image_now_playing()
    output_a = MagicMock()
    output_b = MagicMock()
    cache = MagicMock()
    cache.get_path.side_effect = lambda artwork: f"/cache/{artwork.label}"

    orchestrator = Orchestrator(
        sources=[_StaticSource(now_playing)],
        enrichers=[],
        outputs=[output_a, output_b],
        cache=cache,
        poll_interval_seconds=1,
        rotation_interval_seconds=10,
    )

    clock = _FakeClock()
    with patch("pixoo_media.orchestrator.time.monotonic", clock), patch(
        "pixoo_media.orchestrator.random.shuffle",
        side_effect=_fake_shuffle([[0, 1, 2], [0, 2, 1]]),
    ):
        orchestrator._tick()  # initial image: both outputs show "Image 0"

        output_a.update.reset_mock()
        output_b.update.reset_mock()

        clock.now += 100  # past rotation_interval_seconds
        orchestrator._tick()

    _, artwork_a, _ = output_a.update.call_args[0]
    _, artwork_b, _ = output_b.update.call_args[0]
    assert artwork_a.label == "Image 1"  # order [0, 1, 2] -> position 1
    assert artwork_b.label == "Image 2"  # order [0, 2, 1] -> position 1


def test_single_image_does_not_rotate():
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

    output.update.assert_not_called()

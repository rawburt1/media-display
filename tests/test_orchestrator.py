"""Tests for Orchestrator idle wallpaper handling."""

from unittest.mock import MagicMock

from pixoo_media.models import Artwork
from pixoo_media.orchestrator import Orchestrator


class _FakeSource:
    def get_now_playing(self):
        return None


class _FakeIdleSource:
    def __init__(self, artworks, rotation_interval_seconds=0):
        self.artworks = list(artworks)
        self.rotation_interval_seconds = rotation_interval_seconds
        self.calls = 0

    def get_wallpaper(self):
        self.calls += 1
        if not self.artworks:
            return None
        return self.artworks.pop(0)


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

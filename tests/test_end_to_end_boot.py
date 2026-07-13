"""End-to-end boot test (H6 - see docs/architecture-usability-review-2026-07.md):
"there is no test that boots the *real* __main__ wiring (config -> outputs
-> orchestrator -> tick -> fake output) with a realistic config... a true
end-to-end 'appliance boots, plays a fake track, every enabled output got
an update, config hot-reload swaps a source' test would catch the class
of bug unit tests structurally can't (wiring omissions)."

tests/test_smoke.py comes close - it builds every collaborator from
config.example.yaml and confirms nothing raises - but stops there. This
file goes one step further: it actually starts a real Orchestrator thread
and a real WebOutput behind a real SharedHttpServer, and observes the
result through the same public HTTP API a browser would use
(GET /api/now-playing), rather than reaching into orchestrator internals.
A fake, in-test-only MediaSource (not a mock - a real MediaSource
subclass, registered the same way a real plugin would be) stands in for
an actual device/service, since this test's job is to catch wiring
mistakes, not re-test any individual source's own protocol handling
(already covered by that source's own dedicated test file).

The second half reuses mediainfo.__main__._start_and_wire() and
mediainfo.reload_plan.compute_reload_plan() directly (the same real
functions __main__.main()'s config-file-watching loop calls - see N7)
to hot-reload from one fake source to another, and confirms the swap
actually reaches the running output.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Optional

import pytest

from mediainfo.__main__ import _build_cache, _start_and_wire
from mediainfo.config import Config
from mediainfo.models import NowPlaying
from mediainfo.musiclibrary import MusicLibrary
from mediainfo.outputs.http_server import SharedHttpServer
from mediainfo.sources.base import MediaSource
from mediainfo.wiring import (
    build_artwork_overrides,
    build_history,
    build_poster_store,
    instantiate_outputs,
)


class _FakeSource(MediaSource):
    """A real MediaSource implementation (not a mock) standing in for an
    actual device/service - returns a fixed, controllable NowPlaying so
    this test can assert on it without any real network/hardware."""

    def __init__(self, config, *, title: str, subtitle: str) -> None:
        self.config = config
        self._now_playing = NowPlaying(
            source=self.name, media_type="music", title=title, subtitle=subtitle
        )

    def get_now_playing(self) -> Optional[NowPlaying]:
        return self._now_playing


class _FakeSourceA(_FakeSource):
    name = "fake_a"

    def __init__(self, config) -> None:
        super().__init__(config, title="Song A", subtitle="Artist A")


class _FakeSourceB(_FakeSource):
    name = "fake_b"

    def __init__(self, config) -> None:
        super().__init__(config, title="Song B", subtitle="Artist B")


def _minimal_config(tmp_path: Path, *, priority: list, sources: dict) -> Config:
    raw = {
        "priority": priority,
        "sources": sources,
        "outputs": {"web": [{"enabled": True}]},
        "http": {"host": "127.0.0.1", "port": 0},
        # Fast enough that the very first tick (which fires immediately -
        # see Orchestrator._run()) is all this test needs to wait for.
        "poll_interval_seconds": 1,
        "cache": {"dir": str(tmp_path / "cache")},
        "library": {"db_path": str(tmp_path / "library.db")},
        "overrides": {"dir": str(tmp_path / "overrides")},
        "posters": {"dir": str(tmp_path / "posters")},
        "history": {"db_path": str(tmp_path / "history.db")},
        "mediadata": {"path": str(tmp_path / "mediadata")},
    }
    return Config.from_dict(raw)


@pytest.fixture
def registered_fake_sources(monkeypatch):
    """Register _FakeSourceA/_FakeSourceB the same way a real plugin is
    registered - both registries.py's dotted-path dict (get_source_class())
    and mediainfo.config's SOURCE_CONFIG_TYPES (Config.from_dict()'s own
    validation) - so this test exercises the real wiring path end to end,
    not a shortcut around it. monkeypatch.setitem auto-reverts, so this
    can't leak into any other test (e.g. H3's registry-parity tests, which
    iterate the real dicts and would otherwise trip over test-only keys).
    """
    import pydantic

    import mediainfo.config as config_module
    from mediainfo import registries

    # A minimal but real config dataclass, matching every actual source's
    # own convention (pydantic.dataclasses.dataclass, extra="forbid") -
    # Config.from_dict() calls SOURCE_CONFIG_TYPES[name](**values), so this
    # needs to accept exactly the fields this test's raw config supplies.
    @pydantic.dataclasses.dataclass(config=pydantic.ConfigDict(extra="forbid"))
    class FakeSourceConfig:
        enabled: bool = False

    monkeypatch.setitem(registries.SOURCE_CLASSES, "fake_a", _FakeSourceA)
    monkeypatch.setitem(registries.SOURCE_CLASSES, "fake_b", _FakeSourceB)
    monkeypatch.setitem(config_module.SOURCE_CONFIG_TYPES, "fake_a", FakeSourceConfig)
    monkeypatch.setitem(config_module.SOURCE_CONFIG_TYPES, "fake_b", FakeSourceConfig)
    yield


def _get_now_playing(port: int) -> dict:
    resp = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/now-playing", timeout=2)
    return json.loads(resp.read())


def _wait_until(predicate, timeout: float = 3.0, interval: float = 0.05):
    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as exc:  # e.g. connection refused during startup
            last_err = exc
        time.sleep(interval)
    raise AssertionError(f"condition never became true within {timeout}s (last error: {last_err})")


@pytest.fixture
def boot(tmp_path, registered_fake_sources):
    """Boot the real wiring path with fake_a active: Config.load-equivalent
    -> instantiate_outputs -> _start_and_wire (real Orchestrator, real
    thread) -> SharedHttpServer.start() - exactly what __main__.main()
    does, minus the signal handling and config-file-watching loop (those
    are plain glue, already covered by tests/test_main.py).
    """
    config = _minimal_config(tmp_path, priority=["fake_a"], sources={"fake_a": {"enabled": True}})
    cache = _build_cache(config)
    server = SharedHttpServer(config.http, config.auth)
    outputs = instantiate_outputs(config, tmp_path / "config.yaml", cache, server)
    server.start()
    library = MusicLibrary(config.library.db_path, max_age_days=config.library.max_age_days)
    overrides = build_artwork_overrides(config)
    poster_store = build_poster_store(config)
    history = build_history(config)
    state = _start_and_wire(config, outputs, cache, library, overrides, poster_store, history)

    assert server._server is not None
    port = server._server.server_port
    try:
        yield config, outputs, cache, library, overrides, poster_store, history, state, port
    finally:
        state.orch.stop()
        state.orch.join()
        server.stop()
        library.close()
        if history is not None:
            history.close()


def test_boot_to_fake_track_updates_the_output(boot):
    *_rest, port = boot

    _wait_until(lambda: _get_now_playing(port).get("title") == "Song A")

    payload = _get_now_playing(port)
    assert payload["source"] == "fake_a"
    assert payload["subtitle"] == "Artist A"


def test_config_hot_reload_swaps_the_active_source(boot):
    config, outputs, cache, library, overrides, poster_store, history, state, port = boot

    _wait_until(lambda: _get_now_playing(port).get("title") == "Song A")

    # The same real reload path __main__.main()'s config-file-watching
    # loop drives (see N7's mediainfo.reload_plan.compute_reload_plan +
    # _start_and_wire) - just invoked directly instead of via a file mtime
    # change, since that outer loop is plain glue already covered by
    # tests/test_main.py.
    from mediainfo.reload_plan import compute_reload_plan

    new_config = Config.from_dict(
        {
            **_raw_of(config),
            "priority": ["fake_b"],
            "sources": {"fake_a": {"enabled": False}, "fake_b": {"enabled": True}},
        }
    )
    plan = compute_reload_plan(config, new_config)
    assert plan.sources_dirty
    assert plan.orchestrator_dirty

    new_state = _start_and_wire(
        new_config,
        outputs,
        cache,
        library,
        overrides,
        poster_store,
        history,
        previous=state,
        plan=plan,
    )

    _wait_until(lambda: _get_now_playing(port).get("title") == "Song B")

    payload = _get_now_playing(port)
    assert payload["source"] == "fake_b"
    assert payload["subtitle"] == "Artist B"

    new_state.orch.stop()
    new_state.orch.join()


def _raw_of(config: Config) -> dict:
    """Rebuild a from_dict()-compatible raw dict for *config* - only the
    handful of top-level keys this test's own _minimal_config() sets,
    since that's all Config.from_dict() needs (everything else keeps its
    default)."""
    return {
        "priority": list(config.priority),
        "sources": {},
        "outputs": {"web": [{"enabled": True}]},
        "http": {"host": config.http.host, "port": config.http.port},
        "poll_interval_seconds": config.poll_interval_seconds,
        "cache": {"dir": config.cache.dir},
        "library": {"db_path": config.library.db_path},
        "overrides": {"dir": config.overrides.dir},
        "posters": {"dir": config.posters.dir},
        "history": {"db_path": config.history.db_path},
        "mediadata": {"path": config.mediadata.path},
    }

"""Tests for mediainfo.wiring: building sources/enrichers/idle sources/
outputs from config, and wiring cross-cutting state onto outputs.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mediainfo.text_cache import TextCache
from mediainfo.wiring import (
    _compute_url_mount,
    attach_services,
    build_app_services,
    build_artwork_overrides,
    build_enrichers,
    build_idle_source,
    build_mediadata_store,
    build_sources,
    build_text_enrichers,
    instantiate_outputs,
    start_orchestrator,
)


def _minimal_config(**kwargs):
    """Return a MagicMock that quacks like a Config."""
    cfg = MagicMock()
    cfg.priority = []
    cfg.sources = {}
    cfg.enrichers = {}
    cfg.text_enrichers = {}
    cfg.idle = {}
    cfg.idle_priority = []
    cfg.idle_mode = "priority"
    # Real values (not a bare MagicMock attribute) - build_text_enrichers()
    # constructs a real TextCache(Path(config.cache.dir)/"text", ...),
    # which creates that directory on disk; a MagicMock-derived path would
    # otherwise get mkdir'd for real under a garbage name.
    cfg.cache.dir = tempfile.gettempdir()
    cfg.cache.max_age_days = 30
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


# ---------------------------------------------------------------------------
# instantiate_outputs
# ---------------------------------------------------------------------------


def test_instantiate_outputs_calls_start_on_each():
    output_cfg = MagicMock()
    output_cfg.enabled = True
    fake_instance = MagicMock()
    fake_cls = MagicMock(return_value=fake_instance)
    cfg = _minimal_config(outputs={"pixoo": [output_cfg]})

    with (
        patch("mediainfo.registries.OUTPUT_CLASSES", {"pixoo": fake_cls}),
        patch("mediainfo.registries.OUTPUT_EXTRA_ARGS", {}),
    ):
        result = instantiate_outputs(cfg, Path("config.yaml"), MagicMock())

    fake_instance.start.assert_called_once_with()
    assert result == [fake_instance]


def test_instantiate_outputs_skips_disabled():
    output_cfg = MagicMock()
    output_cfg.enabled = False
    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(outputs={"pixoo": [output_cfg]})

    with (
        patch("mediainfo.registries.OUTPUT_CLASSES", {"pixoo": fake_cls}),
        patch("mediainfo.registries.OUTPUT_EXTRA_ARGS", {}),
    ):
        result = instantiate_outputs(cfg, Path("config.yaml"), MagicMock())

    fake_cls.assert_not_called()
    assert result == []


class _FakeOutputCls:
    """A minimal Output-like class for build_http_blueprint()'s sake -
    real Output subclasses declare root_mounted as a class attribute."""

    root_mounted = False


class _RootMountedOutputCls:
    root_mounted = True


def test_compute_url_mount_single_instance_uses_plain_prefix_and_name():
    prefix, name = _compute_url_mount("config", 0, 1, _FakeOutputCls, "")
    assert (prefix, name) == ("/config", "config")


def test_compute_url_mount_root_mounted_output_uses_empty_prefix():
    prefix, name = _compute_url_mount("web", 0, 1, _RootMountedOutputCls, "")
    assert (prefix, name) == ("", "web")


def test_compute_url_mount_second_instance_uses_label_suffix_and_indexed_name():
    prefix, name = _compute_url_mount("config", 1, 2, _FakeOutputCls, "dashboard")
    assert (prefix, name) == ("/config-dashboard", "config1")


def test_compute_url_mount_second_root_mounted_instance_uses_label_as_prefix():
    prefix, name = _compute_url_mount("web", 1, 2, _RootMountedOutputCls, "bedroom")
    assert (prefix, name) == ("/bedroom", "web1")


def test_compute_url_mount_first_instance_name_is_indexed_when_multiple_exist():
    # Even the first instance's blueprint name must be disambiguated once
    # there's more than one, even though its URL prefix stays plain -
    # Flask requires unique blueprint names regardless of prefix.
    prefix, name = _compute_url_mount("config", 0, 2, _FakeOutputCls, "")
    assert (prefix, name) == ("/config", "config0")


def test_compute_url_mount_missing_label_on_second_instance_raises():
    with pytest.raises(ValueError, match="label"):
        _compute_url_mount("config", 1, 2, _FakeOutputCls, "")


def test_instantiate_outputs_second_instance_of_non_http_output_needs_no_label():
    # Regression test: _compute_url_mount()'s label-collision check must
    # only apply to Flask-based outputs (those overriding
    # build_http_blueprint) - a non-HTTP output (e.g. ulanzi, ran with two
    # unlabeled instances in a real config this was caught against) never
    # mounts anything on the shared server, so it must not be required to
    # set a `label` just because a second instance exists. Uses the real
    # Output.build_http_blueprint (inherited, unoverridden) rather than a
    # MagicMock class so the "isn't overridden" check actually exercises
    # the same attribute lookup real Output subclasses go through.
    from mediainfo.outputs.base import Output

    class _NonHttpOutput:
        root_mounted = False
        build_http_blueprint = Output.build_http_blueprint

        def __init__(self, config):
            self.config = config

        def start(self):
            pass

    first_cfg = MagicMock(enabled=True, label="")
    second_cfg = MagicMock(enabled=True, label="")
    cfg = _minimal_config(outputs={"ulanzi": [first_cfg, second_cfg]})
    shared_server = MagicMock()

    with (
        patch("mediainfo.registries.OUTPUT_CLASSES", {"ulanzi": _NonHttpOutput}),
        patch("mediainfo.registries.OUTPUT_EXTRA_ARGS", {}),
    ):
        result = instantiate_outputs(cfg, Path("config.yaml"), MagicMock(), shared_server)

    assert len(result) == 2
    shared_server.register_blueprint.assert_not_called()


def test_instantiate_outputs_registers_blueprint_on_shared_server():
    output_cfg = MagicMock()
    output_cfg.enabled = True
    output_cfg.label = ""
    fake_instance = MagicMock()
    fake_blueprint = MagicMock()
    fake_instance.build_http_blueprint.return_value = fake_blueprint
    fake_cls = MagicMock(return_value=fake_instance, root_mounted=False)
    cfg = _minimal_config(outputs={"pixoo": [output_cfg]})
    shared_server = MagicMock()

    with (
        patch("mediainfo.registries.OUTPUT_CLASSES", {"pixoo": fake_cls}),
        patch("mediainfo.registries.OUTPUT_EXTRA_ARGS", {}),
    ):
        instantiate_outputs(cfg, Path("config.yaml"), MagicMock(), shared_server)

    fake_instance.build_http_blueprint.assert_called_once_with("/pixoo", sock=shared_server.sock)
    shared_server.register_blueprint.assert_called_once_with(
        fake_blueprint, url_prefix="/pixoo", name="pixoo"
    )


def test_instantiate_outputs_skips_registration_when_blueprint_is_none():
    # An output that isn't Flask-based (build_http_blueprint()'s default
    # implementation returns None) must not be registered on the shared
    # server at all.
    output_cfg = MagicMock()
    output_cfg.enabled = True
    fake_instance = MagicMock()
    fake_instance.build_http_blueprint.return_value = None
    fake_cls = MagicMock(return_value=fake_instance, root_mounted=False)
    cfg = _minimal_config(outputs={"mqtt": [output_cfg]})
    shared_server = MagicMock()

    with (
        patch("mediainfo.registries.OUTPUT_CLASSES", {"mqtt": fake_cls}),
        patch("mediainfo.registries.OUTPUT_EXTRA_ARGS", {}),
    ):
        instantiate_outputs(cfg, Path("config.yaml"), MagicMock(), shared_server)

    shared_server.register_blueprint.assert_not_called()


def test_instantiate_outputs_without_shared_server_never_builds_blueprints():
    # Backward-compatible default (shared_server=None): callers that don't
    # care about HTTP wiring (most existing tests) are unaffected.
    output_cfg = MagicMock()
    output_cfg.enabled = True
    fake_instance = MagicMock()
    fake_cls = MagicMock(return_value=fake_instance, root_mounted=False)
    cfg = _minimal_config(outputs={"pixoo": [output_cfg]})

    with (
        patch("mediainfo.registries.OUTPUT_CLASSES", {"pixoo": fake_cls}),
        patch("mediainfo.registries.OUTPUT_EXTRA_ARGS", {}),
    ):
        instantiate_outputs(cfg, Path("config.yaml"), MagicMock())

    fake_instance.build_http_blueprint.assert_not_called()


# ---------------------------------------------------------------------------
# build_sources / build_enrichers / build_idle_source
# ---------------------------------------------------------------------------


def test_build_sources_empty_priority():
    cfg = _minimal_config()
    assert build_sources(cfg) == []


def test_build_sources_skips_disabled():
    source_cfg = MagicMock()
    source_cfg.enabled = False
    cfg = _minimal_config(priority=["kodi"], sources={"kodi": source_cfg})
    assert build_sources(cfg) == []


def test_build_sources_skips_unknown(caplog):
    import logging

    source_cfg = MagicMock()
    source_cfg.enabled = True
    cfg = _minimal_config(priority=["nonexistent"], sources={"nonexistent": source_cfg})
    with caplog.at_level(logging.WARNING, logger="mediainfo.wiring"):
        result = build_sources(cfg)
    assert result == []
    assert any("nonexistent" in r.message for r in caplog.records)


def test_build_sources_instantiates_enabled():
    source_cfg = MagicMock()
    source_cfg.enabled = True

    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(priority=["kodi"], sources={"kodi": source_cfg})

    with patch("mediainfo.registries.SOURCE_CLASSES", {"kodi": fake_cls}):
        result = build_sources(cfg)

    fake_cls.assert_called_once_with(source_cfg)
    assert result == [fake_cls.return_value]


def test_build_enrichers_skips_disabled():
    enc_cfg = MagicMock()
    enc_cfg.enabled = False
    cfg = _minimal_config(enrichers={"fanarttv": enc_cfg})
    assert build_enrichers(cfg) == []


def test_build_enrichers_instantiates_enabled():
    enc_cfg = MagicMock()
    enc_cfg.enabled = True

    fake_cls = MagicMock(return_value=MagicMock())
    fake_cls.capabilities = frozenset()
    cfg = _minimal_config(enrichers={"fanarttv": enc_cfg})

    with patch("mediainfo.registries.ENRICHER_CLASSES", {"fanarttv": fake_cls}):
        result = build_enrichers(cfg)

    fake_cls.assert_called_once_with(enc_cfg)
    assert result == [fake_cls.return_value]


def test_build_enrichers_passes_library_to_library_aware_enrichers():
    enc_cfg = MagicMock()
    enc_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    fake_cls.capabilities = frozenset({"library"})
    fake_library = MagicMock()
    cfg = _minimal_config(enrichers={"fanarttv": enc_cfg})

    with patch("mediainfo.registries.ENRICHER_CLASSES", {"fanarttv": fake_cls}):
        result = build_enrichers(cfg, fake_library)

    fake_cls.assert_called_once_with(enc_cfg, fake_library)
    assert result == [fake_cls.return_value]


def test_build_enrichers_passes_cache_dir_to_cache_aware_enrichers():
    enc_cfg = MagicMock()
    enc_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    fake_cls.capabilities = frozenset({"cache_dir"})
    cfg = _minimal_config(enrichers={"ai_artwork": enc_cfg})

    with patch("mediainfo.registries.ENRICHER_CLASSES", {"ai_artwork": fake_cls}):
        result = build_enrichers(cfg)

    args, _ = fake_cls.call_args
    assert args[0] is enc_cfg
    assert args[1] == Path(cfg.cache.dir) / "ai_artwork"
    assert result == [fake_cls.return_value]


def test_build_enrichers_passes_mediadata_store_to_mediadata_aware_enrichers():
    enc_cfg = MagicMock()
    enc_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    fake_cls.capabilities = frozenset({"mediadata"})
    fake_store = MagicMock()
    cfg = _minimal_config(enrichers={"mediadata": enc_cfg})

    with patch("mediainfo.registries.ENRICHER_CLASSES", {"mediadata": fake_cls}):
        result = build_enrichers(cfg, mediadata_store=fake_store)

    fake_cls.assert_called_once_with(enc_cfg, fake_store)
    assert result == [fake_cls.return_value]


# ---------------------------------------------------------------------------
# build_mediadata_store
# ---------------------------------------------------------------------------


def test_build_mediadata_store_none_when_neither_plugin_enabled():
    cfg = _minimal_config(enrichers={}, text_enrichers={})
    assert build_mediadata_store(cfg, MagicMock()) is None


def test_build_mediadata_store_none_when_both_disabled():
    artwork_cfg = MagicMock(enabled=False)
    lyrics_cfg = MagicMock(enabled=False)
    cfg = _minimal_config(
        enrichers={"mediadata": artwork_cfg}, text_enrichers={"mediadata": lyrics_cfg}
    )
    assert build_mediadata_store(cfg, MagicMock()) is None


def test_build_mediadata_store_constructed_when_artwork_enabled():
    artwork_cfg = MagicMock(enabled=True)
    cfg = _minimal_config(enrichers={"mediadata": artwork_cfg}, text_enrichers={})
    fake_cache = MagicMock()
    fake_cls = MagicMock(return_value=MagicMock())

    with patch("mediainfo.wiring.MediaDataStore", fake_cls):
        result = build_mediadata_store(cfg, fake_cache)

    fake_cls.assert_called_once_with(
        cfg.mediadata,
        cache=fake_cache,
        discogs_token="",
        tmdb_api_key="",
        fanarttv_api_key="",
        lastfm_api_key="",
    )
    assert result is fake_cls.return_value


def test_build_mediadata_store_constructed_when_lyrics_enabled():
    lyrics_cfg = MagicMock(enabled=True)
    cfg = _minimal_config(enrichers={}, text_enrichers={"mediadata": lyrics_cfg})
    fake_cls = MagicMock(return_value=MagicMock())

    with patch("mediainfo.wiring.MediaDataStore", fake_cls):
        result = build_mediadata_store(cfg, MagicMock())

    assert result is fake_cls.return_value


def test_build_mediadata_store_passes_discogs_token_when_enabled():
    artwork_cfg = MagicMock(enabled=True)
    discogs_cfg = MagicMock(enabled=True, token="secret-token")
    cfg = _minimal_config(
        enrichers={"mediadata": artwork_cfg, "discogs": discogs_cfg}, text_enrichers={}
    )
    fake_cls = MagicMock(return_value=MagicMock())

    with patch("mediainfo.wiring.MediaDataStore", fake_cls):
        build_mediadata_store(cfg, MagicMock())

    _, kwargs = fake_cls.call_args
    assert kwargs["discogs_token"] == "secret-token"


def test_build_mediadata_store_skips_discogs_token_when_disabled():
    artwork_cfg = MagicMock(enabled=True)
    discogs_cfg = MagicMock(enabled=False, token="secret-token")
    cfg = _minimal_config(
        enrichers={"mediadata": artwork_cfg, "discogs": discogs_cfg}, text_enrichers={}
    )
    fake_cls = MagicMock(return_value=MagicMock())

    with patch("mediainfo.wiring.MediaDataStore", fake_cls):
        build_mediadata_store(cfg, MagicMock())

    _, kwargs = fake_cls.call_args
    assert kwargs["discogs_token"] == ""


def test_build_mediadata_store_passes_tmdb_and_fanarttv_keys_when_enabled():
    artwork_cfg = MagicMock(enabled=True)
    tmdb_cfg = MagicMock(enabled=True, api_key="tmdb-key")
    fanarttv_cfg = MagicMock(enabled=True, api_key="fanarttv-key")
    cfg = _minimal_config(
        enrichers={
            "mediadata": artwork_cfg,
            "tmdb": tmdb_cfg,
            "fanarttv": fanarttv_cfg,
        },
        text_enrichers={},
    )
    fake_cls = MagicMock(return_value=MagicMock())

    with patch("mediainfo.wiring.MediaDataStore", fake_cls):
        build_mediadata_store(cfg, MagicMock())

    _, kwargs = fake_cls.call_args
    assert kwargs["tmdb_api_key"] == "tmdb-key"
    assert kwargs["fanarttv_api_key"] == "fanarttv-key"


def test_build_mediadata_store_skips_tmdb_and_fanarttv_keys_when_disabled():
    artwork_cfg = MagicMock(enabled=True)
    tmdb_cfg = MagicMock(enabled=False, api_key="tmdb-key")
    fanarttv_cfg = MagicMock(enabled=False, api_key="fanarttv-key")
    cfg = _minimal_config(
        enrichers={
            "mediadata": artwork_cfg,
            "tmdb": tmdb_cfg,
            "fanarttv": fanarttv_cfg,
        },
        text_enrichers={},
    )
    fake_cls = MagicMock(return_value=MagicMock())

    with patch("mediainfo.wiring.MediaDataStore", fake_cls):
        build_mediadata_store(cfg, MagicMock())

    _, kwargs = fake_cls.call_args
    assert kwargs["tmdb_api_key"] == ""
    assert kwargs["fanarttv_api_key"] == ""


def test_build_mediadata_store_passes_lastfm_key_when_enabled():
    artwork_cfg = MagicMock(enabled=True)
    lastfm_cfg = MagicMock(enabled=True, api_key="lastfm-key")
    cfg = _minimal_config(
        enrichers={"mediadata": artwork_cfg, "lastfm": lastfm_cfg},
        text_enrichers={},
    )
    fake_cls = MagicMock(return_value=MagicMock())

    with patch("mediainfo.wiring.MediaDataStore", fake_cls):
        build_mediadata_store(cfg, MagicMock())

    _, kwargs = fake_cls.call_args
    assert kwargs["lastfm_api_key"] == "lastfm-key"


def test_build_mediadata_store_skips_lastfm_key_when_disabled():
    artwork_cfg = MagicMock(enabled=True)
    lastfm_cfg = MagicMock(enabled=False, api_key="lastfm-key")
    cfg = _minimal_config(
        enrichers={"mediadata": artwork_cfg, "lastfm": lastfm_cfg},
        text_enrichers={},
    )
    fake_cls = MagicMock(return_value=MagicMock())

    with patch("mediainfo.wiring.MediaDataStore", fake_cls):
        build_mediadata_store(cfg, MagicMock())

    _, kwargs = fake_cls.call_args
    assert kwargs["lastfm_api_key"] == ""


# ---------------------------------------------------------------------------
# build_text_enrichers (roadmap item 7 foundation - no real plugin yet)
# ---------------------------------------------------------------------------


def test_build_text_enrichers_empty_by_default():
    cfg = _minimal_config()
    assert build_text_enrichers(cfg) == []


def test_build_text_enrichers_skips_disabled():
    text_cfg = MagicMock()
    text_cfg.enabled = False
    cfg = _minimal_config(text_enrichers={"lrclib": text_cfg})
    assert build_text_enrichers(cfg) == []


def test_build_text_enrichers_skips_unknown(caplog):
    import logging

    text_cfg = MagicMock()
    text_cfg.enabled = True
    cfg = _minimal_config(text_enrichers={"nonexistent": text_cfg})
    with caplog.at_level(logging.WARNING, logger="mediainfo.wiring"):
        result = build_text_enrichers(cfg)
    assert result == []
    assert any("nonexistent" in r.message for r in caplog.records)


def test_build_text_enrichers_instantiates_enabled():
    text_cfg = MagicMock()
    text_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(text_enrichers={"lrclib": text_cfg})

    with patch("mediainfo.registries.TEXT_ENRICHER_CLASSES", {"lrclib": fake_cls}):
        result = build_text_enrichers(cfg)

    args, _ = fake_cls.call_args
    assert args[0] is text_cfg
    assert isinstance(args[1], TextCache)
    assert result == [fake_cls.return_value]


def test_build_text_enrichers_shares_one_cache_across_plugins():
    lrclib_cfg = MagicMock()
    lrclib_cfg.enabled = True
    other_cfg = MagicMock()
    other_cfg.enabled = True
    fake_cls = MagicMock(side_effect=lambda cfg, cache: MagicMock(cache=cache))
    cfg = _minimal_config(text_enrichers={"lrclib": lrclib_cfg, "other": other_cfg})

    with patch(
        "mediainfo.registries.TEXT_ENRICHER_CLASSES",
        {"lrclib": fake_cls, "other": fake_cls},
    ):
        result = build_text_enrichers(cfg)

    assert result[0].cache is result[1].cache


def test_build_text_enrichers_passes_mediadata_store_to_mediadata_aware_enrichers():
    text_cfg = MagicMock()
    text_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    fake_cls.capabilities = frozenset({"mediadata"})
    fake_store = MagicMock()
    cfg = _minimal_config(text_enrichers={"mediadata": text_cfg})

    with patch("mediainfo.registries.TEXT_ENRICHER_CLASSES", {"mediadata": fake_cls}):
        result = build_text_enrichers(cfg, mediadata_store=fake_store)

    fake_cls.assert_called_once_with(text_cfg, fake_store)
    assert result == [fake_cls.return_value]


def test_build_idle_source_returns_none_when_disabled():
    idle_cfg = MagicMock()
    idle_cfg.enabled = False
    cfg = _minimal_config(idle={"unsplash": idle_cfg})
    assert build_idle_source(cfg) is None


def test_build_idle_source_returns_instance_when_enabled():
    idle_cfg = MagicMock()
    idle_cfg.enabled = True

    fake_cls = MagicMock(return_value=MagicMock())
    cfg = _minimal_config(idle={"unsplash": idle_cfg})

    with patch("mediainfo.registries.IDLE_CLASSES", {"unsplash": fake_cls}):
        result = build_idle_source(cfg)

    fake_cls.assert_called_once_with(idle_cfg)
    assert result is fake_cls.return_value


def test_build_idle_source_returns_none_for_empty():
    cfg = _minimal_config()
    assert build_idle_source(cfg) is None


def test_build_idle_source_wraps_multiple_enabled_sources_in_composite():
    from mediainfo.idle.composite import CompositeIdleWallpaperSource

    unsplash_cfg = MagicMock()
    unsplash_cfg.enabled = True
    lastfm_cfg = MagicMock()
    lastfm_cfg.enabled = True

    fake_unsplash_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    fake_lastfm_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    cfg = _minimal_config(idle={"unsplash": unsplash_cfg, "lastfm": lastfm_cfg})

    with patch(
        "mediainfo.registries.IDLE_CLASSES",
        {"unsplash": fake_unsplash_cls, "lastfm": fake_lastfm_cls},
    ):
        result = build_idle_source(cfg)

    assert isinstance(result, CompositeIdleWallpaperSource)
    assert result.sources == [
        fake_unsplash_cls.return_value,
        fake_lastfm_cls.return_value,
    ]
    assert result.mode == "priority"


def test_build_idle_source_orders_by_idle_priority():
    from mediainfo.idle.composite import CompositeIdleWallpaperSource

    unsplash_cfg = MagicMock(enabled=True)
    lastfm_cfg = MagicMock(enabled=True)
    fake_unsplash_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    fake_lastfm_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    cfg = _minimal_config(
        idle={"unsplash": unsplash_cfg, "lastfm": lastfm_cfg},
        idle_priority=["lastfm", "unsplash"],
    )

    with patch(
        "mediainfo.registries.IDLE_CLASSES",
        {"unsplash": fake_unsplash_cls, "lastfm": fake_lastfm_cls},
    ):
        result = build_idle_source(cfg)

    assert isinstance(result, CompositeIdleWallpaperSource)
    assert result.sources == [
        fake_lastfm_cls.return_value,
        fake_unsplash_cls.return_value,
    ]


def test_build_idle_source_appends_unlisted_enabled_sources_after_priority_list():
    unsplash_cfg = MagicMock(enabled=True)
    lastfm_cfg = MagicMock(enabled=True)
    library_cfg = MagicMock(enabled=True)
    fake_unsplash_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    fake_lastfm_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    fake_library_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    cfg = _minimal_config(
        idle={"unsplash": unsplash_cfg, "lastfm": lastfm_cfg, "library": library_cfg},
        idle_priority=["lastfm"],  # unsplash/library not listed
    )

    with patch(
        "mediainfo.registries.IDLE_CLASSES",
        {
            "unsplash": fake_unsplash_cls,
            "lastfm": fake_lastfm_cls,
            "library": fake_library_cls,
        },
    ):
        result = build_idle_source(cfg)

    assert result.sources == [
        fake_lastfm_cls.return_value,
        fake_unsplash_cls.return_value,
        fake_library_cls.return_value,
    ]


def test_build_idle_source_passes_through_idle_mode():
    unsplash_cfg = MagicMock(enabled=True)
    lastfm_cfg = MagicMock(enabled=True)
    fake_unsplash_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    fake_lastfm_cls = MagicMock(return_value=MagicMock(rotation_interval_seconds=300))
    cfg = _minimal_config(
        idle={"unsplash": unsplash_cfg, "lastfm": lastfm_cfg},
        idle_mode="random",
    )

    with patch(
        "mediainfo.registries.IDLE_CLASSES",
        {"unsplash": fake_unsplash_cls, "lastfm": fake_lastfm_cls},
    ):
        result = build_idle_source(cfg)

    assert result.mode == "random"


def test_build_idle_source_passes_library_to_library_aware_classes():
    idle_cfg = MagicMock()
    idle_cfg.enabled = True
    fake_cls = MagicMock(return_value=MagicMock())
    fake_cls.capabilities = frozenset({"library"})
    fake_library = MagicMock()
    cfg = _minimal_config(idle={"library": idle_cfg})

    with patch("mediainfo.registries.IDLE_CLASSES", {"library": fake_cls}):
        result = build_idle_source(cfg, fake_library)

    fake_cls.assert_called_once_with(idle_cfg, fake_library)
    assert result is fake_cls.return_value


# ---------------------------------------------------------------------------
# start_orchestrator
# ---------------------------------------------------------------------------


def test_start_orchestrator_starts_and_returns_orchestrator():
    cfg = _minimal_config(
        priority=[],
        sources={},
        enrichers={},
        idle={},
        poll_interval_seconds=5,
        rotation_interval_seconds=30,
    )
    outputs = []
    cache = MagicMock()

    mock_orch = MagicMock()
    with patch("mediainfo.wiring.Orchestrator", return_value=mock_orch) as mock_cls:
        result = start_orchestrator(cfg, outputs, cache)

    mock_cls.assert_called_once()
    mock_orch.start.assert_called_once()
    assert result is mock_orch


def test_start_orchestrator_uses_supplied_mediadata_store_instead_of_building_one():
    cfg = _minimal_config(
        priority=[],
        sources={},
        enrichers={},
        idle={},
        poll_interval_seconds=5,
        rotation_interval_seconds=30,
    )
    store = MagicMock()

    with (
        patch("mediainfo.wiring.Orchestrator", return_value=MagicMock()),
        patch("mediainfo.wiring.build_mediadata_store") as build_fn,
    ):
        start_orchestrator(cfg, [], MagicMock(), mediadata_store=store)

    build_fn.assert_not_called()


# ---------------------------------------------------------------------------
# build_artwork_overrides
# ---------------------------------------------------------------------------


def test_build_artwork_overrides_returns_none_when_disabled():
    cfg = MagicMock()
    cfg.overrides.enabled = False
    assert build_artwork_overrides(cfg) is None


def test_build_artwork_overrides_returns_store_when_enabled(tmp_path):
    from mediainfo.artwork_overrides import ArtworkOverrideStore

    cfg = MagicMock()
    cfg.overrides.enabled = True
    cfg.overrides.dir = str(tmp_path / "overrides")

    store = build_artwork_overrides(cfg)

    assert isinstance(store, ArtworkOverrideStore)
    assert store.dir == tmp_path / "overrides"


def test_build_app_services_populates_every_field():
    orch = MagicMock()
    orch.get_health.return_value = {
        "active_source": None,
        "source_last_polled_ago": {},
        "output_errors": {},
        "source_backoff_seconds": {},
        "uptime_seconds": 0,
        "poll_interval_seconds": 5,
        "rotation_interval_seconds": 30,
        "now_playing": None,
        "idle_wallpapers_loaded": 0,
        "hitster_safe": False,
    }
    orch.sources = []
    orch.enrichers = []
    orch.idle_source = None
    orch.get_hitster_safe = MagicMock()
    orch.set_hitster_safe = MagicMock()
    orch.request_artwork_refresh = MagicMock()
    orch.request_rotation_now = MagicMock()

    cfg = MagicMock()
    cfg.sources = {}
    cfg.outputs = {}
    cfg.enrichers = {}
    cfg.idle = {}

    history = MagicMock()
    overrides = MagicMock()
    mediadata_store = MagicMock()

    services = build_app_services(orch, cfg, [], history, overrides, mediadata_store)

    assert services.history is history
    assert services.overrides is overrides
    assert services.mediadata_store is mediadata_store
    assert services.get_hitster_safe is orch.get_hitster_safe
    assert services.set_hitster_safe is orch.set_hitster_safe
    assert services.request_artwork_refresh is orch.request_artwork_refresh
    assert services.request_rotation_now is orch.request_rotation_now
    # health_provider is built by health.make_health_provider() (its own
    # payload shape is covered by test_health.py) - just confirm one was
    # actually built and closes over this orch/config/outputs.
    assert callable(services.health_provider)


def test_attach_services_calls_attach_on_every_output():
    services = MagicMock()
    outputs = [MagicMock(), MagicMock(), MagicMock()]

    attach_services(outputs, services)

    for output in outputs:
        output.attach.assert_called_once_with(services)


def test_attach_services_handles_no_outputs():
    attach_services([], MagicMock())  # must not raise

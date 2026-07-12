"""Tests for the AI-generated artwork enricher."""

import base64
from unittest.mock import MagicMock, patch

from mediainfo.config import AiArtworkConfig
from mediainfo.enrichers.ai_artwork import AiArtworkEnricher
from mediainfo.models import NowPlaying

_FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake-png-data"


def _config(**kwargs):
    return AiArtworkConfig(enabled=True, **kwargs)


def _music(
    artist="Queen",
    title="Bohemian Rhapsody",
    album="A Night at the Opera",
    genres=None,
    ai_text=None,
):
    return NowPlaying(
        source="kodi",
        media_type="music",
        title=title,
        subtitle=artist,
        album=album,
        genres=genres or [],
        ai_text=ai_text or {},
    )


def _movie(title="Inception"):
    return NowPlaying(source="kodi", media_type="movie", title=title)


def _sd_response(image_bytes=_FAKE_PNG_BYTES, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"images": [base64.b64encode(image_bytes).decode("ascii")]}
    return resp


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_skips_non_music_media_types(mock_post, tmp_path):
    enricher = AiArtworkEnricher(_config(), tmp_path)
    np = _movie()

    enricher.enrich(np)

    mock_post.assert_not_called()
    assert np.images == []


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_skips_when_artist_missing(mock_post, tmp_path):
    enricher = AiArtworkEnricher(_config(), tmp_path)
    np = _music(artist="")

    enricher.enrich(np)

    mock_post.assert_not_called()


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_generates_and_appends_artwork(mock_post, tmp_path):
    mock_post.return_value = _sd_response()
    enricher = AiArtworkEnricher(_config(), tmp_path)
    np = _music()

    enricher.enrich(np)

    assert len(np.images) == 1
    artwork = np.images[0]
    assert artwork.url.startswith("file://")
    assert artwork.label == "AI-generated artwork"
    cached_path = artwork.url.removeprefix("file://")
    assert open(cached_path, "rb").read() == _FAKE_PNG_BYTES


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_uses_configured_host_port_and_params(mock_post, tmp_path):
    mock_post.return_value = _sd_response()
    enricher = AiArtworkEnricher(
        _config(
            host="192.168.1.60", port=7861, steps=30, width=768, height=768, timeout_seconds=60
        ),
        tmp_path,
    )

    enricher.enrich(_music())

    args, kwargs = mock_post.call_args
    assert args[0] == "http://192.168.1.60:7861/sdapi/v1/txt2img"
    assert kwargs["json"]["steps"] == 30
    assert kwargs["json"]["width"] == 768
    assert kwargs["json"]["height"] == 768
    assert kwargs["timeout"] == 60


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_prompt_never_includes_lyrics(mock_post, tmp_path):
    """Critical: the roadmap explicitly forbids sending lyrics to the model."""
    mock_post.return_value = _sd_response()
    enricher = AiArtworkEnricher(_config(), tmp_path)
    np = _music(ai_text={"mood": "wistful"})
    np.lyrics = "Is this the real life, is this just fantasy"
    np.synced_lyrics = "[00:01.00]Is this the real life"

    enricher.enrich(np)

    prompt = mock_post.call_args.kwargs["json"]["prompt"]
    assert "Is this the real life" not in prompt
    assert "fantasy" not in prompt


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_prompt_uses_mood_from_ai_text_when_present(mock_post, tmp_path):
    mock_post.return_value = _sd_response()
    enricher = AiArtworkEnricher(_config(), tmp_path)

    enricher.enrich(_music(ai_text={"mood": "wistful and grand"}, genres=["Rock"]))

    prompt = mock_post.call_args.kwargs["json"]["prompt"]
    assert "wistful and grand" in prompt
    assert "Rock" in prompt


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_prompt_falls_back_to_genre_without_mood(mock_post, tmp_path):
    mock_post.return_value = _sd_response()
    enricher = AiArtworkEnricher(_config(), tmp_path)

    enricher.enrich(_music(genres=["Jazz"]))

    prompt = mock_post.call_args.kwargs["json"]["prompt"]
    assert "Jazz" in prompt


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_prompt_has_a_generic_fallback_with_no_metadata(mock_post, tmp_path):
    mock_post.return_value = _sd_response()
    enricher = AiArtworkEnricher(_config(), tmp_path)

    enricher.enrich(_music())

    prompt = mock_post.call_args.kwargs["json"]["prompt"]
    assert prompt  # non-empty, doesn't crash with no mood/genre


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_no_images_in_response_leaves_now_playing_unchanged(mock_post, tmp_path):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"images": []}
    mock_post.return_value = resp
    enricher = AiArtworkEnricher(_config(), tmp_path)
    np = _music()

    enricher.enrich(np)

    assert np.images == []


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_empty_base64_image_is_not_cached_or_applied(mock_post, tmp_path):
    # A present-but-empty base64 string decodes to b"" with no exception -
    # must not be written to disk, since `enrich()`'s cache-hit check is
    # just `if not path.exists()`: a 0-byte file would be reused forever.
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"images": [""]}
    mock_post.return_value = resp
    enricher = AiArtworkEnricher(_config(), tmp_path)
    np = _music()

    enricher.enrich(np)

    assert np.images == []
    assert list(tmp_path.glob("*.png")) == []

    # Not cached as a "hit" either, so a later play retries generation.
    enricher.enrich(_music())
    assert mock_post.call_count == 2


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_network_exception_does_not_raise(mock_post, tmp_path):
    mock_post.side_effect = RuntimeError("connection refused")
    enricher = AiArtworkEnricher(_config(), tmp_path)
    np = _music()

    enricher.enrich(np)  # must not raise (SD WebUI not running is expected/common)

    assert np.images == []


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_caches_generated_image_and_reuses_on_second_lookup(mock_post, tmp_path):
    mock_post.return_value = _sd_response()
    enricher = AiArtworkEnricher(_config(), tmp_path)

    first_np = _music()
    enricher.enrich(first_np)
    assert mock_post.call_count == 1

    mock_post.reset_mock()
    second_np = _music()
    enricher.enrich(second_np)

    mock_post.assert_not_called()
    assert len(second_np.images) == 1
    assert second_np.images[0].url == first_np.images[0].url


@patch("mediainfo.enrichers.ai_artwork.requests.post")
def test_different_songs_do_not_share_a_cached_file(mock_post, tmp_path):
    enricher = AiArtworkEnricher(_config(), tmp_path)

    mock_post.return_value = _sd_response(b"song-a-bytes")
    np_a = _music(title="Song A")
    enricher.enrich(np_a)

    mock_post.return_value = _sd_response(b"song-b-bytes")
    np_b = _music(title="Song B")
    enricher.enrich(np_b)

    assert mock_post.call_count == 2
    assert np_a.images[0].url != np_b.images[0].url


def test_cache_dir_is_created_on_construction(tmp_path):
    cache_dir = tmp_path / "ai_artwork"
    assert not cache_dir.exists()

    AiArtworkEnricher(_config(), cache_dir)

    assert cache_dir.exists()

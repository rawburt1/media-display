"""Tests for the Ollama AI text enricher."""

import json
from unittest.mock import MagicMock, patch

from mediainfo.config import OllamaTextConfig
from mediainfo.enrichers.ollama_text import OllamaTextEnricher
from mediainfo.models import NowPlaying
from mediainfo.text_cache import TextCache


def _config(**kwargs):
    return OllamaTextConfig(enabled=True, **kwargs)


def _music(
    artist="Queen", title="Bohemian Rhapsody", album="A Night at the Opera",
    genres=None, year=None, lyrics="", synced_lyrics="",
):
    return NowPlaying(
        source="kodi", media_type="music", title=title, subtitle=artist, album=album,
        genres=genres or [], year=year, lyrics=lyrics, synced_lyrics=synced_lyrics,
    )


def _movie(title="Inception"):
    return NowPlaying(source="kodi", media_type="movie", title=title)


def _ollama_response(fields: dict, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"response": json.dumps(fields)}
    return resp


_ALL_FIELDS = {
    "mood": "wistful and grand",
    "description": "A theatrical rock ballad blending operatic and hard rock styles.",
    "fun_fact": "The song is known for its unconventional structure with no repeating chorus.",
    "context": "A standout track from Queen's fourth studio album.",
}


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_skips_non_music_media_types(mock_post):
    enricher = OllamaTextEnricher(_config())
    np = _movie()

    enricher.enrich(np)

    mock_post.assert_not_called()
    assert np.ai_text == {}


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_skips_when_artist_missing(mock_post):
    enricher = OllamaTextEnricher(_config())
    np = _music(artist="")

    enricher.enrich(np)

    mock_post.assert_not_called()


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_generates_and_applies_all_four_fields(mock_post):
    mock_post.return_value = _ollama_response(_ALL_FIELDS)
    enricher = OllamaTextEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.ai_text == _ALL_FIELDS
    args, kwargs = mock_post.call_args
    assert args[0] == "http://localhost:11434/api/generate"
    assert kwargs["json"]["model"] == "llama3.2"
    assert kwargs["json"]["format"] == "json"
    assert kwargs["timeout"] == 30


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_uses_configured_host_port_model_and_timeout(mock_post):
    mock_post.return_value = _ollama_response(_ALL_FIELDS)
    enricher = OllamaTextEnricher(
        _config(host="192.168.1.50", port=11555, model="mistral", timeout_seconds=5)
    )

    enricher.enrich(_music())

    args, kwargs = mock_post.call_args
    assert args[0] == "http://192.168.1.50:11555/api/generate"
    assert kwargs["json"]["model"] == "mistral"
    assert kwargs["timeout"] == 5


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_prompt_never_includes_lyrics(mock_post):
    """Critical: the roadmap explicitly forbids sending lyrics to the model."""
    mock_post.return_value = _ollama_response(_ALL_FIELDS)
    enricher = OllamaTextEnricher(_config())
    np = _music(
        lyrics="Is this the real life, is this just fantasy",
        synced_lyrics="[00:01.00]Is this the real life",
    )

    enricher.enrich(np)

    prompt = mock_post.call_args.kwargs["json"]["prompt"]
    assert "Is this the real life" not in prompt
    assert "fantasy" not in prompt
    # Sanity check the prompt does include the metadata it's meant to use.
    assert "Bohemian Rhapsody" in prompt
    assert "Queen" in prompt


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_prompt_includes_genres_and_year_when_present(mock_post):
    mock_post.return_value = _ollama_response(_ALL_FIELDS)
    enricher = OllamaTextEnricher(_config())

    enricher.enrich(_music(genres=["Rock", "Progressive"], year=1975))

    prompt = mock_post.call_args.kwargs["json"]["prompt"]
    assert "Rock, Progressive" in prompt
    assert "1975" in prompt


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_partial_response_only_applies_present_fields(mock_post):
    mock_post.return_value = _ollama_response({"mood": "energetic"})
    enricher = OllamaTextEnricher(_config())
    np = _music()

    enricher.enrich(np)

    assert np.ai_text == {"mood": "energetic"}


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_non_dict_json_response_is_ignored(mock_post):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"response": json.dumps(["not", "a", "dict"])}
    mock_post.return_value = resp
    enricher = OllamaTextEnricher(_config())
    np = _music()

    enricher.enrich(np)  # must not raise

    assert np.ai_text == {}


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_invalid_json_response_does_not_raise(mock_post):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"response": "not valid json{{{"}
    mock_post.return_value = resp
    enricher = OllamaTextEnricher(_config())
    np = _music()

    enricher.enrich(np)  # must not raise

    assert np.ai_text == {}


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_network_exception_does_not_raise(mock_post):
    mock_post.side_effect = RuntimeError("connection refused")
    enricher = OllamaTextEnricher(_config())
    np = _music()

    enricher.enrich(np)  # must not raise (Ollama not running is expected/common)

    assert np.ai_text == {}


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_works_without_a_cache(mock_post):
    mock_post.return_value = _ollama_response(_ALL_FIELDS)
    enricher = OllamaTextEnricher(_config(), cache=None)

    enricher.enrich(_music())  # must not raise


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_caches_result_and_reuses_on_second_lookup(mock_post, tmp_path):
    mock_post.return_value = _ollama_response(_ALL_FIELDS)
    cache = TextCache(tmp_path)
    enricher = OllamaTextEnricher(_config(), cache=cache)

    enricher.enrich(_music())
    assert mock_post.call_count == 1

    mock_post.reset_mock()
    second_np = _music()
    enricher.enrich(second_np)

    mock_post.assert_not_called()
    assert second_np.ai_text == _ALL_FIELDS


@patch("mediainfo.enrichers.ollama_text.requests.post")
def test_different_songs_do_not_share_a_cache_entry(mock_post, tmp_path):
    cache = TextCache(tmp_path)
    enricher = OllamaTextEnricher(_config(), cache=cache)

    mock_post.return_value = _ollama_response({"mood": "song A mood"})
    enricher.enrich(_music(title="Song A"))

    mock_post.return_value = _ollama_response({"mood": "song B mood"})
    np_b = _music(title="Song B")
    enricher.enrich(np_b)

    assert mock_post.call_count == 2
    assert np_b.ai_text == {"mood": "song B mood"}

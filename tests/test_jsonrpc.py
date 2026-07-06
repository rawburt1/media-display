"""Tests for the shared JSON-RPC 2.0-over-HTTP client."""

from unittest.mock import MagicMock, patch

import pytest

from mediainfo.sources.jsonrpc import JsonRpcClient, JsonRpcError


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_call_returns_result(mock_post):
    response = MagicMock()
    response.json.return_value = {"result": {"foo": "bar"}}
    mock_post.return_value = response

    client = JsonRpcClient("http://example.com/rpc")
    result = client.call("some.method", ["a", "b"])

    assert result == {"foo": "bar"}
    payload = mock_post.call_args.kwargs["json"]
    assert payload == {"jsonrpc": "2.0", "id": 1, "method": "some.method", "params": ["a", "b"]}


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_call_defaults_params_to_empty_list(mock_post):
    response = MagicMock()
    response.json.return_value = {"result": None}
    mock_post.return_value = response

    JsonRpcClient("http://example.com/rpc").call("some.method")

    assert mock_post.call_args.kwargs["json"]["params"] == []


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_call_raises_jsonrpc_error_on_error_field(mock_post):
    response = MagicMock()
    response.json.return_value = {"error": {"code": -1, "message": "nope"}}
    mock_post.return_value = response

    client = JsonRpcClient("http://example.com/rpc")
    with pytest.raises(JsonRpcError):
        client.call("some.method")


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_call_raises_on_http_error(mock_post):
    response = MagicMock()
    response.raise_for_status.side_effect = Exception("HTTP 500")
    mock_post.return_value = response

    client = JsonRpcClient("http://example.com/rpc")
    with pytest.raises(Exception):
        client.call("some.method")


@patch("mediainfo.sources.jsonrpc.requests.post")
def test_call_passes_auth_and_timeout(mock_post):
    response = MagicMock()
    response.json.return_value = {"result": None}
    mock_post.return_value = response

    client = JsonRpcClient("http://example.com/rpc", auth=("user", "pass"), timeout=3)
    client.call("some.method")

    assert mock_post.call_args.kwargs["auth"] == ("user", "pass")
    assert mock_post.call_args.kwargs["timeout"] == 3

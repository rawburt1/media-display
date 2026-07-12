"""Tests for the shared optional HTTP Basic Auth helper."""

from flask import Flask

from mediainfo.config import AuthConfig
from mediainfo.web_auth import install_auth, is_loopback_address, is_private_address


# ---------------------------------------------------------------------------
# is_private_address
# ---------------------------------------------------------------------------


def test_private_ipv4_ranges_are_exempt():
    assert is_private_address("10.0.0.1")
    assert is_private_address("172.16.0.1")
    assert is_private_address("172.31.255.255")
    assert is_private_address("192.168.1.42")


def test_loopback_is_exempt():
    assert is_private_address("127.0.0.1")
    assert is_private_address("::1")


def test_ipv6_unique_local_is_exempt():
    assert is_private_address("fc00::1")
    assert is_private_address("fd12:3456:789a::1")


def test_public_addresses_are_not_exempt():
    assert not is_private_address("8.8.8.8")
    assert not is_private_address("1.1.1.1")
    assert not is_private_address("2001:4860:4860::8888")


def test_addresses_just_outside_private_ranges_are_not_exempt():
    assert not is_private_address("172.15.255.255")
    assert not is_private_address("172.32.0.0")
    assert not is_private_address("11.0.0.1")  # outside 10.0.0.0/8


def test_missing_address_is_not_exempt():
    assert not is_private_address(None)
    assert not is_private_address("")


def test_unparseable_address_is_not_exempt():
    assert not is_private_address("not-an-ip")


def test_ipv6_zone_id_is_stripped_before_parsing():
    # fe80::/10 (link-local) isn't in our exempt list, but a zone id
    # suffix (e.g. from a scoped address) must not raise.
    assert is_private_address("fe80::1%eth0") is False


# ---------------------------------------------------------------------------
# install_auth
# ---------------------------------------------------------------------------


def _app(auth_config):
    app = Flask(__name__)

    @app.get("/secret")
    def secret():
        return "ok"

    install_auth(app, auth_config)
    return app


def test_disabled_auth_allows_any_request():
    app = _app(AuthConfig(enabled=False))
    client = app.test_client()
    resp = client.get("/secret", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
    assert resp.status_code == 200


def test_none_config_allows_any_request():
    app = _app(None)
    client = app.test_client()
    resp = client.get("/secret", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
    assert resp.status_code == 200


def test_private_address_is_never_challenged():
    app = _app(AuthConfig(enabled=True, username="u", password="p"))
    client = app.test_client()
    resp = client.get("/secret", environ_overrides={"REMOTE_ADDR": "192.168.1.5"})
    assert resp.status_code == 200


def test_public_address_without_credentials_is_rejected():
    app = _app(AuthConfig(enabled=True, username="u", password="p"))
    client = app.test_client()
    resp = client.get("/secret", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers


def test_public_address_with_correct_credentials_is_allowed():
    app = _app(AuthConfig(enabled=True, username="u", password="p"))
    client = app.test_client()
    resp = client.get(
        "/secret",
        environ_overrides={"REMOTE_ADDR": "8.8.8.8"},
        auth=("u", "p"),
    )
    assert resp.status_code == 200


def test_public_address_with_wrong_credentials_is_rejected():
    app = _app(AuthConfig(enabled=True, username="u", password="p"))
    client = app.test_client()
    resp = client.get(
        "/secret",
        environ_overrides={"REMOTE_ADDR": "8.8.8.8"},
        auth=("u", "wrong"),
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# is_loopback_address
# ---------------------------------------------------------------------------


def test_loopback_ipv4_is_loopback():
    assert is_loopback_address("127.0.0.1")
    assert is_loopback_address("127.255.255.255")


def test_loopback_ipv6_is_loopback():
    assert is_loopback_address("::1")


def test_lan_address_is_not_loopback():
    assert not is_loopback_address("192.168.1.1")
    assert not is_loopback_address("10.0.0.1")


def test_docker_bridge_is_not_loopback():
    assert not is_loopback_address("172.17.0.1")


def test_missing_is_not_loopback():
    assert not is_loopback_address(None)
    assert not is_loopback_address("")

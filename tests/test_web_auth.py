"""Tests for the shared optional HTTP Basic Auth helper."""

from flask import Flask

from mediainfo.config import AuthConfig
from mediainfo.web_auth import (
    _host_without_port,
    hash_password,
    install_auth,
    is_loopback_address,
    is_private_address,
    verify_password,
)


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
# hash_password / verify_password (M1 - see
# docs/architecture-usability-review-2026-07.md)
# ---------------------------------------------------------------------------


def test_hash_password_does_not_return_the_plaintext():
    assert hash_password("hunter2") != "hunter2"


def test_verify_password_accepts_the_correct_plaintext():
    assert verify_password("hunter2", hash_password("hunter2"))


def test_verify_password_rejects_the_wrong_plaintext():
    assert not verify_password("wrong", hash_password("hunter2"))


def test_verify_password_rejects_an_empty_stored_hash():
    # auth.password's own default - "no credential configured yet" must
    # never accidentally match anything, including an empty guess.
    assert not verify_password("", "")
    assert not verify_password("hunter2", "")


def test_verify_password_rejects_a_malformed_stored_hash_without_raising():
    assert not verify_password("hunter2", "not-a-real-hash")


def test_hash_password_is_salted_so_the_same_password_hashes_differently():
    assert hash_password("hunter2") != hash_password("hunter2")


# ---------------------------------------------------------------------------
# install_auth
# ---------------------------------------------------------------------------


def _app(auth_config):
    app = Flask(__name__)

    @app.get("/secret")
    def secret():
        return "ok"

    @app.post("/secret")
    @app.put("/secret")
    @app.delete("/secret")
    def mutate_secret():
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
    app = _app(AuthConfig(enabled=True, username="u", password=hash_password("p")))
    client = app.test_client()
    resp = client.get("/secret", environ_overrides={"REMOTE_ADDR": "192.168.1.5"})
    assert resp.status_code == 200


def test_public_address_without_credentials_is_rejected():
    app = _app(AuthConfig(enabled=True, username="u", password=hash_password("p")))
    client = app.test_client()
    resp = client.get("/secret", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers


def test_public_address_with_correct_credentials_is_allowed():
    app = _app(AuthConfig(enabled=True, username="u", password=hash_password("p")))
    client = app.test_client()
    resp = client.get(
        "/secret",
        environ_overrides={"REMOTE_ADDR": "8.8.8.8"},
        auth=("u", "p"),
    )
    assert resp.status_code == 200


def test_public_address_with_wrong_credentials_is_rejected():
    app = _app(AuthConfig(enabled=True, username="u", password=hash_password("p")))
    client = app.test_client()
    resp = client.get(
        "/secret",
        environ_overrides={"REMOTE_ADDR": "8.8.8.8"},
        auth=("u", "wrong"),
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# _require_csrf_header / _require_trusted_host - always installed,
# independent of AuthConfig (auth disabled/None in most of these, to prove
# that's true).
# ---------------------------------------------------------------------------


def test_mutating_request_without_csrf_header_is_rejected():
    app = _app(None)
    client = app.test_client()
    resp = client.post("/secret")
    assert resp.status_code == 403


def test_mutating_request_with_csrf_header_is_allowed():
    app = _app(None)
    client = app.test_client()
    resp = client.post("/secret", headers={"X-Requested-With": "XMLHttpRequest"})
    assert resp.status_code == 200


def test_put_and_delete_also_require_csrf_header():
    app = _app(None)
    client = app.test_client()
    assert client.put("/secret").status_code == 403
    assert client.delete("/secret").status_code == 403
    headers = {"X-Requested-With": "XMLHttpRequest"}
    assert client.put("/secret", headers=headers).status_code == 200
    assert client.delete("/secret", headers=headers).status_code == 200


def test_get_request_never_needs_the_csrf_header():
    app = _app(None)
    client = app.test_client()
    resp = client.get("/secret")
    assert resp.status_code == 200


def test_wrong_csrf_header_value_is_rejected():
    app = _app(None)
    client = app.test_client()
    resp = client.post("/secret", headers={"X-Requested-With": "something-else"})
    assert resp.status_code == 403


def test_untrusted_host_header_is_rejected():
    app = _app(None)
    client = app.test_client()
    resp = client.get("/secret", headers={"Host": "evil.example"})
    assert resp.status_code == 403


def test_untrusted_host_header_with_port_is_rejected():
    app = _app(None)
    client = app.test_client()
    resp = client.get("/secret", headers={"Host": "evil.example:8094"})
    assert resp.status_code == 403


def test_localhost_host_header_is_trusted():
    app = _app(None)
    client = app.test_client()
    resp = client.get("/secret", headers={"Host": "localhost:8094"})
    assert resp.status_code == 200


def test_private_ip_host_header_is_trusted():
    app = _app(None)
    client = app.test_client()
    resp = client.get("/secret", headers={"Host": "192.168.1.40:8094"})
    assert resp.status_code == 200


def test_bracketed_ipv6_host_header_is_trusted():
    app = _app(None)
    client = app.test_client()
    resp = client.get("/secret", headers={"Host": "[::1]:8094"})
    assert resp.status_code == 200


def test_host_without_port_strips_plain_port():
    assert _host_without_port("192.168.1.40:8094") == "192.168.1.40"


def test_host_without_port_leaves_bare_host_alone():
    assert _host_without_port("localhost") == "localhost"


def test_host_without_port_handles_bracketed_ipv6():
    assert _host_without_port("[::1]:8094") == "::1"
    assert _host_without_port("[::1]") == "::1"


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

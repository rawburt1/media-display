"""Tests for mediainfo.outputs.http_server.SharedHttpServer - one shared
Flask app/server for every Flask-based output (H1 in
docs/architecture-usability-review-2026-07.md). This covers the class in
isolation with throwaway blueprints; see tests/test_wiring.py for how
wiring.instantiate_outputs() drives it from real output config, and
tests/test_smoke.py for the full config.example.yaml wiring proof.
"""

import urllib.error
import urllib.request

from flask import Blueprint

from mediainfo.config import AuthConfig, HttpServerConfig
from mediainfo.outputs.http_server import SharedHttpServer


def _server(port=0):
    return SharedHttpServer(HttpServerConfig(host="127.0.0.1", port=port), AuthConfig())


def _get(server, path):
    url = f"http://127.0.0.1:{server._server.server_port}{path}"
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, resp.read().decode()


def test_registered_blueprint_is_reachable_at_its_prefix():
    server = _server()
    bp = Blueprint("thing", __name__)

    @bp.get("/hello")
    def hello():
        return "hi"

    server.register_blueprint(bp, url_prefix="/thing")
    server.start()
    try:
        status, body = _get(server, "/thing/hello")
        assert status == 200
        assert body == "hi"
    finally:
        server.stop()


def test_root_mounted_blueprint_uses_empty_prefix():
    server = _server()
    bp = Blueprint("root", __name__)

    @bp.get("/")
    def index():
        return "root page"

    server.register_blueprint(bp, url_prefix="")
    server.start()
    try:
        status, body = _get(server, "/")
        assert status == 200
        assert body == "root page"
    finally:
        server.stop()


def test_stop_actually_terminates_the_server_thread():
    server = _server()
    bp = Blueprint("thing", __name__)

    @bp.get("/hello")
    def hello():
        return "hi"

    server.register_blueprint(bp, url_prefix="/thing")
    server.start()
    assert server._thread.is_alive()

    server.stop()

    assert not server._thread.is_alive()
    with_error = False
    try:
        _get(server, "/thing/hello")
    except OSError:
        with_error = True
    assert with_error  # nothing is listening on that port anymore


def test_stop_before_start_is_a_safe_no_op():
    server = _server()
    server.stop()  # must not raise


def test_name_override_avoids_flask_blueprint_name_collision():
    # Two instances of the same output type build blueprints with the same
    # constructor name (e.g. every ConfigUiOutput builds a Blueprint named
    # "thing" here) - Flask requires unique names across the app, so
    # wiring.py passes a distinguishing name for every instance past the
    # first. Regression test for a real bug found while wiring this up:
    # passing name=None explicitly (instead of omitting it) breaks the
    # first instance's own endpoint name ("None.index" instead of
    # "thing.index") - see register_blueprint()'s own comment.
    server = _server()

    bp1 = Blueprint("thing", __name__)

    @bp1.get("/")
    def index1():
        return "one"

    bp2 = Blueprint("thing", __name__)

    @bp2.get("/")
    def index2():
        return "two"

    server.register_blueprint(bp1, url_prefix="/thing")
    server.register_blueprint(bp2, url_prefix="/thing-second", name="thing_1")
    server.start()
    try:
        status1, body1 = _get(server, "/thing/")
        status2, body2 = _get(server, "/thing-second/")
        assert (status1, body1) == (200, "one")
        assert (status2, body2) == (200, "two")
    finally:
        server.stop()


def test_csrf_header_guard_is_installed_once_for_the_shared_app():
    """install_auth() is called once in __init__, not per-blueprint - a
    mutating request without the CSRF header must still be rejected."""
    server = _server()
    bp = Blueprint("thing", __name__)

    @bp.post("/save")
    def save():
        return "saved"

    server.register_blueprint(bp, url_prefix="/thing")
    server.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server._server.server_port}/thing/save", method="POST"
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "expected the CSRF-header guard to reject this request"
        except urllib.error.HTTPError as exc:
            assert exc.code == 403
    finally:
        server.stop()

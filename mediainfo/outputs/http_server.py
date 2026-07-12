"""One shared Flask app + one real HTTP server, used by every Flask-based
output (web/config/themes/info/feed/video/nest_hub) instead of each owning
its own `Flask(__name__)` app and `app.run()` dev server on its own port -
see H1 in docs/architecture-usability-review-2026-07.md.

Uses `werkzeug.serving.make_server()`, not a "real" production WSGI server
like waitress: waitress doesn't support flask_sock's WebSocket hijacking (it
never sets `werkzeug.socket`/`gunicorn.socket`/etc in the WSGI environ, which
`simple_websocket` requires to hijack the connection) - it would silently
break `/ws` on `web`/`themes`/`info`, curl-clean but broken the moment a
real browser opens one. `make_server()` is exactly what `Flask.run()` already
wraps today, so `/ws` keeps working exactly as it does now; the real gain
over `Flask.run()` is a genuine `.shutdown()` for graceful stop, which none
of the 7 previously-separate dev servers ever had (they just died with the
process).
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from flask import Blueprint, Flask
from flask_sock import Sock
from werkzeug.serving import BaseWSGIServer, make_server

from mediainfo.config import AuthConfig, HttpServerConfig
from mediainfo.web_auth import install_auth

logger = logging.getLogger(__name__)


class SharedHttpServer:
    """Owns the one Flask app, the one `flask_sock.Sock` instance, and the
    one server thread shared by every enabled Flask-based output."""

    def __init__(self, config: HttpServerConfig, auth_config: Optional[AuthConfig]):
        self.config = config
        self.app = Flask(__name__)
        self.sock = Sock(self.app)
        # Always the same shared config.auth object every output used to
        # pass individually - one registration instead of seven identical
        # ones, not a behavior change.
        install_auth(self.app, auth_config)
        self._server: Optional[BaseWSGIServer] = None
        self._thread: Optional[threading.Thread] = None

    def register_blueprint(self, blueprint: Blueprint, url_prefix: str) -> None:
        """Mount one output instance's blueprint at its wiring-computed
        path prefix ("" for the root-mounted output - see
        Output.root_mounted)."""
        self.app.register_blueprint(blueprint, url_prefix=url_prefix or None)

    def start(self) -> None:
        """Start serving in a daemon thread. Call once, after every enabled
        output's blueprint has already been registered - starting earlier
        would let requests race blueprint registration.
        """
        self._server = make_server(self.config.host, self.config.port, self.app, threaded=True)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        logger.info("Starting shared HTTP server on %s:%d", self.config.host, self.config.port)

    def stop(self) -> None:
        """Gracefully stop serving - unlike the old per-output dev servers,
        this actually terminates the listening thread instead of relying on
        the whole process exiting.
        """
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("Shared HTTP server stopped")

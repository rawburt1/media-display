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
        # static_folder=None: the app-level default static route (which
        # would otherwise point at mediainfo/outputs/ - the parent of every
        # output's own static/<name>/ subfolder) would register at the same
        # "/static/<path:filename>" URL pattern as config_ui's own
        # blueprint-scoped static route and silently shadow it (Werkzeug
        # resolves the conflict by whichever rule was added first, not by
        # specificity - the app's own default is always added first).
        # Outputs that want static files declare their own blueprint-scoped
        # static_folder/static_url_path instead (see ConfigUiOutput).
        self.app = Flask(__name__, static_folder=None)
        self.sock = Sock(self.app)
        # Always the same shared config.auth object every output used to
        # pass individually - one registration instead of seven identical
        # ones, not a behavior change.
        install_auth(self.app, auth_config)
        self._server: Optional[BaseWSGIServer] = None
        self._thread: Optional[threading.Thread] = None

    def register_blueprint(
        self, blueprint: Blueprint, url_prefix: str, name: Optional[str] = None
    ) -> None:
        """Mount one output instance's blueprint at its wiring-computed
        path prefix ("" for the root-mounted output - see
        Output.root_mounted).

        `name` overrides the blueprint's own registration name (Flask
        requires unique names across the app, but every instance of a
        given output type builds a blueprint with the same constructor
        name, e.g. every ConfigUiOutput's blueprint is named "config") -
        wiring.py passes a per-instance-unique name here when more than
        one instance of a type is configured. Every converted output's
        templates/JS use Flask's relative url_for('.endpoint') form
        specifically so this is invisible to them regardless of what name
        ends up registered.
        """
        # name=None must not be passed at all, not even explicitly: Flask's
        # register_blueprint(**options) does options.get("name", ...)
        # internally, which does NOT fall back to the blueprint's own name
        # when the key is present with value None - it registers a
        # literally broken "None.<endpoint>" name instead. Confirmed via a
        # standalone repro against Flask 3.1.3.
        kwargs = {"url_prefix": url_prefix or None}
        if name is not None:
            kwargs["name"] = name
        self.app.register_blueprint(blueprint, **kwargs)

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

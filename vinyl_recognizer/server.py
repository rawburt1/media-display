"""Flask app exposing the recognizer's current result."""

from __future__ import annotations

from flask import Flask, jsonify

from vinyl_recognizer.service import RecognizerService


def create_app(service: RecognizerService) -> Flask:
    app = Flask(__name__)

    @app.route("/now-playing")
    def now_playing():
        return jsonify(service.get_now_playing())

    return app

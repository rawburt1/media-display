"""Flask app exposing the recognizer's current result and on-demand recognition."""

from __future__ import annotations

from flask import Flask, jsonify, request

from vinyl_recognizer.service import RecognizerService


def create_app(service: RecognizerService) -> Flask:
    app = Flask(__name__)

    @app.route("/now-playing")
    def now_playing():
        return jsonify(service.get_now_playing())

    @app.route("/recognize", methods=["POST"])
    def recognize():
        wav_bytes = request.data
        if not wav_bytes:
            return jsonify({"error": "No audio data"}), 400
        result = service.recognize(wav_bytes)
        return jsonify(result or {})

    return app

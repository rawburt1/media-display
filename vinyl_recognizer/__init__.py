"""Standalone audio-recognition service for a turntable line-in.

Runs on the machine where a Behringer UCA202 (or similar USB audio
interface) is connected to a turntable's output. Periodically records short
clips, sends them to AudD for recognition, and serves the latest result over
HTTP for `pixoo_media`'s `VinylSource` to poll.
"""

__version__ = "0.1.0"

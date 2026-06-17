"""Entry point: python -m vinyl_recognizer [--config config.yaml]"""

from __future__ import annotations

import argparse
import logging

from vinyl_recognizer.config import RecognizerConfig
from vinyl_recognizer.server import create_app
from vinyl_recognizer.service import RecognizerService


def main() -> None:
    parser = argparse.ArgumentParser(description="Turntable audio recognition service")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="List available audio input devices and exit",
    )
    args = parser.parse_args()

    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return

    config = RecognizerConfig.load(args.config)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    service = RecognizerService(config)
    service.start()

    app = create_app(service)
    app.run(host=config.host, port=config.port)


if __name__ == "__main__":
    main()

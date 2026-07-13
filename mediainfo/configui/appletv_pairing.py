"""Apple TV pairing wizard for the config UI: the same pyatv-based flow as
`python -m mediainfo auth appletv` (see __main__.py), but reachable from
the browser without shell/docker-exec access.

Split out of config_ui.py. Pairing is async (pyatv) and inherently a
multi-step wizard (start -> enter/confirm PIN -> finish), so it gets its
own short-lived background event loop thread per pairing attempt, created
in start() and torn down in finish()/cancel(). Only one pairing attempt is
tracked at a time, which is fine for a single-operator local admin tool.

`run_async`/`stop_loop` are injected rather than implemented here because
ConfigUiOutput._run_appletv_async/_stop_appletv_loop are monkeypatched
directly by tests (to run coroutines with plain asyncio.run() instead of a
real background loop+thread) - keeping them defined on ConfigUiOutput and
passing them in here means that patch target keeps working unchanged.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional

from mediainfo.config import Config
from mediainfo.config_backup import backup_config_file
from mediainfo.configui.config_yaml_io import _dump_config, _read_config

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class _AppleTvSession:
    """An in-progress pairing attempt, with the resources needed to finish
    or cancel it. The event loop/thread must outlive the request that
    started the pairing, since pyatv's PairingHandler keeps background
    network state tied to the loop it was created on.
    """

    loop: asyncio.AbstractEventLoop
    thread: threading.Thread
    pairing: Any  # pyatv.interface.PairingHandler
    protocol_name: str
    device_name: str
    manual_pin: Optional[int] = None


class AppleTvPairingManager:
    def __init__(
        self,
        config_path: Path,
        lock: threading.Lock,
        run_async: Callable[..., Any],
        stop_loop: Callable[[asyncio.AbstractEventLoop, threading.Thread], None],
    ):
        self.config_path = config_path
        self._lock = lock
        self._run_async = run_async
        self._stop_loop = stop_loop
        self._appletv_lock = threading.Lock()
        self._session: Optional[_AppleTvSession] = None

    def start(self, host: str, protocol_name: str) -> dict:
        with self._appletv_lock:
            if self._session is not None:
                raise RuntimeError("A pairing attempt is already in progress - cancel it first.")
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, daemon=True)
            thread.start()

        try:
            result = self._run_async(loop, self._do_pair_start(loop, host, protocol_name))
        except Exception:
            self._stop_loop(loop, thread)
            raise

        with self._appletv_lock:
            self._session = _AppleTvSession(
                loop=loop,
                thread=thread,
                pairing=result["pairing"],
                protocol_name=protocol_name,
                device_name=result["device_name"],
                manual_pin=result["manual_pin"],
            )

        return {
            "device_name": result["device_name"],
            "protocol": protocol_name,
            "device_provides_pin": result["device_provides_pin"],
            "manual_pin": result["manual_pin"],
        }

    @staticmethod
    async def _do_pair_start(loop, host: str, protocol_name: str) -> dict:
        import pyatv

        protocols = {"companion": pyatv.const.Protocol.Companion, "mrp": pyatv.const.Protocol.MRP}
        protocol = protocols.get(protocol_name)
        if protocol is None:
            raise ValueError(f"Unknown protocol: {protocol_name!r} (expected companion or mrp)")

        results = await pyatv.scan(loop, hosts=[host], timeout=5)
        if not results:
            raise RuntimeError(f"No Apple TV found at {host}")
        conf = results[0]

        pairing = await pyatv.pair(conf, protocol, loop)
        await pairing.begin()

        manual_pin = None
        if not pairing.device_provides_pin:
            manual_pin = 1234
            pairing.pin(manual_pin)

        return {
            "pairing": pairing,
            "device_name": conf.name,
            "device_provides_pin": pairing.device_provides_pin,
            "manual_pin": manual_pin,
        }

    def finish(self, pin: Optional[str]) -> dict:
        with self._appletv_lock:
            session = self._session
        if session is None:
            raise RuntimeError('No pairing in progress - click "Start pairing" first.')

        try:
            credentials = self._run_async(session.loop, self._do_pair_finish(session, pin))
        finally:
            with self._appletv_lock:
                self._session = None
            self._stop_loop(session.loop, session.thread)

        field = f"{session.protocol_name}_credentials"
        self._save_credentials(field, credentials)
        return {"protocol": session.protocol_name, "field": field, "credentials": credentials}

    @staticmethod
    async def _do_pair_finish(session: _AppleTvSession, pin: Optional[str]) -> str:
        if session.pairing.device_provides_pin:
            if not pin:
                raise ValueError("Enter the PIN shown on the Apple TV.")
            session.pairing.pin(int(pin))

        await session.pairing.finish()

        if not session.pairing.has_paired:
            await session.pairing.close()
            raise RuntimeError("Pairing failed - check the PIN and try again.")

        credentials = session.pairing.service.credentials
        await session.pairing.close()
        return credentials

    def cancel(self) -> None:
        with self._appletv_lock:
            session = self._session
            self._session = None
        if session is None:
            return
        try:
            self._run_async(session.loop, session.pairing.close())
        except Exception:
            logger.exception("Error closing cancelled Apple TV pairing session")
        self._stop_loop(session.loop, session.thread)

    def _save_credentials(self, field: str, value: str) -> None:
        with self._lock:
            data = _read_config(self.config_path)
            section = data.setdefault("sources", {})
            entry = section.get("appletv")
            entry = entry if isinstance(entry, dict) else {}
            entry[field] = value
            entry["enabled"] = True
            section["appletv"] = entry

            Config.from_dict(data)

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            backup_config_file(self.config_path)
            with self.config_path.open("w", encoding="utf-8") as f:
                f.write(_dump_config(data))

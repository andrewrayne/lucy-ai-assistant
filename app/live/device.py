"""The owner's Mac, as seen from the server.

When the Jarvis app is connected, tools can ask it to do things (take a
screenshot, click, type, open an app, control Spotify). Each request gets an
id; Jarvis answers with {"type": "device_result", "id": ..., ...}.

Only one Jarvis connection is kept: a newer one replaces the older one.
"""

import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

OFFLINE = "Jarvis (the Mac app) is offline, so I can't reach the owner's Mac right now."
DEFAULT_TIMEOUT = 20

SendJson = Callable[[dict], Awaitable[None]]


class DeviceOffline(Exception):
    pass


class MacDevice:
    def __init__(self) -> None:
        self._send: SendJson | None = None
        self._owner: object | None = None  # the connection that registered _send
        self._pending: dict[str, asyncio.Future] = {}
        self._ids = itertools.count(1)

    @property
    def online(self) -> bool:
        return self._send is not None

    def attach(self, connection: object, send_json: SendJson) -> None:
        self._fail_pending("Jarvis reconnected")
        self._owner, self._send = connection, send_json
        log.info("Jarvis connected")

    def detach(self, connection: object) -> None:
        if self._owner is connection:
            self._owner, self._send = None, None
            self._fail_pending("Jarvis disconnected")
            log.info("Jarvis disconnected")

    def resolve(self, message: dict) -> None:
        future = self._pending.pop(str(message.get("id")), None)
        if future and not future.done():
            future.set_result(message)

    async def request(self, action: str, timeout: float = DEFAULT_TIMEOUT, **params) -> dict:
        """Ask the Mac to do one thing and wait for its answer."""
        if self._send is None:
            raise DeviceOffline(OFFLINE)
        request_id = str(next(self._ids))
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            await self._send({"type": "device", "id": request_id, "action": action, **params})
            result = await asyncio.wait_for(future, timeout)
        except TimeoutError:
            return {"ok": False, "error": f"The Mac didn't answer '{action}' in time."}
        finally:
            self._pending.pop(request_id, None)
        if result.get("disconnected"):
            raise DeviceOffline(OFFLINE)
        return result

    def _fail_pending(self, reason: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_result({"ok": False, "disconnected": True, "error": reason})
        self._pending.clear()


mac = MacDevice()

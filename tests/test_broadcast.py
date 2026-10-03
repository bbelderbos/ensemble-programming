import asyncio
from typing import cast

from starlette.websockets import WebSocket, WebSocketDisconnect

from main import ConnectionManager


class FakeSocket:
    def __init__(self, alive: bool = True):
        self.alive = alive
        self.sent: list[str] = []

    async def send_text(self, message: str) -> None:
        if not self.alive:
            raise WebSocketDisconnect(code=1006)
        self.sent.append(message)


def test_a_closed_connection_does_not_stop_the_broadcast():
    manager = ConnectionManager()
    dead, alive = FakeSocket(alive=False), FakeSocket()
    manager.active_connections["s1"] = cast(list[WebSocket], [dead, alive])

    asyncio.run(manager.broadcast("s1", "hello"))

    assert alive.sent == ["hello"]
    assert manager.active_connections["s1"] == [alive]

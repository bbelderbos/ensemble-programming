import json
from contextlib import contextmanager

from fastapi.testclient import TestClient

import main
from main import app

client = TestClient(app)


@contextmanager
def join(username):
    with client.websocket_connect("/ws/rotation/s1") as rotation:
        rotation.send_text(
            json.dumps({"type": "join", "username": username, "participate": True})
        )
        rotation.receive_text()
        yield


def code(username, content):
    return json.dumps({"type": "code", "username": username, "content": content})


def test_code_change_reaches_peers_but_not_sender():
    with (
        join("alice"),
        client.websocket_connect("/ws/s1") as sender,
        client.websocket_connect("/ws/s1") as peer,
    ):
        sender.send_text(code("alice", "x = 1"))
        sender.send_text(json.dumps({"type": "typing", "username": "alice"}))

        assert json.loads(peer.receive_text()) == {"type": "code", "content": "x = 1"}
        assert json.loads(sender.receive_text())["type"] == "typing"


def test_only_the_driver_can_edit():
    with (
        join("alice"),
        join("bob"),
        client.websocket_connect("/ws/s1") as editor,
        client.websocket_connect("/ws/s1") as peer,
    ):
        editor.send_text(code("bob", "hijack()"))
        editor.send_text(code("alice", "x = 1"))

        assert json.loads(peer.receive_text())["content"] == "x = 1"


def test_joining_late_loads_the_current_code():
    main.redis_client.set(main.key("s1", "code"), "x = 1")

    with client.websocket_connect("/ws/s1") as latecomer:
        assert json.loads(latecomer.receive_text()) == {
            "type": "code",
            "content": "x = 1",
        }

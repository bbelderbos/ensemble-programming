import json

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_code_change_reaches_peers_but_not_sender():
    with (
        client.websocket_connect("/ws/s1") as sender,
        client.websocket_connect("/ws/s1") as peer,
    ):
        sender.send_text(json.dumps({"type": "code", "content": "x = 1"}))
        sender.send_text(json.dumps({"type": "typing", "username": "alice"}))

        assert json.loads(peer.receive_text()) == {"type": "code", "content": "x = 1"}
        assert json.loads(sender.receive_text())["type"] == "typing"

import os
import socket
import threading
import time

import fakeredis
import pytest
import uvicorn

os.environ.setdefault("DATABASE_URL", "sqlite://")

import main  # noqa: E402  (needs DATABASE_URL set first)


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    monkeypatch.setattr(
        main, "redis_client", fakeredis.FakeRedis(decode_responses=True)
    )
    # Timers from earlier tests belong to event loops that no longer run
    monkeypatch.setattr(main, "segment_timers", {})


@pytest.fixture(scope="session")
def live_server():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join()

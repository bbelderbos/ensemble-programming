import os

import fakeredis
import pytest

os.environ.setdefault("DATABASE_URL", "sqlite://")

import main  # noqa: E402  (needs DATABASE_URL set first)


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    monkeypatch.setattr(
        main, "redis_client", fakeredis.FakeRedis(decode_responses=True)
    )
    # Timers from earlier tests belong to event loops that no longer run
    monkeypatch.setattr(main, "segment_timers", {})

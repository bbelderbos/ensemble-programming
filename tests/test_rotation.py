import json
import time

import pytest
from fastapi.testclient import TestClient

import main
from rotation import Roles, assign_roles

client = TestClient(main.app)


@pytest.mark.parametrize(
    ("rotation", "segment", "expected"),
    [
        ([], 0, Roles(driver=None, navigator=None, timekeeper=None)),
        (["ann"], 0, Roles(driver="ann", navigator=None, timekeeper="ann")),
        (["ann", "bob"], 0, Roles(driver="ann", navigator="bob", timekeeper="bob")),
        (
            ["ann", "bob", "cy"],
            0,
            Roles(driver="ann", navigator="bob", timekeeper="cy"),
        ),
        (
            ["ann", "bob", "cy"],
            1,
            Roles(driver="bob", navigator="cy", timekeeper="ann"),
        ),
        (
            ["ann", "bob", "cy", "di"],
            5,
            Roles(driver="bob", navigator="cy", timekeeper="di"),
        ),
    ],
)
def test_assign_roles(rotation, segment, expected):
    assert assign_roles(rotation, segment) == expected


def test_navigator_becomes_next_driver():
    people = ["ann", "bob", "cy", "di"]
    for segment in range(8):
        assert (
            assign_roles(people, segment + 1).driver
            == assign_roles(people, segment).navigator
        )


def send(ws, **message):
    ws.send_text(json.dumps(message))


def receive_state(ws):
    return json.loads(ws.receive_text())


def test_observers_sit_in_without_a_role():
    with client.websocket_connect("/ws/rotation/s1") as ws:
        send(ws, type="join", username="ann", participate=True)
        receive_state(ws)
        send(ws, type="join", username="obi", participate=False)
        state = receive_state(ws)

    assert state["participants"] == ["ann"]
    assert state["observers"] == ["obi"]
    assert state["driver"] == "ann"
    assert "obi" not in (state["navigator"], state["timekeeper"])


def test_session_starts_on_break_until_timekeeper_starts():
    with client.websocket_connect("/ws/rotation/s1") as ws:
        send(ws, type="join", username="ann", participate=True)
        receive_state(ws)
        send(ws, type="join", username="bob", participate=True)
        state = receive_state(ws)
        assert state["remaining"] is None

        send(ws, type="start", username="ann")  # driver, not timekeeper
        send(ws, type="start", username="bob")
        state = receive_state(ws)

    assert state["timekeeper"] == "bob"
    assert state["remaining"] == main.ROTATION_SECONDS


def test_segment_end_rotates_roles_and_breaks(monkeypatch):
    monkeypatch.setattr(main, "ROTATION_SECONDS", 0.05)
    with client.websocket_connect("/ws/rotation/s1") as ws:
        for name in ("ann", "bob", "cy"):
            send(ws, type="join", username=name, participate=True)
            receive_state(ws)
        send(ws, type="start", username="cy")
        running = receive_state(ws)
        after = receive_state(ws)

    assert (running["driver"], running["navigator"]) == ("ann", "bob")
    assert after["remaining"] is None
    assert (after["driver"], after["navigator"], after["timekeeper"]) == (
        "bob",
        "cy",
        "ann",
    )


def test_leaving_removes_you_from_the_rotation():
    with client.websocket_connect("/ws/rotation/s1") as ws:
        send(ws, type="join", username="ann", participate=True)
        receive_state(ws)
        with client.websocket_connect("/ws/rotation/s1") as other:
            send(other, type="join", username="bob", participate=True)
            receive_state(ws)
        state = receive_state(ws)

    assert state["participants"] == ["ann"]


def seed(session_id, participants, segment=0, ends_at=None):
    main.redis_client.rpush(main.key(session_id, "participants"), *participants)
    main.redis_client.set(main.key(session_id, "segment"), segment)
    if ends_at is not None:
        main.redis_client.set(main.key(session_id, "ends_at"), ends_at)


def test_segment_that_expired_during_a_restart_ends_on_reconnect():
    seed("s1", ["ann", "bob"], ends_at=time.time() - 60)

    with client.websocket_connect("/ws/rotation/s1") as ws:
        state = receive_state(ws)

    assert state["remaining"] is None
    assert state["driver"] == "bob"


def test_segment_interrupted_by_a_restart_still_ends_on_time(monkeypatch):
    seed("s1", ["ann", "bob"], ends_at=time.time() + 0.05)

    with client.websocket_connect("/ws/rotation/s1") as ws:
        state = receive_state(ws)

    assert state["remaining"] is None
    assert state["driver"] == "bob"


def test_driver_leaving_hands_over_to_the_navigator():
    seed("s1", ["ann", "bob", "cy"], segment=1)  # bob drives
    with client.websocket_connect("/ws/rotation/s1") as ws:
        send(ws, type="join", username="bob", participate=True)
        receive_state(ws)
    with client.websocket_connect("/ws/rotation/s1") as ws:
        send(ws, type="join", username="dee", participate=False)
        state = receive_state(ws)

    assert state["participants"] == ["ann", "cy"]
    assert state["driver"] == "cy"


@pytest.mark.parametrize("segment", [1, 4])  # bob drives in both
def test_someone_leaving_does_not_change_the_current_driver(segment):
    seed("s1", ["ann", "bob", "cy"], segment=segment)
    with client.websocket_connect("/ws/rotation/s1") as ws:
        send(ws, type="join", username="ann", participate=True)
        receive_state(ws)
    with client.websocket_connect("/ws/rotation/s1") as ws:
        send(ws, type="join", username="dee", participate=False)
        state = receive_state(ws)

    assert state["participants"] == ["bob", "cy"]
    assert state["driver"] == "bob"


def test_rejoining_does_not_duplicate_you():
    with client.websocket_connect("/ws/rotation/s1") as ws:
        send(ws, type="join", username="ann", participate=True)
        receive_state(ws)
        send(ws, type="join", username="ann", participate=True)
        state = receive_state(ws)

    assert state["participants"] == ["ann"]

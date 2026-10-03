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


def test_timekeeper_can_rotate_early_which_resets_the_clock(monkeypatch):
    monkeypatch.setattr(main, "ROTATION_SECONDS", 0.2)
    with client.websocket_connect("/ws/rotation/s1") as ws:
        for name in ("ann", "bob", "cy"):
            send(ws, type="join", username=name, participate=True)
            receive_state(ws)
        send(ws, type="start", username="cy")
        receive_state(ws)

        send(ws, type="rotate", username="ann")  # driver, not timekeeper
        send(ws, type="rotate", username="cy")
        rotated = receive_state(ws)
        # The cancelled segment timer must not rotate a second time
        time.sleep(0.3)
        send(ws, type="join", username="dee", participate=False)
        later = receive_state(ws)

    assert rotated["remaining"] is None
    assert (rotated["driver"], rotated["timekeeper"]) == ("bob", "ann")
    assert later["driver"] == "bob"


def test_rotating_during_a_break_moves_to_the_next_driver():
    with client.websocket_connect("/ws/rotation/s1") as ws:
        for name in ("ann", "bob"):
            send(ws, type="join", username=name, participate=True)
            receive_state(ws)
        send(ws, type="rotate", username="bob")
        state = receive_state(ws)

    assert (state["driver"], state["timekeeper"]) == ("bob", "ann")


def join_all(ws, *names):
    for name in names:
        send(ws, type="join", username=name, participate=True)
        receive_state(ws)


def test_timekeeper_sets_the_segment_length():
    with client.websocket_connect("/ws/rotation/s1") as ws:
        join_all(ws, "ann", "bob")
        send(ws, type="set_length", username="ann", minutes=10)  # not timekeeper
        for invalid in (0, 31, "5", 2.5):
            send(ws, type="set_length", username="bob", minutes=invalid)
        send(ws, type="set_length", username="bob", minutes=10)
        state = receive_state(ws)
        assert state["segment_seconds"] == 600

        send(ws, type="start", username="bob")
        state = receive_state(ws)

    assert state["remaining"] == 600


def test_keep_rotating_starts_the_next_segment_without_a_break(monkeypatch):
    monkeypatch.setattr(main, "ROTATION_SECONDS", 0.05)
    with client.websocket_connect("/ws/rotation/s1") as ws:
        join_all(ws, "ann", "bob")
        send(ws, type="set_auto", username="ann", on=True)  # not timekeeper
        send(ws, type="set_auto", username="bob", on=True)
        assert receive_state(ws)["auto"] is True

        send(ws, type="start", username="bob")
        receive_state(ws)
        after = receive_state(ws)

    assert after["driver"] == "bob"
    assert after["remaining"] is not None


def test_anyone_in_the_rotation_can_pause_and_resume(monkeypatch):
    monkeypatch.setattr(main, "ROTATION_SECONDS", 0.1)
    with client.websocket_connect("/ws/rotation/s1") as ws:
        join_all(ws, "ann", "bob")
        send(ws, type="join", username="obi", participate=False)
        receive_state(ws)
        send(ws, type="start", username="bob")
        receive_state(ws)

        send(ws, type="pause", username="obi")  # observers can't pause
        send(ws, type="pause", username="ann")
        paused = receive_state(ws)
        # A paused clock must not end the segment
        time.sleep(0.2)
        send(ws, type="resume", username="obi")
        send(ws, type="resume", username="ann")
        resumed = receive_state(ws)

    assert paused["remaining"] is None
    assert 0 < paused["paused"] <= 0.1
    assert resumed["driver"] == "ann"
    assert resumed["paused"] is None
    assert resumed["remaining"] is not None


def test_rotating_while_paused_clears_the_pause():
    with client.websocket_connect("/ws/rotation/s1") as ws:
        join_all(ws, "ann", "bob")
        send(ws, type="start", username="bob")
        receive_state(ws)
        send(ws, type="pause", username="ann")
        receive_state(ws)
        send(ws, type="rotate", username="bob")
        state = receive_state(ws)

    assert state["paused"] is None
    assert state["driver"] == "bob"

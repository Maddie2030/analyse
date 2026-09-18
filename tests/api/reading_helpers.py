"""Reading command setup for capability tests; ordering tests use explicit bodies."""

from uuid import uuid4

from helpers import assert_status


def open_chapter(session, path, expected_revision=None):
    if expected_revision is None:
        current = session.get(path, timeout=15)
        assert_status(current, 200)
        expected_revision = current.json()["revision"]
    response = session.post(
        f"{path}/open",
        json={"command_id": str(uuid4()), "expected_revision": expected_revision},
        timeout=15,
    )
    assert_status(response, 200)
    state = response.json()
    assert state["accepted"] is True, state
    return state


def checkpoint_payload(state, last_page, scroll_position, *, completed_page=0):
    return {
        "command_id": str(uuid4()),
        "session_generation": state["session_generation"],
        "command_sequence": state["command_sequence"] + 1,
        "last_page": last_page,
        "scroll_position": scroll_position,
        "completed": completed_page > 0,
        "completed_page": completed_page,
    }

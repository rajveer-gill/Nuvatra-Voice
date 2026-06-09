"""main's in-mem appointment/message globals must stay aliased to the runtime
lists (same object) so routers and main share one store. Guards against a future
reassignment silently splitting them."""

import main
import runtime


def test_appointments_alias():
    assert main.appointments is runtime.appointments


def test_messages_alias():
    assert main.messages is runtime.messages


def test_mutation_is_shared():
    runtime.appointments.clear()
    runtime.appointments.append({"id": 999})
    try:
        assert main.appointments[-1]["id"] == 999  # same object
    finally:
        runtime.appointments.clear()

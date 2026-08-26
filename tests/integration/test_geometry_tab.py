from __future__ import annotations

import pytest

from tabs.geometry_tab import _schedule_on_event_loop

pytestmark = pytest.mark.integration


class FakeEventLoop:
    def __init__(self, *, running: bool = True):
        self.running = running
        self.callbacks = []

    def is_running(self):
        return self.running

    def call_soon_threadsafe(self, callback):
        self.callbacks.append(callback)


def test_geometry_completion_is_deferred_to_event_loop():
    loop = FakeEventLoop()
    completed = []

    assert _schedule_on_event_loop(loop, lambda: completed.append(True)) is True
    assert completed == []

    loop.callbacks[0]()

    assert completed == [True]


def test_geometry_completion_is_not_run_without_event_loop():
    completed = []

    assert _schedule_on_event_loop(None, lambda: completed.append(True)) is False
    assert completed == []

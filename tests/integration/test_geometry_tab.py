from __future__ import annotations

import pytest

from tabs.geometry_tab import _replace_geometry_preferences, _schedule_on_event_loop

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


def test_restored_geometry_preferences_replace_live_cache():
    current = {
        "library_selection": "old.stl.gz",
        "case_geometry_selections": {"aerofoil": "old.stl.gz"},
    }
    restored = {
        "preferred_mode": "case",
        "library_selection": "flange.stl.gz",
        "case_geometry_selections": {"aerofoil": "flange.stl.gz"},
    }

    selections = _replace_geometry_preferences(current, restored, "aerofoil")

    assert selections == ("flange.stl.gz", "flange.stl.gz")
    assert current == restored

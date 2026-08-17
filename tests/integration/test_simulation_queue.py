import threading
from pathlib import Path

import pytest

from backend.case.capabilities import CaseActionService
from backend.simulation_queue import SequentialSimulationQueue, SimulationJob
from tabs.run_log_tab import _reconcile_interrupted_history


def make_job(job_id: int) -> SimulationJob:
    inspection = CaseActionService().inspect_case(None)
    return SimulationJob(
        id=job_id,
        case_name=f"case-{job_id}",
        case_path=Path(f"case-{job_id}"),
        command_label="Allrun",
        action_ids=("allrun",),
        inspection=inspection,
        docker_image="openfoam:test",
        openfoam_version="12",
        queued_at="2026-08-13 00:00:00",
    )


def test_simulation_queue_runs_jobs_one_at_a_time_in_fifo_order():
    first_started = threading.Event()
    release_first = threading.Event()
    executed = []
    concurrent = 0
    max_concurrent = 0
    execution_lock = threading.Lock()

    def execute(job):
        nonlocal concurrent, max_concurrent
        with execution_lock:
            concurrent += 1
            max_concurrent = max(max_concurrent, concurrent)
        executed.append(job.id)
        if job.id == 1:
            first_started.set()
            assert release_first.wait(timeout=2)
        with execution_lock:
            concurrent -= 1

    queue = SequentialSimulationQueue(execute)
    queue.enqueue(make_job(1))
    assert first_started.wait(timeout=2)
    queue.enqueue(make_job(2))
    queue.enqueue(make_job(3))

    snapshot = queue.snapshot()
    assert snapshot.active is not None
    assert snapshot.active.id == 1
    assert [job.id for job in snapshot.pending] == [2, 3]

    release_first.set()
    assert queue.wait_until_idle(timeout=2)
    assert executed == [1, 2, 3]
    assert max_concurrent == 1


def test_simulation_queue_can_cancel_waiting_jobs_without_stopping_active_job():
    first_started = threading.Event()
    release_first = threading.Event()
    executed = []

    def execute(job):
        executed.append(job.id)
        if job.id == 1:
            first_started.set()
            assert release_first.wait(timeout=2)

    queue = SequentialSimulationQueue(execute)
    queue.enqueue(make_job(1))
    assert first_started.wait(timeout=2)
    queue.enqueue(make_job(2))
    queue.enqueue(make_job(3))

    removed = queue.cancel(2)
    assert removed is not None and removed.id == 2
    assert [job.id for job in queue.clear_pending()] == [3]

    release_first.set()
    assert queue.wait_until_idle(timeout=2)
    assert executed == [1]


def test_simulation_queue_rejects_duplicate_job_ids():
    started = threading.Event()
    release = threading.Event()

    def execute(_job):
        started.set()
        assert release.wait(timeout=2)

    queue = SequentialSimulationQueue(execute)
    job = make_job(1)
    queue.enqueue(job)
    assert started.wait(timeout=2)
    with pytest.raises(ValueError, match="already queued"):
        queue.enqueue(job)
    release.set()
    assert queue.wait_until_idle(timeout=2)


def test_restart_marks_non_durable_queue_states_as_interrupted():
    history = [
        {"id": 1, "status": "Queued", "end_time": None},
        {"id": 2, "status": "Running", "end_time": None},
        {"id": 3, "status": "Completed", "end_time": "already-set"},
    ]

    reconciled, changed = _reconcile_interrupted_history(history)

    assert changed is True
    assert [entry["status"] for entry in reconciled] == [
        "Interrupted",
        "Interrupted",
        "Completed",
    ]
    assert reconciled[0]["end_time"]
    assert history[0]["status"] == "Queued"


def test_queue_publishes_waiting_state_before_running_state():
    release = threading.Event()
    snapshots = []

    def execute(_job):
        assert release.wait(timeout=2)

    def on_change(snapshot):
        snapshots.append(
            (
                snapshot.active.id if snapshot.active else None,
                [job.id for job in snapshot.pending],
            )
        )

    queue = SequentialSimulationQueue(execute, on_change)
    queue.enqueue(make_job(1))

    assert snapshots[:2] == [(None, [1]), (1, [])]
    release.set()
    assert queue.wait_until_idle(timeout=2)


def test_queue_continues_after_executor_failure():
    executed = []

    def execute(job):
        executed.append(job.id)
        if job.id == 1:
            raise RuntimeError("failed job")

    queue = SequentialSimulationQueue(execute)
    queue.enqueue(make_job(1))
    queue.enqueue(make_job(2))

    assert queue.wait_until_idle(timeout=2)
    assert executed == [1, 2]

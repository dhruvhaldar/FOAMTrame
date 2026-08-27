from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from backend.case.capabilities import CaseInspection

logger = logging.getLogger("FOAMTrame")


@dataclass(frozen=True)
class SimulationJob:
    """A validated, immutable simulation request waiting for execution."""

    id: int
    case_name: str
    case_path: Path
    command_label: str
    action_ids: tuple[str, ...]
    inspection: CaseInspection
    docker_image: str
    openfoam_version: str
    queued_at: str
    safe_clean: bool = False

    def to_state(self, status: str) -> dict[str, object]:
        return {
            "id": self.id,
            "case_name": self.case_name,
            "command": self.command_label,
            "status": status,
            "queued_at": self.queued_at,
        }


@dataclass(frozen=True)
class QueueSnapshot:
    active: SimulationJob | None
    pending: tuple[SimulationJob, ...]


class SequentialSimulationQueue:
    """Run validated simulation jobs one at a time in FIFO order."""

    def __init__(
        self,
        executor: Callable[[SimulationJob], None],
        on_change: Callable[[QueueSnapshot], None] | None = None,
    ) -> None:
        self._executor = executor
        self._on_change = on_change
        self._lock = threading.Lock()
        self._pending: deque[SimulationJob] = deque()
        self._active: SimulationJob | None = None
        self._worker: threading.Thread | None = None

    def snapshot(self) -> QueueSnapshot:
        with self._lock:
            return QueueSnapshot(self._active, tuple(self._pending))

    def enqueue(self, job: SimulationJob) -> None:
        worker_to_start = None
        with self._lock:
            if (self._active is not None and self._active.id == job.id) or any(
                item.id == job.id for item in self._pending
            ):
                raise ValueError(f"Simulation job {job.id} is already queued")
            self._pending.append(job)
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._run,
                    name="foamtrame-simulation-queue",
                    daemon=True,
                )
                worker_to_start = self._worker
            snapshot = QueueSnapshot(self._active, tuple(self._pending))
        self._notify(snapshot)
        # Publish the queued state before the worker can publish a running state.
        # Otherwise a fast worker can leave consumers displaying a stale queue.
        if worker_to_start is not None:
            worker_to_start.start()

    def cancel(self, job_id: int) -> SimulationJob | None:
        removed = None
        with self._lock:
            retained: deque[SimulationJob] = deque()
            while self._pending:
                job = self._pending.popleft()
                if removed is None and job.id == job_id:
                    removed = job
                else:
                    retained.append(job)
            self._pending = retained
            snapshot = QueueSnapshot(self._active, tuple(self._pending))
        if removed is not None:
            self._notify(snapshot)
        return removed

    def clear_pending(self) -> tuple[SimulationJob, ...]:
        with self._lock:
            removed = tuple(self._pending)
            self._pending.clear()
            snapshot = QueueSnapshot(self._active, ())
        if removed:
            self._notify(snapshot)
        return removed

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        """Wait until there is no active or pending work.

        This is primarily useful for orderly shutdown and deterministic tests;
        normal UI callers receive state through ``on_change``.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            with self._lock:
                if self._active is None and not self._pending and self._worker is None:
                    return True
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def _notify(self, snapshot: QueueSnapshot) -> None:
        if self._on_change is None:
            return
        try:
            self._on_change(snapshot)
        except Exception:
            logger.exception("Simulation queue state callback failed")

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._worker = None
                    return
                job = self._pending.popleft()
                self._active = job
                snapshot = QueueSnapshot(job, tuple(self._pending))
            self._notify(snapshot)
            try:
                self._executor(job)
            except Exception:
                logger.exception("Unhandled simulation queue executor failure")
            finally:
                with self._lock:
                    self._active = None
                    snapshot = QueueSnapshot(None, tuple(self._pending))
                self._notify(snapshot)

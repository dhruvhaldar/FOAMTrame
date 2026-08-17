"""Microbenchmark FOAMTrame's filesystem-signature memoization.

Run from the repository root with:
    uv run --locked python benchmarks/benchmark_cachebox.py

The uncached measurements call the undecorated implementation; the cached
measurements warm the entry once and then exercise the normal hit path. Both
retain the same filesystem signature checks. Results are medians across
repeated rounds and are intentionally focused on deterministic local I/O rather
than Docker or rendering performance.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.case.capabilities import (  # noqa: E402
    _read_solver,
    _read_solver_file,
    _safe_clean_targets,
    _safe_clean_targets_for_signature,
)


def _measure(callable_, iterations: int, rounds: int = 7) -> float:
    samples = []
    for _ in range(rounds):
        started = time.perf_counter_ns()
        for _ in range(iterations):
            callable_()
        samples.append((time.perf_counter_ns() - started) / iterations)
    return statistics.median(samples)


def _row(name: str, uncached_ns: float, cached_ns: float) -> str:
    speedup = uncached_ns / cached_ns
    return (
        f"| {name} | {uncached_ns / 1_000:.2f} | "
        f"{cached_ns / 1_000:.2f} | {speedup:.1f}x |"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=2_000)
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="foamtrame-cache-benchmark-") as temp:
        case = Path(temp) / "case"
        system = case / "system"
        system.mkdir(parents=True)
        (system / "controlDict").write_text(
            "application foamRun;\nsolver incompressibleFluid;\n",
            encoding="utf-8",
        )
        for index in range(200):
            (case / f"{index + 1}.0").mkdir()

        control_dict = system / "controlDict"

        def uncached_solver() -> None:
            signature = control_dict.stat()
            _read_solver_file.__wrapped__(
                str(control_dict), signature.st_mtime_ns, signature.st_size
            )

        _read_solver_file.cache_clear()
        _read_solver(case)

        def cached_solver() -> None:
            _read_solver(case)

        def uncached_clean_scan() -> None:
            signature = case.stat()
            _safe_clean_targets_for_signature.__wrapped__(
                str(case), signature.st_mtime_ns
            )

        _safe_clean_targets_for_signature.cache_clear()
        _safe_clean_targets(case)

        def cached_clean_scan() -> None:
            _safe_clean_targets(case)

        solver_uncached = _measure(uncached_solver, args.iterations)
        solver_cached = _measure(cached_solver, args.iterations)
        scan_iterations = max(100, args.iterations // 10)
        scan_uncached = _measure(uncached_clean_scan, scan_iterations)
        scan_cached = _measure(cached_clean_scan, scan_iterations)

    print("| Operation | Uncached (us/call) | Cached (us/call) | Speedup |")
    print("|---|---:|---:|---:|")
    print(_row("controlDict solver metadata", solver_uncached, solver_cached))
    print(_row("safe-clean scan (200 outputs)", scan_uncached, scan_cached))


if __name__ == "__main__":
    main()

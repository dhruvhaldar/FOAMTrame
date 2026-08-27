"""Reproducible microbenchmarks for frequently polled FOAMTrame hot paths."""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time
from pathlib import Path

from backend.case.capabilities import CaseActionService
from backend.plots.realtime_plots import OpenFOAMFieldParser, clear_cache


def _measure(
    operation, *, repeats: int = 9, iterations: int = 20
) -> tuple[float, float]:
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        for _ in range(iterations):
            operation()
        samples.append((time.perf_counter() - started) / iterations)
    return statistics.median(samples), min(samples)


def benchmark_case_inspection(entry_count: int) -> tuple[float, float]:
    with tempfile.TemporaryDirectory(prefix="foamtrame-bench-") as directory:
        case = Path(directory) / "case"
        (case / "system").mkdir(parents=True)
        (case / "0").mkdir()
        (case / "system" / "controlDict").write_text(
            "application simpleFoam;\n", encoding="utf-8"
        )
        for index in range(1, entry_count + 1):
            (case / f"{index / 1000:g}").mkdir()

        service = CaseActionService()

        def inspect() -> None:
            service.inspect_case(case)

        return _measure(inspect)


def benchmark_residual_parser(step_count: int) -> tuple[float, float]:
    with tempfile.TemporaryDirectory(prefix="foamtrame-bench-") as directory:
        case = Path(directory)
        log_path = case / "log.foamRun"
        with log_path.open("w", encoding="utf-8") as stream:
            for index in range(step_count):
                stream.write(f"Time = {index * 0.001:g}\n")
                for field in ("Ux", "Uy", "Uz", "p", "k", "omega"):
                    stream.write(
                        f"smoothSolver: Solving for {field}, Initial residual = 1e-3, "
                        "Final residual = 1e-8, No Iterations 2\n"
                    )

        parser = OpenFOAMFieldParser(case)

        def parse_cold() -> None:
            clear_cache(str(case))
            parser.get_residuals_from_log()

        return _measure(parse_cold, repeats=7, iterations=1)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-entries", type=int, default=2_000)
    parser.add_argument("--residual-steps", type=int, default=10_000)
    args = parser.parse_args()

    median, best = benchmark_case_inspection(args.case_entries)
    print(f"case_inspection median={median * 1000:.3f}ms best={best * 1000:.3f}ms")
    median, best = benchmark_residual_parser(args.residual_steps)
    print(f"residual_parse median={median * 1000:.3f}ms best={best * 1000:.3f}ms")


if __name__ == "__main__":
    main()

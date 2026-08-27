"""Measure time until FOAMTrame serves its first HTTP response."""

from __future__ import annotations

import argparse
import os
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def benchmark_once(timeout: float, verbose: bool) -> float:
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="foamtrame-startup-") as temp_dir:
        temp_path = Path(temp_dir)
        output_path = temp_path / "server-output.log"
        environment = os.environ.copy()
        environment.update(
            {
                "FOAMTRAME_DATA_DIR": temp_dir,
                "FOAMTRAME_LOG_DIR": str(temp_path / "logs"),
                "FOAMTRAME_LOG_LEVEL": "INFO" if verbose else "WARNING",
                "FOAMTRAME_STARTUP_TIMING": "1" if verbose else "0",
                "FOAMTrame_SANDBOX_MODE": "1",
            }
        )
        started = time.perf_counter()
        with output_path.open("w+", encoding="utf-8") as output:
            process = subprocess.Popen(  # nosec: fixed local benchmark command
                [
                    sys.executable,
                    str(PROJECT_ROOT / "app.py"),
                    "--server",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=PROJECT_ROOT,
                env=environment,
                stdout=output,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                deadline = started + timeout
                while time.perf_counter() < deadline:
                    if process.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/", timeout=0.5
                        ) as response:
                            if response.status == 200:
                                elapsed = time.perf_counter() - started
                                if verbose:
                                    output.flush()
                                    output.seek(0)
                                    print(output.read().rstrip())
                                return elapsed
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.05)

                output.flush()
                output.seek(0)
                details = output.read()[-12000:]
                raise RuntimeError(
                    f"FOAMTrame was not ready within {timeout:.1f}s.\n{details}"
                )
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                if os.name == "nt":
                    time.sleep(0.25)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument(
        "--verbose", action="store_true", help="show internal startup checkpoints"
    )
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be at least 1")

    results = []
    for index in range(args.runs):
        elapsed = benchmark_once(args.timeout, args.verbose)
        results.append(elapsed)
        print(f"run {index + 1}: {elapsed:.3f}s")
    print(f"median: {statistics.median(results):.3f}s")
    if len(results) > 1:
        print(f"range: {min(results):.3f}s - {max(results):.3f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

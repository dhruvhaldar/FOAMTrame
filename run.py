from __future__ import annotations

import signal
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from runtime import settings

PROJECT_ROOT = Path(__file__).resolve().parent


def tee_stream(source: TextIO, console: TextIO, log_file: TextIO) -> None:
    """Copy complete child output to both the terminal and the daily run log."""
    for line in source:
        console.write(line)
        console.flush()
        log_file.write(line)
        log_file.flush()


def main(argv: list[str] | None = None) -> int:
    """Run FOAMTrame with signal forwarding and complete output capture."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    command = [sys.executable, str(PROJECT_ROOT / "app.py"), "--server", *arguments]
    run_log_path = settings.daily_log_dir / "run.log"
    run_log_path.parent.mkdir(parents=True, exist_ok=True)

    with run_log_path.open("a", encoding="utf-8", buffering=1) as log_file:
        started_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        header = f"\n{'=' * 80}\nFOAMTrame start {started_at}\nCommand: {' '.join(command)}\n"
        sys.stdout.write(header)
        sys.stdout.flush()
        log_file.write(header)

        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )

        def stop_child(_signum=None, _frame=None):
            if process.poll() is None:
                process.terminate()

        for signal_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
            if hasattr(signal, signal_name):
                signal.signal(getattr(signal, signal_name), stop_child)

        try:
            if process.stdout is not None:
                tee_stream(process.stdout, sys.stdout, log_file)
            return_code = process.wait()
        except KeyboardInterrupt:
            stop_child()
            try:
                return_code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                return_code = process.wait()

        ended_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        footer = f"FOAMTrame stopped {ended_at} (exit code {return_code})\n"
        sys.stdout.write(footer)
        sys.stdout.flush()
        log_file.write(footer)
        return return_code


if __name__ == "__main__":
    raise SystemExit(main())

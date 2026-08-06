from __future__ import annotations

import signal
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    """Run FOAMTrame with signal forwarding and the active Python environment."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    command = [sys.executable, str(PROJECT_ROOT / "app.py"), "--server", *arguments]
    process = subprocess.Popen(command, cwd=PROJECT_ROOT)

    def stop_child(_signum=None, _frame=None):
        if process.poll() is None:
            process.terminate()

    for signal_name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, signal_name):
            signal.signal(getattr(signal, signal_name), stop_child)

    try:
        return process.wait()
    except KeyboardInterrupt:
        stop_child()
        try:
            return process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait()


if __name__ == "__main__":
    raise SystemExit(main())

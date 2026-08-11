from __future__ import annotations

import importlib.util
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
HAS_RUNTIME = all(importlib.util.find_spec(name) for name in ("trame", "vtk"))

try:
    import pytest

    pytestmark = pytest.mark.smoke
except ImportError:  # unittest remains dependency-free
    pass


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@unittest.skipUnless(HAS_RUNTIME, "Full Trame/VTK runtime is not installed")
class ApplicationSmokeTest(unittest.TestCase):
    def test_server_starts_and_serves_html(self):
        port = free_port()
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "server-output.log"
            env = os.environ.copy()
            env.update(
                {
                    "FOAMTRAME_DATA_DIR": temp_dir,
                    "FOAMTRAME_LOG_DIR": str(Path(temp_dir) / "logs"),
                    "FOAMTRAME_LOG_LEVEL": "WARNING",
                    "FOAMTrame_SANDBOX_MODE": "1",
                }
            )
            with output_path.open("w+", encoding="utf-8") as output:
                process = subprocess.Popen(
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
                    env=env,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                try:
                    deadline = time.monotonic() + 120
                    response_body = ""
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            break
                        try:
                            with urllib.request.urlopen(
                                f"http://127.0.0.1:{port}/", timeout=2
                            ) as response:
                                response_body = response.read().decode("utf-8", "replace")
                                self.assertEqual(200, response.status)
                                break
                        except (urllib.error.URLError, TimeoutError):
                            time.sleep(0.5)

                    if not response_body:
                        output.flush()
                        output.seek(0)
                        self.fail(
                            "FOAMTrame did not become ready. Server output:\n"
                            + output.read()[-12000:]
                        )
                    self.assertIn("<html", response_body.lower())
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=15)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
                    # Windows may release rotating log/WAL handles a moment after
                    # the process handle signals. Give it a bounded grace period
                    # before TemporaryDirectory removes the runtime directory.
                    if os.name == "nt":
                        time.sleep(1.0)


if __name__ == "__main__":
    unittest.main()

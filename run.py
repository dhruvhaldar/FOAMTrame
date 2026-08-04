import subprocess
import sys
import os


def main():
    python_exe = sys.executable or os.path.join("venv", "Scripts", "python.exe")

    log_file = open("run.log", "w", encoding="utf-8", buffering=1)

    def log_msg(msg):
        try:
            print(msg, flush=True)
        except Exception:
            pass
        try:
            log_file.write(msg + "\n")
            log_file.flush()
        except Exception:
            pass

    log_msg("Starting Trame visualization server...")
    trame_process = subprocess.Popen(
        [python_exe, "app.py", "--server"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    import threading

    def forward_logs(process, prefix):
        try:
            while process.poll() is None or process.stdout:
                line = process.stdout.readline()
                if not line:
                    break
                log_msg(f"[{prefix}] {line.strip()}")
        except (ValueError, OSError):
            pass

    t = threading.Thread(target=forward_logs, args=(trame_process, "Trame"), daemon=True)
    t.start()

    try:
        while True:
            if trame_process.poll() is not None:
                log_msg("Trame server stopped.")
                break
            import time
            time.sleep(0.5)
    except KeyboardInterrupt:
        log_msg("Stopping server...")
    finally:
        try:
            trame_process.terminate()
            trame_process.wait(timeout=3)
        except Exception:
            try:
                trame_process.kill()
            except Exception:
                pass
        log_msg("Server stopped.")
        try:
            log_file.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()

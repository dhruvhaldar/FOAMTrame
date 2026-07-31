import subprocess
import sys
import os


def main():
    python_exe = sys.executable or os.path.join("venv", "Scripts", "python.exe")

    log_file = open("run.log", "w", encoding="utf-8", buffering=1)

    def log_msg(msg):
        print(msg)
        log_file.write(msg + "\n")

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
        for line in iter(process.stdout.readline, ""):
            log_msg(f"[{prefix}] {line.strip()}")

    t = threading.Thread(target=forward_logs, args=(trame_process, "Trame"), daemon=True)
    t.start()

    try:
        while True:
            if trame_process.poll() is not None:
                print("Trame server stopped.")
                break
            import time
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        trame_process.terminate()
        trame_process.wait()
        log_msg("Server stopped.")
        log_file.close()


if __name__ == "__main__":
    main()

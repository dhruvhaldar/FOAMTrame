import subprocess
import sys
import time
import os

def main():
    python_exe = sys.executable or os.path.join("venv", "Scripts", "python.exe")
    
    log_file = open("run.log", "w", encoding="utf-8", buffering=1)
    
    def log_msg(msg):
        print(msg)
        log_file.write(msg + "\n")

    log_msg("Starting Flask backend server...")
    flask_process = subprocess.Popen(
        [python_exe, "flask_server.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    # Wait briefly for Flask to spin up
    time.sleep(2)
    
    log_msg("Starting Trame visualization server...")
    trame_process = subprocess.Popen(
        [python_exe, "app.py", "--server"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )
    
    # Simple log forwarder thread
    def forward_logs(process, prefix):
        for line in iter(process.stdout.readline, ''):
            log_msg(f"[{prefix}] {line.strip()}")
            
    import threading
    t1 = threading.Thread(target=forward_logs, args=(flask_process, "Flask"), daemon=True)
    t2 = threading.Thread(target=forward_logs, args=(trame_process, "Trame"), daemon=True)
    t1.start()
    t2.start()
    
    try:
        while True:
            # Check if either process has exited
            if flask_process.poll() is not None:
                print("Flask server stopped.")
                break
            if trame_process.poll() is not None:
                print("Trame server stopped.")
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping both servers...")
    finally:
        flask_process.terminate()
        trame_process.terminate()
        flask_process.wait()
        trame_process.wait()
        log_msg("Both servers successfully stopped.")
        log_file.close()

if __name__ == "__main__":
    main()

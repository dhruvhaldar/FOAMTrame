import logging
import os
import platform
import posixpath
import shutil
import threading
from pathlib import Path
from flask import Flask, jsonify, request
from flask_compress import Compress

from app_state import (
    load_case_config,
    load_security_preferences,
    update_case_config,
)
from runtime import configure_logging
from security import configure_flask_security

configure_logging()
logger = logging.getLogger("FOAMTrameBackend")

app = Flask(__name__)
Compress(app)
configure_flask_security(app, load_security_preferences)

load_config = load_case_config
save_config = update_case_config

# Initialize config globals
config_data = load_config()
CASE_ROOT = config_data["CASE_ROOT"]
DOCKER_IMAGE = config_data["DOCKER_IMAGE"]
OPENFOAM_VERSION = config_data["OPENFOAM_VERSION"]
ACTIVE_CASE = config_data["ACTIVE_CASE"]

STARTUP_STATUS = {"status": "starting", "message": "Initializing..."}

def get_docker_client():
    import docker
    try:
        client = docker.from_env(timeout=5)
        client.ping()
        return client
    except Exception:
        return None

def run_startup_checks():
    global STARTUP_STATUS
    logger.info("Starting background startup checks...")
    STARTUP_STATUS = {"status": "running", "message": "Checking Docker integration..."}
    try:
        if not shutil.which("docker"):
            STARTUP_STATUS = {"status": "failed", "message": "Docker not installed or not in PATH."}
            logger.error("Docker not in PATH")
            return
            
        client = get_docker_client()
        if not client:
            STARTUP_STATUS = {"status": "failed", "message": "Cannot connect to Docker daemon. Make sure Docker Desktop is running."}
            logger.error("Cannot connect to Docker daemon")
            return

        try:
            images = client.images.list(name=DOCKER_IMAGE)
            if images:
                STARTUP_STATUS = {"status": "completed", "message": "Docker integration ready."}
                logger.info("Startup check completed successfully.")
            else:
                STARTUP_STATUS = {"status": "warning", "message": f"Docker image '{DOCKER_IMAGE}' not found on host."}
                logger.warning(f"Docker image '{DOCKER_IMAGE}' not found.")
        except Exception as e:
            logger.warning(f"Docker image check exception: {e}")
            STARTUP_STATUS = {"status": "warning", "message": f"Docker image check failed: {e}"}
    except Exception as e:
        logger.error(f"Unexpected error in startup checks: {e}")
        STARTUP_STATUS = {"status": "failed", "message": f"Startup check failed: {e}"}

# Run setup checks in background thread
threading.Thread(target=run_startup_checks, daemon=True).start()


@app.route("/get_case_root", methods=["GET"])
def get_case_root():
    return jsonify({"caseDir": CASE_ROOT})


@app.route("/get_active_case", methods=["GET"])
def get_active_case():
    return jsonify({"activeCase": ACTIVE_CASE})


@app.route("/set_active_case", methods=["POST"])
def set_active_case():
    global ACTIVE_CASE
    data = request.get_json() or {}
    case = data.get("activeCase", "")
    ACTIVE_CASE = case
    save_config({"ACTIVE_CASE": ACTIVE_CASE})
    return jsonify({"success": True, "activeCase": ACTIVE_CASE})


@app.route("/set_case", methods=["POST"])
def set_case():
    global CASE_ROOT
    data = request.get_json() or {}
    case_dir = data.get("caseDir")
    if not case_dir:
        return jsonify({"error": "No caseDir provided"}), 400
    try:
        path = Path(case_dir).resolve()
        path.mkdir(parents=True, exist_ok=True)
        CASE_ROOT = str(path)
        save_config({"CASE_ROOT": CASE_ROOT})
        return jsonify({"output": f"INFO::Case root set to: {CASE_ROOT}", "caseDir": CASE_ROOT})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/get_docker_config", methods=["GET"])
def get_docker_config():
    return jsonify({"dockerImage": DOCKER_IMAGE, "openfoamVersion": OPENFOAM_VERSION})


@app.route("/set_docker_config", methods=["POST"])
def set_docker_config():
    global DOCKER_IMAGE, OPENFOAM_VERSION
    data = request.get_json() or {}
    image = data.get("dockerImage")
    version = data.get("openfoamVersion")
    
    updates = {}
    if image:
        DOCKER_IMAGE = image
        updates["DOCKER_IMAGE"] = image
    if version:
        OPENFOAM_VERSION = version
        updates["OPENFOAM_VERSION"] = version
        
    if updates:
        save_config(updates)
        threading.Thread(target=run_startup_checks, daemon=True).start()
        
    return jsonify({
        "output": "INFO::Docker config updated",
        "dockerImage": DOCKER_IMAGE,
        "openfoamVersion": OPENFOAM_VERSION
    })


@app.route("/api/cases/list", methods=["GET"])
def list_cases():
    root = Path(CASE_ROOT)
    if not root.exists():
        return jsonify({"cases": []})
    try:
        cases = [entry.name for entry in os.scandir(str(root)) if entry.is_dir()]
        return jsonify({"cases": sorted(cases)})
    except Exception:
        return jsonify({"cases": []})


@app.route("/api/case/create", methods=["POST"])
def create_case():
    data = request.get_json() or {}
    name = data.get("caseName")
    if not name:
        return jsonify({"success": False, "message": "No case name specified"}), 400
        
    try:
        from backend.case.manager import CaseManager
        full_path = Path(CASE_ROOT) / name
        result = CaseManager.create_case_structure(full_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/tutorials", methods=["GET"])
def get_tutorials():
    client = get_docker_client()
    if not client:
        return jsonify({"tutorials": [], "error": "Docker not available."}), 503
        
    try:
        bashrc = f"/opt/openfoam{OPENFOAM_VERSION}/etc/bashrc"
        cmd = (
            f"source {bashrc} && "
            "tutorials_dir=${FOAM_TUTORIALS:-/opt/openfoam12/tutorials} && "
            "echo $tutorials_dir && "
            "find $tutorials_dir -mindepth 3 -maxdepth 3 \\( -type d -o -type l \\) \\( -name system -o -name constant \\) "
            "| sed 's|/[^/]*$||' | sort | uniq -d"
        )
        result = client.containers.run(
            DOCKER_IMAGE,
            ["bash", "-c", cmd],
            remove=True,
            stdout=True,
            stderr=True,
            tty=True,
        )
        output = result.decode().strip()
        if output:
            lines = output.splitlines()
            tutorial_root = lines[0].strip()
            cases = lines[1:]
            tutorials = []
            for c in cases:
                tutorials.append(posixpath.relpath(c, tutorial_root))
            return jsonify({"tutorials": sorted(tutorials)})
        return jsonify({"tutorials": []})
    except Exception as e:
        return jsonify({"tutorials": [], "error": str(e)}), 500


@app.route("/load_tutorial", methods=["POST"])
def load_tutorial():
    data = request.get_json() or {}
    tutorial = data.get("tutorial")
    if not tutorial:
        return jsonify({"output": "[Error] No tutorial selected"}), 400
        
    client = get_docker_client()
    if not client:
        return jsonify({"output": "[Error] Docker not available"}), 503

    try:
        bashrc = f"/opt/openfoam{OPENFOAM_VERSION}/etc/bashrc"
        container_run_path = "/tmp/FOAM_Run"
        tut_name = posixpath.basename(tutorial)
        container_case_path = posixpath.join(container_run_path, tut_name)
        
        host_path = Path(CASE_ROOT).resolve()
        host_path_str = host_path.as_posix() if platform.system() == "Windows" else str(host_path)
        
        shell_cmd = 'source "$1" && mkdir -p "$2" && cp -r $FOAM_TUTORIALS/"$3"/* "$2"'
        if platform.system() != "Windows":
            shell_cmd += ' && chmod +x "$2"/Allrun'
            
        docker_cmd = [
            "bash", "-c", shell_cmd,
            "load_tutorial",
            bashrc,
            container_case_path,
            tutorial
        ]
        
        client.containers.run(
            DOCKER_IMAGE,
            docker_cmd,
            remove=True,
            volumes={host_path_str: {"bind": container_run_path, "mode": "rw"}},
            working_dir=container_run_path
        )
        
        output = f"INFO::[FOAMTrame] Tutorial loaded::{tutorial}\nCopied to: {CASE_ROOT}/{tut_name}\n"
        return jsonify({"output": output, "caseDir": CASE_ROOT})
    except Exception as e:
        return jsonify({"output": f"[Error] {str(e)}"}), 500


@app.route("/api/case/resolve_vtk", methods=["GET"])
def resolve_case_vtk():
    case_name = request.args.get("caseName")
    if not case_name:
        return jsonify({"file_path": None, "error": "No case name specified"})
        
    path = Path(CASE_ROOT) / case_name
    vtk_files = []
    if path.exists():
        for ext in ("*.vtk", "*.vtu", "*.vtp", "*.vti", "*.vtr", "*.vts", "*.ply", "*.stl", "*.obj"):
            vtk_files.extend(path.rglob(ext))
            
    if vtk_files:
        target = max(vtk_files, key=os.path.getmtime)
        return jsonify({"file_path": str(target), "file_name": target.name})
        
    return jsonify({"file_path": None, "message": "No VTK or mesh file found"})


@app.route("/api/startup_status", methods=["GET"])
def get_startup_status():
    return jsonify(STARTUP_STATUS)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)

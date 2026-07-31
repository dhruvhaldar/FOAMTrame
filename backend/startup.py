
import os
import platform
import logging
import uuid
import time
import shutil
import docker
import docker.errors
from pathlib import Path
from typing import Dict, Any, Callable, Tuple, Optional

logger = logging.getLogger("FOAMFlask")

def run_initial_setup_checks(
    get_docker_client_func: Callable[[], Any],
    case_root: str,
    docker_image: str,
    save_config_func: Callable[[Dict[str, Any]], bool],
    config: Dict[str, Any],
    status_callback: Optional[Callable[[str], None]] = None
) -> Dict[str, Any]:
    """
    Performs comprehensive startup checks:
    1. Checks if Docker executable exists in PATH.
    2. Checks if Docker daemon is accessible (permission check).
    3. Checks if the required Docker image exists, pulling it if necessary.
    4. Performs file permission checks (Linux).

    Args:
        get_docker_client_func: Function to get docker client
        case_root: Path to the case directory
        docker_image: Docker image name
        save_config_func: Function to save configuration
        config: Current configuration dictionary
        status_callback: Optional callback to update status message

    Returns:
        Dictionary with status and message
    """

    # 1. Check if setup is already done
    if config.get("initial_setup_done"):
        return {"status": "completed", "message": "Initial setup already completed"}

    logger.info("[FOAMFlask] Performing first-time setup checks...")

    # 2. Check if docker executable exists
    if not shutil.which("docker"):
        msg = "Docker is not installed or not in PATH. Please install Docker first."
        if os.environ.get("FOAMFLASK_SANDBOX_MODE"):
            logger.warning(f"[FOAMFlask] Sandbox Mode: {msg} Still proceeding...")
        else:
            logger.error(f"[FOAMFlask] {msg}")
            return {"status": "failed", "message": msg}

    # 3. Check if we can connect to Docker daemon (permission check)
    try:
        # We try to get the client. get_docker_client_func usually catches errors but
        # we might want to catch specific ones here if the func re-raises or returns None.
        # Assuming get_docker_client_func returns None on failure as per app.py
        client = get_docker_client_func()
        if client is None:
            # If client is None, it means docker.from_env() failed.
            # We need to know WHY. So we might need to try docker.from_env() ourselves here
            # to distinguish between "not running" and "permission denied".
            try:
                temp_client = docker.from_env()
                temp_client.ping()
            except Exception as e:
                err_str = str(e).lower()
                if "permission denied" in err_str or "eacces" in err_str:
                    msg = "Docker exists but permission denied. Please add your user to the 'docker' group and re-login."
                    logger.error(f"[FOAMFlask] {msg}")
                    return {"status": "failed", "message": msg}
                else:
                    if "createfile" in err_str and "system cannot find the file specified" in err_str:
                        msg = "Docker Desktop is NOT running. Please launch Docker Desktop from your Start Menu and wait for the 'running' status."
                    else:
                        msg = f"Docker is installed but not running or not accessible: {e}"
                    if os.environ.get("FOAMFLASK_SANDBOX_MODE"):
                        logger.warning(f"[FOAMFlask] Sandbox Mode: {msg} Still proceeding...")
                        save_config_func({"initial_setup_done": True, "sandbox_mode": True})
                        return {"status": "completed", "message": "Sandbox Mode: Docker unavailable, but proceeding anyway."}
                    else:
                        logger.error(f"[FOAMFlask] {msg}")
                        return {"status": "failed", "message": msg}
    except Exception as e:
        msg = f"Unexpected error checking Docker: {e}"
        logger.error(f"[FOAMFlask] {msg}")
        return {"status": "failed", "message": msg}

    # 4. Check if image exists, pull if not
    try:
        client = get_docker_client_func() # Should be valid now
        try:
            client.images.get(docker_image)
            logger.info(f"[FOAMFlask] Image {docker_image} found.")
        except docker.errors.ImageNotFound:
            # Check for Dockerfile in root
            dockerfile_path = Path(__file__).resolve().parent.parent / "Dockerfile"

            if dockerfile_path.exists():
                msg = f"Docker image '{docker_image}' not found.\nBuilding from Dockerfile... (Warning: This may take a while)"
                logger.info(f"[FOAMFlask] {msg}")
                print(f"INFO::[FOAMFlask] {msg}")

                if status_callback:
                    status_callback(msg)

                # Build from Dockerfile
                # We use fileobj to avoid sending build context, as the Dockerfile only has a FROM instruction
                try:
                    with open(dockerfile_path, 'rb') as f:
                        client.images.build(fileobj=f, tag=docker_image, rm=True)
                    logger.info(f"[FOAMFlask] Image {docker_image} built successfully.")
                except Exception as build_err:
                    # Fallback to pull if build fails (e.g. base image not accessible and build fails?)
                    # Actually, if build fails, we should report it. But maybe fallback to pull if the Dockerfile is bad?
                    # User request was "Instead of docker pull... I want a dockerfile".
                    # So we should probably fail if build fails, or just let the outer exception handler catch it.
                    # Re-raising ensures it goes to the outer handler which logs "Failed to check/pull Docker image"
                    raise build_err

            else:
                msg = f"Docker image '{docker_image}' not found.\nPulling now... (Warning: Large download, check for metered connection)"
                logger.info(f"[FOAMFlask] {msg}")
                print(f"INFO::[FOAMFlask] {msg}") # Console output

                if status_callback:
                    status_callback(msg)

                import json
                # Use the lower-level API to get progress updates
                logger.info(f"[FOAMFlask] Starting pull for {docker_image}")
                last_progress_update = 0
                for line in client.api.pull(docker_image, stream=True, decode=True):
                    status = line.get('status')
                    progress = line.get('progress')
                    
                    if status == 'Downloading' or status == 'Extracting':
                        # Throttle updates to avoid flooding the frontend/logs
                        import time
                        current_time = time.time()
                        if current_time - last_progress_update > 2: # Every 2 seconds
                            msg = f"Docker Image: {status}... {progress or ''}"
                            if status_callback:
                                status_callback(msg)
                            last_progress_update = current_time
                    elif status == 'Pull complete' or status == 'Already exists':
                         msg = f"Docker Image: {status}"
                         if status_callback: status_callback(msg)

                logger.info(f"[FOAMFlask] Image {docker_image} pulled successfully.")

    except Exception as e:
         msg = f"Failed to check/pull Docker image: {e}"
         logger.error(f"[FOAMFlask] {msg}")
         return {"status": "failed", "message": msg}

    # 5. Run file permission checks
    return check_docker_permissions(get_docker_client_func, case_root, docker_image, save_config_func, config)


def check_docker_permissions(
    get_docker_client_func: Callable[[], Any],
    case_root: str,
    docker_image: str,
    save_config_func: Callable[[Dict[str, Any]], bool],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Checks if Docker creates files with root permissions and attempts to fix it.
    """

    # Note: run_initial_setup_checks already handles the "first time" check generally,
    # but we keep this here just in case this function is called independently.
    if config.get("initial_setup_done"):
        return {"status": "completed", "message": "Initial setup already completed"}

    # Determine if we are on Linux
    is_linux = platform.system() == "Linux"
    if not is_linux:
        # On Windows/Mac (Docker Desktop), permissions are usually handled by the VM
        save_config_func({"initial_setup_done": True, "docker_run_as_user": False})
        return {"status": "completed", "message": "Non-Linux system, skipping permission check"}

    client = get_docker_client_func()
    if not client:
        return {"status": "failed", "message": "Docker not available"}

    logger.info("[FOAMFlask] Starting Docker permission check (Dry Run)...")

    # Ensure case root exists
    case_dir_path = Path(case_root).resolve()
    try:
        case_dir_path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return {"status": "failed", "message": f"Could not create case directory: {e}"}

    # Generate a unique test file name
    test_filename = f".permission_test_{uuid.uuid4().hex}"
    host_test_file = case_dir_path / test_filename
    container_run_path = "/tmp/foam_flask_check" # nosec B108

    # Volume mapping
    volumes = {
        str(case_dir_path): {
            "bind": container_run_path,
            "mode": "rw"
        }
    }

    # Attempt 1: Default run (usually root)
    try:
        logger.info("[FOAMFlask] Permission Check: Attempting default write...")
        # Command to touch a file
        cmd = f"touch {container_run_path}/{test_filename}"

        container = client.containers.run(
            docker_image,
            f"bash -c '{cmd}'",
            volumes=volumes,
            remove=True,
            detach=False # Wait for it to finish
        )

        # Check if file exists
        if not host_test_file.exists():
            return {"status": "failed", "message": "Docker container failed to write test file"}

        # Try to delete it
        try:
            host_test_file.unlink()
            # Success! No permission issues.
            logger.info("[FOAMFlask] Permission Check: Default write success. No permission issues.")
            save_config_func({"initial_setup_done": True, "docker_run_as_user": False})
            return {"status": "completed", "message": "Permission check passed (default)"}

        except PermissionError:
            logger.warning("[FOAMFlask] Permission Check: Default write caused PermissionError. Trying fix...")
            # We cannot delete the file. It's likely owned by root.
            # We need to clean it up later or try to use sudo (not possible here).
            # But let's try the fix now.

            # Note: We still have the root-owned file on disk which we can't delete.
            # Ideally, we should use a container to delete it if we can.
            try:
                cleanup_cmd = f"rm {container_run_path}/{test_filename}"
                client.containers.run(
                    docker_image,
                    f"bash -c '{cleanup_cmd}'",
                    volumes=volumes,
                    remove=True
                )
            except Exception as e:
                logger.error(f"[FOAMFlask] Failed to cleanup root file: {e}")

    except Exception as e:
        logger.warning(f"[FOAMFlask] Permission Check: Default write caused error: {e}")
        logger.warning("[FOAMFlask] Default permission check failed. Attempting automatic fix by switching to user mapping...")
        # Proceed to Attempt 2

    # Attempt 2: Run as user
    try:
        uid = os.getuid()
        gid = os.getgid()
        user_str = f"{uid}:{gid}"

        logger.info(f"[FOAMFlask] Permission Check: Attempting write as user {user_str}...")

        cmd = f"touch {container_run_path}/{test_filename}"

        client.containers.run(
            docker_image,
            f"bash -c '{cmd}'",
            volumes=volumes,
            user=user_str,
            remove=True,
            detach=False
        )

        if not host_test_file.exists():
             return {"status": "failed", "message": "Docker container failed to write test file as user"}

        # Try to delete it
        host_test_file.unlink()

        # Success!
        logger.info("[FOAMFlask] Permission Check: User write success.")
        save_config_func({
            "initial_setup_done": True,
            "docker_run_as_user": True,
            "docker_uid": uid,
            "docker_gid": gid
        })
        return {"status": "completed", "message": "Permission check passed (using host user)"}

    except Exception as e:
        logger.error(f"[FOAMFlask] Permission Check: Error during Attempt 2: {e}")
        return {"status": "failed", "message": f"Permission check failed even with user mapping: {e}"}

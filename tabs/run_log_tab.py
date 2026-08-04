from __future__ import annotations

import logging
import os
import platform
import posixpath
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from trame.widgets import html, vuetify

from app_state import load_run_history, update_run_history

logger = logging.getLogger("FOAMTrame")

def _get_cpu_info() -> dict[str, int]:
    logical = os.cpu_count() or 1
    physical = logical
    try:
        import psutil
        physical = psutil.cpu_count(logical=False) or logical
    except Exception:
        if platform.system() == "Windows":
            try:
                import subprocess
                cmd = "Get-CimInstance Win32_Processor | Select-Object -ExpandProperty NumberOfCores"
                out = subprocess.check_output(["powershell", "-Command", cmd], text=True)
                physical = int(out.strip())
            except Exception:
                pass
    return {"logical": logical, "physical": physical}


_load_run_history = load_run_history


def _save_run_history(history: list[dict]) -> None:
    if not update_run_history(history):
        logger.error("Failed to save run history to app_state.json")


def setup_run_log_tab(server):
    state, ctrl = server.state, server.controller

    cpu_info = _get_cpu_info()
    state.setdefault("cpu_count", cpu_info["logical"])
    state.setdefault("physical_cores", cpu_info["physical"])
    state.setdefault("num_processes", 1)
    state.setdefault("detected_num_processes", "-")
    state.setdefault("detected_method", "-")
    state.setdefault("has_parallel_config", False)

    state.setdefault("run_log_text", "Ready for output...")
    state.setdefault("run_status", "Idle")
    state.setdefault("is_running", False)
    state.setdefault("run_history", _load_run_history())

    _running_lock = threading.Lock()
    _active_container = [None]

    def check_parallel_config():
        from tabs.setup_tab import load_config
        config = load_config()
        case_root = config.get("CASE_ROOT", "")
        active_case = state.active_case or ""
        if not case_root or not active_case:
            state.has_parallel_config = False
            state.flush()
            return

        dict_path = Path(case_root) / active_case / "system" / "decomposeParDict"
        if not dict_path.exists():
            state.has_parallel_config = False
            state.detected_num_processes = "-"
            state.detected_method = "-"
            state.flush()
            return

        try:
            with dict_path.open("r", encoding="utf-8") as f:
                content = f.read()

            num_match = re.search(r"numberOfSubdomains\s+(\d+);", content)
            method_match = re.search(r"(?:method|decomposer)\s+(\w+);", content)

            if num_match:
                state.detected_num_processes = num_match.group(1)
                state.detected_method = method_match.group(1) if method_match else "unknown"
                state.has_parallel_config = True
            else:
                state.has_parallel_config = False
        except Exception:
            state.has_parallel_config = False

        state.flush()

    ctrl.check_parallel_config = check_parallel_config

    def run_command(command: str):
        if state.is_running:
            return

        from tabs.setup_tab import get_docker_client, load_config
        config = load_config()
        case_root = config.get("CASE_ROOT", "")
        active_case = state.active_case or ""
        docker_image = config.get("DOCKER_IMAGE", "haldardhruv/ubuntu_noble_openfoam:v12")
        openfoam_version = config.get("OPENFOAM_VERSION", "12")

        if not case_root or not active_case:
            state.run_log_text = "[FOAMTrame] [Error] No active case selected.\n"
            state.flush()
            return

        case_path = Path(case_root) / active_case
        if not case_path.exists():
            state.run_log_text = f"[FOAMTrame] [Error] Case directory '{case_path}' does not exist.\n"
            state.flush()
            return

        client = get_docker_client()
        if not client:
            state.run_log_text = "[FOAMTrame] [Error] Docker daemon not available. Please start Docker Desktop.\n"
            state.flush()
            return

        # Handle decomposition if num_processes > 1 and running parallel or solver command
        if command not in ["./Allclean", "blockMesh"]:
            try:
                num_proc = int(state.num_processes)
                if num_proc > 1:
                    from backend.case.manager import CaseManager
                    CaseManager.update_decomposition(case_path, num_proc)
                    check_parallel_config()
            except Exception as e:
                logger.warning(f"Failed updating decomposition: {e}")

        # Create history entry
        run_id = int(time.time())
        run_entry = {
            "id": run_id,
            "case_name": active_case,
            "command": command,
            "status": "Running",
            "start_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": None,
            "duration": None,
        }

        history = list(state.run_history or [])
        history.insert(0, run_entry)
        state.run_history = history
        _save_run_history(history)

        state.is_running = True
        state.run_status = f"Running {command}..."
        state.run_log_text = f"[FOAMTrame] Executing '{command}' on case '{active_case}'...\n"
        state.flush()

        def execute():
            start_ts = time.time()
            status = "Completed"
            try:
                bashrc = f"/opt/openfoam{openfoam_version}/etc/bashrc"
                host_path_str = case_path.resolve().as_posix() if platform.system() == "Windows" else str(case_path.resolve())
                container_case_path = "/tmp/FOAM_Run"

                volumes = {
                    host_path_str: {
                        "bind": container_case_path,
                        "mode": "rw",
                    }
                }

                if command.startswith("./"):
                    script_name = command[2:]
                    docker_cmd = [
                        "bash", "-c",
                        'source "$1" && cd "$2" && chmod +x "$3" && ./"$3"',
                        "run_script",
                        bashrc,
                        container_case_path,
                        script_name,
                    ]
                else:
                    docker_cmd = [
                        "bash", "-c",
                        'source "$1" && cd "$2" && $3',
                        "run_foam_cmd",
                        bashrc,
                        container_case_path,
                        command,
                    ]

                container = client.containers.run(
                    docker_image,
                    docker_cmd,
                    detach=True,
                    tty=False,
                    volumes=volumes,
                    working_dir=container_case_path,
                    environment={
                        "OMPI_MCA_rmaps_base_oversubscribe": "1",
                        "OMPI_MCA_btl_vader_single_copy_mechanism": "none",
                    },
                )
                _active_container[0] = container

                log_lines = []
                for line in container.logs(stream=True):
                    decoded = line.decode(errors="ignore")
                    log_lines.append(decoded)
                    # Limit buffer in UI state for performance
                    current_text = state.run_log_text
                    if current_text == "Ready for output...":
                        state.run_log_text = decoded
                    else:
                        # Keep last 50000 characters to prevent huge memory buildup
                        new_text = current_text + decoded
                        if len(new_text) > 60000:
                            new_text = new_text[-50000:]
                        state.run_log_text = new_text
                    state.flush()

                result = container.wait()
                if result.get("StatusCode", 0) != 0:
                    status = "Failed"

                # Save log file in case logs directory
                try:
                    log_dir = case_path / "logs"
                    log_dir.mkdir(parents=True, exist_ok=True)
                    log_file = log_dir / f"run_{run_id}.log"
                    with log_file.open("w", encoding="utf-8") as lf:
                        lf.writelines(log_lines)
                except Exception as log_err:
                    logger.error(f"Failed writing log file: {log_err}")

            except Exception as exc:
                status = "Failed"
                err_msg = f"\n[FOAMTrame] [Error] Command execution failed: {exc}\n"
                state.run_log_text = state.run_log_text + err_msg
                logger.error(f"Run command error: {exc}")
            finally:
                duration = round(time.time() - start_ts, 2)
                if _active_container[0]:
                    try:
                        _active_container[0].remove(force=True)
                    except Exception:
                        pass
                    _active_container[0] = None

                # Update history
                hist = list(state.run_history or [])
                for entry in hist:
                    if entry["id"] == run_id:
                        entry["status"] = status
                        entry["end_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                        entry["duration"] = f"{duration}s"
                        break
                state.run_history = hist
                _save_run_history(hist)

                state.is_running = False
                state.run_status = f"{command} {status} ({duration}s)"
                state.flush()
                check_parallel_config()

        threading.Thread(target=execute, daemon=True).start()

    ctrl.run_command = run_command

    def stop_current_run():
        if _active_container[0]:
            try:
                _active_container[0].kill()
                state.run_log_text = state.run_log_text + "\n[FOAMTrame] Process terminated by user.\n"
                state.flush()
            except Exception as e:
                logger.error(f"Error stopping container: {e}")

    ctrl.stop_current_run = stop_current_run

    def clear_log():
        state.run_log_text = "Ready for output..."
        state.flush()

    ctrl.clear_log = clear_log

    @state.change("active_case")
    def on_active_case_change_run_log(**_):
        check_parallel_config()

    check_parallel_config()


def build_run_log_drawer():
    from trame.app import get_server
    server = get_server()
    ctrl = server.controller

    with html.Div(v_show="active_tab === 3", classes="pa-4"):
        # Parallel & Core Configuration Section
        html.Div("Parallel & Core Configuration", classes="text-overline text--secondary mb-1")
        vuetify.VTextField(
            v_model=("num_processes", 1),
            label="Number of Processes (Cores)",
            type="number",
            min=1,
            max=128,
            outlined=True,
            dense=True,
            hide_details=True,
            classes="mb-2",
        )
        html.P(
            "Physical Cores: {{ physical_cores }} (Logical: {{ cpu_count }})",
            classes="text-caption text-secondary mb-1",
        )
        html.Div(
            "Decomposition: {{ has_parallel_config ? ('Configured (' + detected_num_processes + ' cores, ' + detected_method + ')') : 'Not decomposed' }}",
            classes="text-caption font-weight-bold text-primary mb-3",
        )

        vuetify.VDivider(classes="my-3")

        # Simulation Execution Commands Section
        html.Div("Simulation Execution Commands", classes="text-overline text--secondary mb-1")
        vuetify.VBtn(
            "Allrun",
            click=lambda: ctrl.run_command("./Allrun"),
            block=True,
            small=True,
            classes="theme-btn-success mb-2",
            disabled=("is_running",),
        )
        vuetify.VBtn(
            "Allclean",
            click=lambda: ctrl.run_command("./Allclean"),
            block=True,
            small=True,
            classes="theme-btn-error mb-2",
            disabled=("is_running",),
        )
        vuetify.VBtn(
            "blockMesh",
            click=lambda: ctrl.run_command("blockMesh"),
            block=True,
            small=True,
            classes="theme-btn-primary mb-2",
            disabled=("is_running",),
        )
        vuetify.VBtn(
            "simpleFoam",
            click=lambda: ctrl.run_command("simpleFoam"),
            block=True,
            small=True,
            classes="theme-btn-info mb-2",
            disabled=("is_running",),
        )
        vuetify.VBtn(
            "pimpleFoam",
            click=lambda: ctrl.run_command("pimpleFoam"),
            block=True,
            small=True,
            classes="theme-btn-warning mb-2",
            disabled=("is_running",),
        )
        vuetify.VBtn(
            "decomposePar",
            click=lambda: ctrl.run_command("decomposePar"),
            block=True,
            small=True,
            outlined=True,
            color="primary",
            classes="theme-btn-outlined mb-2",
            disabled=("is_running",),
        )
        vuetify.VBtn(
            "reconstructPar",
            click=lambda: ctrl.run_command("reconstructPar"),
            block=True,
            small=True,
            outlined=True,
            color="primary",
            classes="theme-btn-outlined mb-2",
            disabled=("is_running",),
        )
        vuetify.VBtn(
            "foamToVTK",
            click=lambda: ctrl.run_command("foamToVTK"),
            block=True,
            small=True,
            outlined=True,
            color="secondary",
            classes="theme-btn-outlined mb-2",
            disabled=("is_running",),
        )

        vuetify.VDivider(classes="my-3")

        vuetify.VBtn(
            "Stop Process",
            click=ctrl.stop_current_run,
            block=True,
            small=True,
            color="error",
            disabled=("!is_running",),
        )


def build_run_log_content():
    from trame.app import get_server
    server = get_server()
    ctrl = server.controller

    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-6 overflow-y-auto",
        v_if="active_tab === 3",
        style="max-height: calc(100vh - 64px);",
    ):
        with vuetify.VRow(justify="center"):
            with vuetify.VCol(cols="12", lg="10"):
                # Header & Status Card
                with vuetify.VCard(classes="pa-4 mb-4 glass-card"):
                    with vuetify.VRow(align="center", justify="space-between", no_gutters=True):
                        with vuetify.VCol(cols="12", sm="8"):
                            with vuetify.VCardTitle(classes="headline font-weight-bold pa-0"):
                                html.Span("Run & Console Logs")
                            html.P(
                                "Execute OpenFOAM simulation commands and view output logs in real-time.",
                                classes="text-caption text-secondary mb-0",
                            )
                        with vuetify.VCol(cols="12", sm="4", classes="d-flex justify-sm-end align-center mt-2 mt-sm-0"):
                            vuetify.VChip(
                                "{{ run_status }}",
                                color=("is_running ? 'warning' : 'success'", "info"),
                                text_color="white",
                                label=True,
                                small=True,
                                classes="font-weight-bold my-0",
                            )

                # Console Output Log Box Card
                with vuetify.VCard(classes="pa-4 mb-4 glass-card"):
                    with vuetify.VCardTitle(classes="subtitle-1 font-weight-bold d-flex align-center justify-space-between py-1"):
                        with html.Div(classes="d-flex align-center"):
                            vuetify.VIcon("mdi-console", classes="mr-2", color="primary")
                            html.Span("Console Log Output")
                        vuetify.VBtn(
                            "Clear",
                            click=ctrl.clear_log,
                            small=True,
                            outlined=True,
                            color="error",
                            classes="ma-0",
                        )

                    with vuetify.VCardText():
                        html.Pre(
                            "{{ run_log_text }}",
                            style=(
                                "background: #0f172a; color: #38bdf8; font-family: monospace; "
                                "padding: 16px; border-radius: 12px; height: 360px; overflow-y: auto; "
                                "white-space: pre-wrap; word-break: break-all; font-size: 0.85rem;"
                            ),
                        )

                # Run History Table Card
                with vuetify.VCard(classes="pa-4 glass-card"):
                    with vuetify.VCardTitle(classes="subtitle-1 font-weight-bold"):
                        vuetify.VIcon("mdi-history", classes="mr-2", color="primary")
                        html.Span("Simulation Run History")
                    with vuetify.VCardText():
                        with vuetify.VSimpleTable(dense=True):
                            with html.Thead():
                                with html.Tr():
                                    html.Th("Run ID", classes="text-left")
                                    html.Th("Case Name", classes="text-left")
                                    html.Th("Command", classes="text-left")
                                    html.Th("Status", classes="text-left")
                                    html.Th("Start Time", classes="text-left")
                                    html.Th("Duration", classes="text-left")
                            with html.Tbody():
                                with html.Tr(v_for="item in run_history", key="item.id"):
                                    html.Td("{{ item.id }}")
                                    html.Td("{{ item.case_name }}")
                                    html.Td("{{ item.command }}")
                                    with html.Td():
                                        vuetify.VChip(
                                            "{{ item.status }}",
                                            color=("item.status === 'Completed' ? 'success' : (item.status === 'Running' ? 'warning' : 'error')",),
                                            x_small=True,
                                            label=True,
                                            text_color="white",
                                        )
                                    html.Td("{{ item.start_time }}")
                                    html.Td("{{ item.duration || '-' }}")

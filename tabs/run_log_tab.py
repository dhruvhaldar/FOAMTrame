from __future__ import annotations

import asyncio
import logging
import os
import platform
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from trame.widgets import html, vuetify

from app_state import load_run_history, update_run_history
from backend.case.capabilities import CaseInspection, case_action_service

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
        logger.error("Failed to save run history to the application database")


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
    empty_inspection = case_action_service.inspect_case(None)
    state.setdefault("case_action_map", empty_inspection.action_map())
    state.setdefault("case_workflow_items", list(empty_inspection.action_map().values()))
    state.setdefault("guided_action_ids", [])
    state.setdefault("guided_action_labels", [])
    state.setdefault("clean_preview", [])
    state.setdefault("capability_summary", "Waiting for an active case")
    state.setdefault("capability_inspected", False)
    state.setdefault("capability_available_count", 0)
    state.setdefault("capability_solver_label", "")
    state.setdefault("capability_scanning", False)
    state.setdefault("action_confirm_dialog", False)
    state.setdefault("pending_action_id", "")
    state.setdefault("pending_action_title", "")
    state.setdefault("pending_action_message", "")
    state.setdefault("pending_action_preview", [])
    state.setdefault("guided_run_dialog", False)

    _running_lock = threading.Lock()
    _active_container = [None]
    _inspection: list[CaseInspection] = [empty_inspection]
    _pending_clean_inspection: list[CaseInspection | None] = [None]
    _inspection_lock = threading.Lock()
    _server_event_loop = [None]
    capability_state_keys = (
        "case_action_map",
        "case_workflow_items",
        "guided_action_ids",
        "guided_action_labels",
        "clean_preview",
        "capability_summary",
        "capability_inspected",
        "capability_available_count",
        "capability_solver_label",
        "capability_scanning",
    )

    def publish_state(*keys: str):
        state.dirty(*keys)
        state.flush()
        loop = _server_event_loop[0]
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(server.force_state_push, *keys)

    @ctrl.add("on_server_ready")
    def capture_run_log_event_loop(**_):
        _server_event_loop[0] = asyncio.get_running_loop()
        server.force_state_push(*capability_state_keys)

    def current_case_context():
        from tabs.setup_tab import load_config

        config = load_config()
        case_root = config.get("CASE_ROOT", "")
        active_case = getattr(state, "active_case", "") or ""
        case_path = Path(case_root) / active_case if case_root and active_case else None
        return config, case_path

    def inspect_current_case() -> CaseInspection:
        from tabs.setup_tab import get_docker_client

        config, case_path = current_case_context()
        return case_action_service.inspect_case(
            case_path,
            docker_client=get_docker_client(),
            docker_image=config.get("DOCKER_IMAGE", ""),
            openfoam_version=config.get("OPENFOAM_VERSION", ""),
        )

    def apply_inspection(inspection: CaseInspection):
        _inspection[0] = inspection
        action_map = inspection.action_map()
        state.case_action_map = action_map
        state.case_workflow_items = [
            action_map[action_id]
            for action_id in case_action_service.ACTION_ORDER
            if action_id in action_map
        ]
        state.guided_action_ids = list(inspection.guided_actions)
        state.guided_action_labels = inspection.guided_labels()
        state.clean_preview = inspection.clean_target_labels()
        state.capability_summary = inspection.summary
        state.capability_inspected = inspection.case_path is not None
        state.capability_available_count = sum(
            bool(action.get("available")) for action in action_map.values()
        )
        solver_action = action_map.get("solver", {})
        state.capability_solver_label = (
            str(solver_action.get("label", ""))
            if solver_action.get("available")
            else ""
        )

    def scan_capabilities():
        if not _inspection_lock.acquire(blocking=False):
            return
        state.capability_scanning = True
        publish_state("capability_scanning")
        try:
            apply_inspection(inspect_current_case())
        except Exception as exc:
            logger.exception("Case capability scan failed")
            fallback = case_action_service.inspect_case(None)
            apply_inspection(fallback)
            state.capability_summary = f"Capability scan failed: {exc}"
        finally:
            state.capability_scanning = False
            publish_state(*capability_state_keys)
            _inspection_lock.release()

    def trigger_capability_scan():
        threading.Thread(target=scan_capabilities, daemon=True).start()

    ctrl.scan_case_capabilities = trigger_capability_scan

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

    def append_history_entry(display_command: str, status: str = "Running") -> int:
        run_id = time.time_ns()
        run_entry = {
            "id": run_id,
            "case_name": getattr(state, "active_case", "") or "",
            "command": display_command,
            "status": status,
            "start_time": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": None,
            "duration": None,
        }

        history = list(state.run_history or [])
        history.insert(0, run_entry)
        state.run_history = history
        _save_run_history(history)
        return run_id

    def finish_history_entry(run_id: int, status: str, duration: float):
        history = list(state.run_history or [])
        for entry in history:
            if entry["id"] == run_id:
                entry["status"] = status
                entry["end_time"] = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S"
                )
                entry["duration"] = f"{duration}s"
                break
        state.run_history = history
        _save_run_history(history)

    def run_actions(action_ids: list[str], display_command: str | None = None):
        if state.is_running or not action_ids:
            return
        if not _running_lock.acquire(blocking=False):
            return

        from tabs.setup_tab import get_docker_client

        try:
            inspection = inspect_current_case()
            actions = case_action_service.resolve_actions(inspection, action_ids)
            config, case_path = current_case_context()
            if case_path is None:
                raise ValueError("No active case selected")
            client = get_docker_client()
            if client is None:
                raise RuntimeError("Docker daemon not available. Please start Docker Desktop.")
        except Exception as exc:
            _running_lock.release()
            state.run_log_text = f"[FOAMTrame] [Error] {exc}\n"
            state.run_status = "Action unavailable"
            state.flush()
            trigger_capability_scan()
            return

        active_case = getattr(state, "active_case", "") or ""
        docker_image = config.get("DOCKER_IMAGE", "haldardhruv/ubuntu_noble_openfoam:v12")
        openfoam_version = config.get("OPENFOAM_VERSION", "12")
        command_label = display_command or actions[0].label
        run_id = append_history_entry(command_label)
        state.is_running = True
        state.run_status = f"Running {command_label}..."
        state.run_log_text = (
            f"[FOAMTrame] Executing '{command_label}' on case '{active_case}'...\n"
            + "[FOAMTrame] Validated plan: "
            + " → ".join(action.label for action in actions)
            + "\n"
        )
        state.flush()

        def execute():
            start_ts = time.time()
            status = "Completed"
            try:
                container, _ = case_action_service.start_run(
                    inspection,
                    action_ids,
                    docker_client=client,
                    docker_image=docker_image,
                    openfoam_version=openfoam_version,
                    environment={
                        "OMPI_MCA_rmaps_base_oversubscribe": "1",
                        "OMPI_MCA_btl_vader_single_copy_mechanism": "none",
                    },
                )
                _active_container[0] = container

                log_dir = case_path / "logs"
                log_dir.mkdir(parents=True, exist_ok=True)
                archive_log_path = log_dir / f"run_{run_id}.log"
                is_solver_run = any(
                    action.id in {"allrun", "solver"} for action in actions
                )
                live_log_path = case_path / "log.foamRun" if is_solver_run else None

                # Tee solver output to log.foamRun while it is produced. The plots
                # parser can then consume residuals incrementally rather than waiting
                # for the container to finish and an archive to be written.
                live_log = None
                archive_log = None
                try:
                    try:
                        archive_log = archive_log_path.open("w", encoding="utf-8", buffering=1)
                    except OSError as log_err:
                        logger.warning(f"Could not open run archive log: {log_err}")
                    if live_log_path is not None:
                        try:
                            live_log = live_log_path.open("w", encoding="utf-8", buffering=1)
                        except OSError as log_err:
                            logger.warning(f"Could not open live residual log: {log_err}")

                    for line in container.logs(stream=True):
                        decoded = line.decode(errors="ignore")
                        if archive_log is not None:
                            archive_log.write(decoded)
                        if live_log is not None:
                            live_log.write(decoded)

                        # Limit buffer in UI state for performance
                        current_text = state.run_log_text
                        if current_text == "Ready for output...":
                            state.run_log_text = decoded
                        else:
                            new_text = current_text + decoded
                            if len(new_text) > 60000:
                                new_text = new_text[-50000:]
                            state.run_log_text = new_text
                        state.flush()
                finally:
                    if archive_log is not None:
                        archive_log.close()
                    if live_log is not None:
                        live_log.close()

                result = container.wait()
                if result.get("StatusCode", 0) != 0:
                    status = "Failed"

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

                finish_history_entry(run_id, status, duration)
                state.is_running = False
                state.run_status = f"{command_label} {status} ({duration}s)"
                state.flush()
                check_parallel_config()
                trigger_capability_scan()
                _running_lock.release()

        threading.Thread(target=execute, daemon=True).start()

    def run_safe_clean(inspection: CaseInspection | None = None):
        if state.is_running or not _running_lock.acquire(blocking=False):
            return
        inspection = inspection or _inspection[0]
        run_id = append_history_entry("Safe Clean Generated Outputs")
        state.is_running = True
        state.run_status = "Cleaning generated outputs..."
        state.run_log_text = "[FOAMTrame] Removing the reviewed generated outputs...\n"
        state.flush()

        def execute_clean():
            start_ts = time.time()
            status = "Completed"
            try:
                removed = case_action_service.clean_case(inspection)
                if removed:
                    state.run_log_text += "".join(
                        f"[FOAMTrame] Removed {path}\n" for path in removed
                    )
                else:
                    state.run_log_text += "[FOAMTrame] Nothing remained to remove.\n"
            except Exception as exc:
                status = "Failed"
                state.run_log_text += f"[FOAMTrame] [Error] Safe clean failed: {exc}\n"
            finally:
                duration = round(time.time() - start_ts, 2)
                finish_history_entry(run_id, status, duration)
                state.is_running = False
                state.run_status = f"Safe Clean {status} ({duration}s)"
                state.flush()
                trigger_capability_scan()
                _running_lock.release()

        threading.Thread(target=execute_clean, daemon=True).start()

    def request_case_action(action_id: str):
        action = _inspection[0].actions.get(action_id)
        if action is None or not action.available:
            reason = action.reason if action else "Unknown action"
            state.run_log_text = f"[FOAMTrame] [Error] Action unavailable: {reason}\n"
            state.flush()
            return
        if action.destructive:
            state.pending_action_id = action_id
            state.pending_action_title = f"Confirm {action.label}"
            state.pending_action_message = (
                "The case-provided Allclean script controls what will be removed."
                if action_id == "allclean"
                else "Only the generated paths listed below will be removed."
            )
            state.pending_action_preview = (
                list(state.clean_preview)
                if action_id == "safe_clean"
                else ["Review the case's Allclean script if its cleanup policy is uncertain."]
            )
            _pending_clean_inspection[0] = (
                _inspection[0] if action_id == "safe_clean" else None
            )
            state.action_confirm_dialog = True
            state.flush()
            return
        run_actions([action_id])

    def confirm_case_action():
        action_id = state.pending_action_id
        state.action_confirm_dialog = False
        state.pending_action_id = ""
        state.flush()
        if action_id == "safe_clean":
            inspection = _pending_clean_inspection[0]
            _pending_clean_inspection[0] = None
            run_safe_clean(inspection)
        elif action_id:
            run_actions([action_id])

    def request_guided_run():
        inspection = _inspection[0]
        if inspection.actions["allrun"].available:
            state.run_log_text = (
                "[FOAMTrame] Allrun is available and remains the preferred workflow.\n"
            )
            state.flush()
            return
        if not inspection.guided_actions:
            state.run_log_text = "[FOAMTrame] No confident guided-run steps were detected.\n"
            state.flush()
            return
        state.guided_run_dialog = True
        state.flush()

    def confirm_guided_run():
        action_ids = list(_inspection[0].guided_actions)
        state.guided_run_dialog = False
        state.flush()
        run_actions(action_ids, "Guided Run")

    ctrl.request_case_action = request_case_action
    ctrl.confirm_case_action = confirm_case_action
    ctrl.request_guided_run = request_guided_run
    ctrl.confirm_guided_run = confirm_guided_run

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
        state.action_confirm_dialog = False
        state.guided_run_dialog = False
        state.pending_action_id = ""
        _pending_clean_inspection[0] = None
        check_parallel_config()
        trigger_capability_scan()

    @state.change("docker_image", "openfoam_version")
    def on_run_log_docker_config_change(**_):
        trigger_capability_scan()

    @state.change("setup_status")
    def on_run_log_setup_status_change(setup_status, **_):
        if setup_status == "Docker integration ready.":
            trigger_capability_scan()

    check_parallel_config()
    trigger_capability_scan()


def build_run_log_drawer():
    from trame.app import get_server
    server = get_server()
    ctrl = server.controller

    def capability_button(
        action_id: str,
        *,
        classes: str = "theme-btn-outlined mb-2",
        color: str = "primary",
        outlined: bool = True,
    ):
        vuetify.VBtn(
            f"{{{{ case_action_map.{action_id}.label }}}}",
            click=lambda key=action_id: ctrl.request_case_action(key),
            block=True,
            small=True,
            outlined=outlined,
            color=color,
            classes=classes,
            disabled=(
                f"is_running || capability_scanning || !case_action_map.{action_id}.available",
            ),
            title=(f"case_action_map.{action_id}.reason",),
        )

    with html.Div(v_show="active_tab === 3", classes="pa-4 run-log-drawer"):
        # Parallel & Core Configuration Section
        html.Div("Parallel & Core Config", classes="text-overline text--secondary mb-1")
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

        with html.Div(classes="d-flex align-center mb-1"):
            html.Div("Detected Case Workflow", classes="text-overline text--secondary")
            vuetify.VSpacer()
            with vuetify.VBtn(
                icon=True,
                x_small=True,
                click=ctrl.scan_case_capabilities,
                disabled=("capability_scanning || is_running",),
                title="Rescan case capabilities",
            ):
                vuetify.VIcon("mdi-refresh", small=True)
        with html.Div(classes="capability-summary mb-2"):
            vuetify.VProgressCircular(
                v_if="capability_scanning",
                indeterminate=True,
                size=16,
                width=2,
                color="cyan darken-2",
                classes="mr-2",
            )
            html.Span(
                "Inspecting case and Docker image…",
                v_if="capability_scanning",
            )
            with html.Div(
                v_if="!capability_scanning && capability_inspected",
                classes="capability-summary__content",
            ):
                html.Span(
                    "Detected {{ capability_available_count }} available action(s)",
                    classes="capability-summary__count",
                )
                with html.Span(
                    v_if="capability_solver_label",
                    classes="capability-summary__solver",
                ):
                    html.Span("•", classes="capability-summary__dot")
                    html.Strong("Solver")
                    html.Span(":")
                    html.Strong("{{ capability_solver_label }}")
            html.Span(
                "{{ capability_summary }}",
                v_if="!capability_scanning && !capability_inspected",
            )

        with vuetify.VList(dense=True, classes="case-workflow-list pa-0 mb-3"):
            with vuetify.VListItem(
                v_for="action in case_workflow_items",
                key=("action.id",),
                classes="case-workflow-item px-2",
            ):
                with vuetify.VListItemIcon(classes="mr-2 my-2"):
                    vuetify.VIcon(
                        "{{ action.available ? 'mdi-check-circle' : 'mdi-close-circle-outline' }}",
                        small=True,
                        color=("action.available ? 'teal darken-2' : 'grey'",),
                    )
                with vuetify.VListItemContent(classes="py-1"):
                    vuetify.VListItemTitle("{{ action.label }}", classes="text-caption font-weight-bold")
                    vuetify.VListItemSubtitle("{{ action.reason }}", classes="case-action-reason")

        html.Div("Workflow", classes="text-overline text--secondary mb-1")
        capability_button(
            "allrun",
            classes="theme-btn-success mb-2",
            color="success",
            outlined=False,
        )
        vuetify.VBtn(
            "Guided Run — Review Steps",
            click=ctrl.request_guided_run,
            block=True,
            small=True,
            classes="theme-btn-primary mb-2",
            v_if="!case_action_map.allrun.available",
            disabled=("is_running || capability_scanning || guided_action_ids.length === 0",),
            title="Review and run the confidently detected case steps",
        )

        html.Div("Detected Commands", classes="text-overline text--secondary mt-3 mb-1")
        capability_button("surfaceFeatureExtract")
        capability_button("blockMesh")
        capability_button("snappyHexMesh")
        capability_button("topoSet")
        capability_button("setFields")
        capability_button(
            "solver",
            classes="theme-btn-info mb-2",
            color="cyan darken-3",
            outlined=False,
        )
        capability_button("decomposePar")
        capability_button("reconstructPar")
        capability_button("foamToVTK", color="secondary")

        html.Div("Cleanup", classes="text-overline text--secondary mt-3 mb-1")
        capability_button(
            "allclean",
            classes="theme-btn-error mb-2",
            color="error",
            outlined=False,
        )
        capability_button("safe_clean", color="warning")

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
        style="max-height: calc(100vh - 48px);",
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

    with vuetify.VDialog(v_model=("action_confirm_dialog", False), max_width="620"):
        with vuetify.VCard(classes="glass-card pa-2"):
            vuetify.VCardTitle("{{ pending_action_title }}", classes="headline font-weight-bold")
            with vuetify.VCardText():
                html.P("{{ pending_action_message }}", classes="mb-3")
                with vuetify.VAlert(
                    type="warning",
                    text=True,
                    dense=True,
                    classes="mb-3",
                ):
                    html.Span("This operation changes or removes case data and cannot be undone by FOAMTrame.")
                with vuetify.VList(
                    dense=True,
                    outlined=True,
                    v_if="pending_action_preview.length > 0",
                    classes="clean-preview-list",
                ):
                    with vuetify.VListItem(
                        v_for="target in pending_action_preview",
                        key=("target",),
                    ):
                        with vuetify.VListItemIcon(classes="mr-2"):
                            vuetify.VIcon("mdi-file-remove-outline", small=True, color="warning")
                        vuetify.VListItemTitle("{{ target }}", classes="text-body-2")
            with vuetify.VCardActions():
                vuetify.VSpacer()
                vuetify.VBtn("Cancel", text=True, click="action_confirm_dialog = false")
                vuetify.VBtn(
                    "Confirm",
                    color="error",
                    classes="theme-btn-error",
                    click=ctrl.confirm_case_action,
                )

    with vuetify.VDialog(v_model=("guided_run_dialog", False), max_width="660"):
        with vuetify.VCard(classes="glass-card pa-2"):
            vuetify.VCardTitle("Review Guided Run", classes="headline font-weight-bold")
            with vuetify.VCardText():
                html.P(
                    "No Allrun script was supplied. FOAMTrame detected the following suggested sequence. Review it before execution because case-specific ordering may differ.",
                    classes="mb-3",
                )
                with vuetify.VList(dense=True, outlined=True, classes="guided-run-list"):
                    with vuetify.VListItem(
                        v_for="(label, index) in guided_action_labels",
                        key=("label",),
                    ):
                        with vuetify.VListItemAvatar(
                            color="cyan darken-3",
                            size="28",
                        ):
                            html.Span("{{ index + 1 }}", classes="white--text text-caption")
                        vuetify.VListItemTitle("{{ label }}")
            with vuetify.VCardActions():
                vuetify.VSpacer()
                vuetify.VBtn("Cancel", text=True, click="guided_run_dialog = false")
                vuetify.VBtn(
                    "Run Reviewed Steps",
                    classes="theme-btn-primary",
                    click=ctrl.confirm_guided_run,
                )

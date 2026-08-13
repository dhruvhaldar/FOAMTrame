from __future__ import annotations

import asyncio
import logging
import os
import platform
import posixpath
import re
import shutil
import threading
from pathlib import Path
from trame.widgets import html, vuetify

from app_state import load_case_config, update_case_config

logger = logging.getLogger("FOAMTrame")

# Backwards-compatible names used by the existing tab modules.
load_config = load_case_config
save_config = update_case_config


def get_docker_client():
    try:
        import docker
        client = docker.from_env(timeout=5)
        client.ping()
        return client
    except Exception:
        return None


def detect_openfoam_version(client, docker_image: str, configured_version: str) -> str:
    """Read the OpenFOAM runtime version from the configured Docker image.

    Sourcing the image's bashrc and reading WM_PROJECT_VERSION avoids inferring
    a version from an image tag, which may be renamed or locally rebuilt.
    """
    shell_script = r'''
requested="$1"
bashrc="/opt/openfoam${requested}/etc/bashrc"
if [ ! -f "$bashrc" ]; then
    bashrc="$(find /opt -maxdepth 4 -type f -path '*/etc/bashrc' 2>/dev/null | head -n 1)"
fi
[ -n "$bashrc" ] && [ -f "$bashrc" ] || exit 2
source "$bashrc" >/dev/null 2>&1 || exit 3
printf '%s' "${WM_PROJECT_VERSION:-}"
'''
    output = client.containers.run(
        docker_image,
        ["bash", "-c", shell_script, "detect_openfoam_version", str(configured_version)],
        remove=True,
        stdout=True,
        stderr=False,
        network_disabled=True,
    )
    version = output.decode("utf-8", errors="replace").strip()
    if not version:
        raise RuntimeError("WM_PROJECT_VERSION was empty after sourcing OpenFOAM")
    # Keep the footer compact and reject unexpected multiline/noisy output.
    version = version.splitlines()[-1].strip()
    if not re.fullmatch(r"[A-Za-z0-9._+-]{1,64}", version):
        raise RuntimeError("The container returned an invalid OpenFOAM version")
    return version


# --- Setup Tab Controller and State ---
def setup_setup_tab(server):
    state, ctrl = server.state, server.controller

    # Load initial config
    config = load_config()
    state.setdefault("case_root", config["CASE_ROOT"])
    state.setdefault("docker_image", config["DOCKER_IMAGE"])
    state.setdefault("openfoam_version", config["OPENFOAM_VERSION"])
    state.setdefault("openfoam_runtime_version", "")
    state.setdefault("openfoam_runtime_label", "OpenFOAM: detecting…")
    state.setdefault(
        "openfoam_runtime_source",
        "Detecting the runtime version from the configured Docker image.",
    )

    state.setdefault("docker_checking", True)
    state.setdefault("setup_status", "Initializing...")
    state.setdefault("setup_status_color", "info")
    state.setdefault("trame_status", "Trame server ready.")
    state.setdefault("trame_status_color", "success")
    state.setdefault("active_case", config.get("ACTIVE_CASE", ""))
    state.setdefault("cases_list", [])

    state.setdefault("new_case_name", "")
    state.setdefault("tutorials_list", [])
    state.setdefault("tutorial_search", "")
    state.setdefault("filtered_tutorials", [])
    state.setdefault("selected_tutorial", "")
    state.setdefault("case_creation_tab", 0)
    state.setdefault("tutorials_loaded", False)
    state.setdefault("tutorials_loading", False)

    tutorial_fetch_lock = threading.Lock()
    server_event_loop = [None]

    docker_state_keys = (
        "setup_status",
        "setup_status_color",
        "docker_checking",
        "openfoam_runtime_version",
        "openfoam_runtime_label",
        "openfoam_runtime_source",
    )

    @ctrl.add("on_server_ready")
    def capture_server_event_loop(**_):
        """Capture the wslink loop used for thread-safe client state pushes."""
        server_event_loop[0] = asyncio.get_running_loop()
        server.force_state_push(
            "tutorials_list",
            "filtered_tutorials",
            "tutorials_loaded",
            "tutorials_loading",
            "openfoam_runtime_version",
            "openfoam_runtime_label",
            "openfoam_runtime_source",
        )

    @ctrl.add("on_client_connected")
    def publish_setup_snapshot(**_):
        """Give reconnecting clients the latest completed background state."""
        server.force_state_push(*docker_state_keys)
        server.force_state_push(
            "tutorials_list",
            "filtered_tutorials",
            "tutorials_loaded",
            "tutorials_loading",
        )

    def publish_setup_state(*keys):
        """Publish worker-thread state changes through wslink's event loop."""
        state.dirty(*keys)
        state.flush()
        loop = server_event_loop[0]
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(server.force_state_push, *keys)

    def publish_tutorial_state(*keys):
        """Flush Python state, then publish it on wslink's running event loop."""
        state.dirty(*keys)
        state.flush()
        loop = server_event_loop[0]
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(server.force_state_push, *keys)

    def scan_cases():
        root_path = Path(state.case_root)
        if not root_path.exists():
            try:
                root_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.error(f"Failed to create Case Root directory: {e}")
                state.cases_list = []
                state.active_case = ""
                save_config({"ACTIVE_CASE": ""})
                state.flush()
                return

        try:
            cases = [
                entry.name
                for entry in os.scandir(str(root_path))
                if entry.is_dir()
            ]
            state.cases_list = sorted(cases)
            if state.active_case not in state.cases_list:
                state.active_case = state.cases_list[0] if state.cases_list else ""
                save_config({"ACTIVE_CASE": state.active_case})
            state.flush()
        except Exception as e:
            logger.error(f"Error scanning cases: {e}")
            state.cases_list = []
            state.active_case = ""
            save_config({"ACTIVE_CASE": ""})
            state.flush()

    ctrl.scan_cases = scan_cases

    def run_docker_checks():
        state.docker_checking = True
        state.openfoam_runtime_version = ""
        state.openfoam_runtime_label = "OpenFOAM: detecting…"
        state.openfoam_runtime_source = (
            "Detecting the runtime version from the configured Docker image."
        )
        state.setup_status = "Checking Docker executable..."
        state.setup_status_color = "info"
        publish_setup_state(*docker_state_keys)

        if not shutil.which("docker"):
            state.setup_status = "Docker executable not found in PATH."
            state.setup_status_color = "error"
            state.docker_checking = False
            state.openfoam_runtime_label = f"OpenFOAM {state.openfoam_version} (configured)"
            state.openfoam_runtime_source = (
                "Docker is unavailable; showing the configured version instead."
            )
            publish_setup_state(*docker_state_keys)
            return

        state.setup_status = "Connecting to Docker daemon..."
        publish_setup_state("setup_status")

        client = get_docker_client()
        if not client:
            state.setup_status = "Cannot connect to Docker daemon. Make sure Docker Desktop is running."
            state.setup_status_color = "error"
            state.docker_checking = False
            state.openfoam_runtime_label = f"OpenFOAM {state.openfoam_version} (configured)"
            state.openfoam_runtime_source = (
                "Docker is unavailable; showing the configured version instead."
            )
            publish_setup_state(*docker_state_keys)
            return

        state.setup_status = f"Checking Docker image {state.docker_image}..."
        publish_setup_state("setup_status")

        try:
            import docker.errors
            client.images.get(state.docker_image)
            try:
                detected_version = detect_openfoam_version(
                    client,
                    state.docker_image,
                    state.openfoam_version,
                )
                state.openfoam_runtime_version = detected_version
                state.openfoam_runtime_label = f"OpenFOAM {detected_version}"
                state.openfoam_runtime_source = (
                    f"Detected from Docker image {state.docker_image}."
                )
            except Exception as version_error:
                logger.warning(
                    "Could not detect OpenFOAM version from %s: %s",
                    state.docker_image,
                    version_error,
                )
                state.openfoam_runtime_label = (
                    f"OpenFOAM {state.openfoam_version} (configured)"
                )
                state.openfoam_runtime_source = (
                    "Runtime detection failed; showing the configured version instead."
                )
            state.setup_status = "Docker integration ready."
            state.setup_status_color = "success"
            state.docker_checking = False
            publish_setup_state(*docker_state_keys)
            fetch_tutorials()
        except Exception as e:
            err = str(e)
            if "404" in err or "No such image" in err.lower():
                state.setup_status = f"Image '{state.docker_image}' not found on host. Pull/build required."
                state.setup_status_color = "warning"
            else:
                state.setup_status = f"Error checking image: {e}"
                state.setup_status_color = "error"
            state.docker_checking = False
            state.openfoam_runtime_label = f"OpenFOAM {state.openfoam_version} (configured)"
            state.openfoam_runtime_source = (
                "The Docker image could not be inspected; showing the configured version."
            )
            publish_setup_state(*docker_state_keys)

    def fetch_tutorials():
        # Re-publish cached values. The import tab may have been inactive when
        # the background Docker check first populated them, so a plain early
        # return can leave the Vue client with an empty items array until F5.
        if state.tutorials_loaded and state.tutorials_list:
            on_tutorial_search_change()
            publish_tutorial_state(
                "tutorials_list", "filtered_tutorials", "tutorials_loaded"
            )
            return

        if not tutorial_fetch_lock.acquire(blocking=False):
            return

        state.tutorials_loading = True
        publish_tutorial_state("tutorials_loading")

        client = get_docker_client()
        if not client:
            state.tutorials_loading = False
            publish_tutorial_state("tutorials_loading")
            tutorial_fetch_lock.release()
            return

        try:
            bashrc = f"/opt/openfoam{state.openfoam_version}/etc/bashrc"
            cmd = (
                f"source {bashrc} && "
                "tutorials_dir=${FOAM_TUTORIALS:-/opt/openfoam12/tutorials} && "
                "echo $tutorials_dir && "
                "find $tutorials_dir -mindepth 3 -maxdepth 5 \\( -type d -o -type l \\) \\( -name system -o -name constant \\) "
                "| sed 's|/[^/]*$||' | sort | uniq -d"
            )
            result = client.containers.run(
                state.docker_image,
                ["bash", "-c", cmd],
                remove=True,
                stdout=True,
                stderr=False,
            )
            output = result.decode().strip()
            tutorials = []
            if output:
                lines = output.splitlines()
                tutorial_root = lines[0].strip()
                cases = lines[1:]
                tutorials = [posixpath.relpath(c, tutorial_root) for c in cases if c.strip()]
            state.tutorials_list = sorted(tutorials)
            state.filtered_tutorials = sorted(tutorials)
            state.tutorials_loaded = True
            publish_tutorial_state(
                "tutorials_list", "filtered_tutorials", "tutorials_loaded"
            )
        except Exception as e:
            logger.error(f"Failed to fetch tutorials: {e}")
            state.tutorials_loaded = False
        finally:
            state.tutorials_loading = False
            publish_tutorial_state(
                "tutorials_list",
                "filtered_tutorials",
                "tutorials_loaded",
                "tutorials_loading",
            )
            tutorial_fetch_lock.release()

    # Listeners for state changes
    @state.change("case_root")
    def on_case_root_change(case_root, **_):
        if not case_root:
            return
        save_config({"CASE_ROOT": case_root})
        scan_cases()

    @state.change("active_case")
    def on_active_case_change(active_case, **_):
        if not active_case:
            return
        save_config({"ACTIVE_CASE": active_case})

    @state.change("docker_image", "openfoam_version")
    def on_docker_config_change(docker_image, openfoam_version, **_):
        if not docker_image or not openfoam_version:
            return
        save_config({"DOCKER_IMAGE": docker_image, "OPENFOAM_VERSION": openfoam_version})
        state.tutorials_loaded = False
        state.flush()
        threading.Thread(target=run_docker_checks, daemon=True).start()

    @state.change("tutorial_search", "tutorials_list")
    def on_tutorial_search_change(**_):
        search_val = state.tutorial_search
        query = str(search_val).lower() if search_val else ""
        t_list = state.tutorials_list or []
        if not query:
            state.filtered_tutorials = t_list
        else:
            state.filtered_tutorials = [
                t for t in t_list if query in t.lower()
            ]
        state.flush()

    @state.change("case_creation_tab")
    def on_case_creation_tab_change(case_creation_tab, **_):
        if int(case_creation_tab) == 1:
            trigger_fetch_tutorials()

    def trigger_checks():
        threading.Thread(target=run_docker_checks, daemon=True).start()
    ctrl.trigger_checks = trigger_checks

    def trigger_fetch_tutorials():
        threading.Thread(target=fetch_tutorials, daemon=True).start()
    ctrl.trigger_fetch_tutorials = trigger_fetch_tutorials

    def create_blank_case():
        name = state.new_case_name.strip()
        if not name:
            return

        path = Path(state.case_root) / name
        try:
            (path / "0").mkdir(parents=True, exist_ok=True)
            (path / "constant" / "triSurface").mkdir(parents=True, exist_ok=True)
            (path / "system").mkdir(parents=True, exist_ok=True)

            with (path / "system" / "controlDict").open("w", encoding="utf-8") as f:
                f.write(
                    "FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }\n"
                    "application simpleFoam; startFrom startTime; startTime 0; stopAt endTime; "
                    "endTime 1000; deltaT 1; writeControl timeStep; writeInterval 100;\n"
                )

            state.new_case_name = ""
            scan_cases()
            state.active_case = name
            save_config({"ACTIVE_CASE": name})
            state.flush()
        except Exception as e:
            logger.error(f"Error creating case: {e}")
    ctrl.create_blank_case = create_blank_case

    def import_tutorial_case():
        tut = state.selected_tutorial
        if not tut:
            return

        state.setup_status = f"Importing tutorial {tut}..."
        state.setup_status_color = "info"
        state.flush()

        def run_import():
            try:
                client = get_docker_client()
                if not client:
                    state.setup_status = "Docker not available for tutorial import."
                    state.setup_status_color = "error"
                    state.flush()
                    return

                tut_name = posixpath.basename(tut)
                bashrc = f"/opt/openfoam{state.openfoam_version}/etc/bashrc"
                container_run_path = "/tmp/FOAM_Run"
                container_case_path = posixpath.join(container_run_path, tut_name)

                host_path = Path(state.case_root).resolve()
                host_path_str = (
                    host_path.as_posix()
                    if platform.system() == "Windows"
                    else str(host_path)
                )

                shell_cmd = f'source "$1" && mkdir -p "$2" && cp -r $FOAM_TUTORIALS/"$3"/* "$2"'
                if platform.system() != "Windows":
                    shell_cmd += ' && chmod +x "$2"/Allrun'

                docker_cmd = [
                    "bash", "-c", shell_cmd,
                    "load_tutorial",
                    bashrc,
                    container_case_path,
                    tut,
                ]

                client.containers.run(
                    state.docker_image,
                    docker_cmd,
                    remove=True,
                    volumes={host_path_str: {"bind": container_run_path, "mode": "rw"}},
                    working_dir=container_run_path,
                )

                state.setup_status = f"Tutorial {tut_name} imported successfully."
                state.setup_status_color = "success"
                scan_cases()
                state.active_case = tut_name
                save_config({"ACTIVE_CASE": tut_name})
                state.flush()
            except Exception as e:
                logger.error(f"Error importing tutorial: {e}")
                state.setup_status = f"Import failed: {e}"
                state.setup_status_color = "error"
                state.flush()

        threading.Thread(target=run_import, daemon=True).start()
    ctrl.import_tutorial_case = import_tutorial_case

    # Initialize scans/checks on startup
    scan_cases()
    # Restore saved active_case if valid
    saved_active = config.get("ACTIVE_CASE", "")
    if saved_active and saved_active in state.cases_list:
        state.active_case = saved_active
    elif state.cases_list:
        state.active_case = state.cases_list[0]
    trigger_checks()


def build_setup_drawer():
    from trame.app import get_server
    server = get_server()
    ctrl = server.controller

    with html.Div(v_show="active_tab === 0", classes="pa-4"):
        # Header / Status Cards in Sidebar
        html.Div("Health Checkup 💊", classes="text-subtitle-1 font-weight-bold text-slate-800 mb-2", style="color: #0f172a;")
        vuetify.VAlert(
            "{{ trame_status }}",
            type=("trame_status_color", "success"),
            dense=True,
            outlined=True,
            classes="mb-2 setup-status-alert",
        )
        vuetify.VAlert(
            "{{ setup_status }}",
            type=("setup_status_color", "info"),
            dense=True,
            outlined=True,
            classes="mb-3 setup-status-alert",
        )


def build_setup_content():
    from trame.app import get_server
    server = get_server()
    ctrl = server.controller
    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-6 setup-page",
        v_if="active_tab === 0",
    ):
        with vuetify.VRow(justify="center", classes="setup-page-row"):
            with vuetify.VCol(cols="12", md="10", lg="8", xl="7", classes="setup-card-stack"):
                # Clear glass shell with matte glass panels, inspired by FOAMFlask.
                with html.Div(classes="setup-glass-shell"):
                    # Active Case Card
                    with vuetify.VCard(
                        classes="pa-4 glass-card setup-main-card setup-case-card",
                        style=(
                            "((case_creation_tab === 0 && new_case_name && new_case_name.trim().length > 0) || "
                            "(case_creation_tab === 1 && ((tutorial_search && tutorial_search.trim().length > 0) || selected_tutorial))) "
                            "? 'opacity: 0.56; filter: saturate(0.72); transform: scale(0.995);' : ''",
                        ),
                    ):
                        with vuetify.VCardTitle():
                            html.H2("Active Case", classes="setup-card-heading")
                        with vuetify.VCardText():
                            html.P(
                                "Select the case you want to work on. This selection applies to Geometry, Meshing, and Run tabs.",
                                classes="text-caption setup-section-copy",
                                v_if="cases_list && cases_list.length > 0",
                            )
                            with html.Div(
                                classes="setup-empty-state d-flex align-center",
                                v_if="!cases_list || cases_list.length === 0",
                            ):
                                vuetify.VIcon("mdi-folder-open-outline", classes="mr-3 setup-empty-state-icon")
                                with html.Div():
                                    html.Div("No active cases found", classes="setup-empty-state-title")
                                    html.Div(
                                        "Create or import a case below, then refresh the list.",
                                        classes="setup-empty-state-copy",
                                    )
                            with vuetify.VRow(align="center", classes="setup-control-row"):
                                with vuetify.VCol(cols="8"):
                                    vuetify.VSelect(
                                        v_model=("active_case",),
                                        items=("cases_list",),
                                        label="Choose Case",
                                        outlined=True,
                                        hide_details=True,
                                        disabled=("!cases_list || cases_list.length === 0",),
                                    )
                                with vuetify.VCol(cols="4"):
                                    vuetify.VBtn(
                                        "Refresh List",
                                        click=ctrl.scan_cases,
                                        block=True,
                                        classes="theme-btn-primary",
                                    )

                    # Case Management Tabs Card
                    with vuetify.VCard(
                        classes="pa-4 glass-card setup-main-card setup-creation-card",
                        style=(
                            "case_creation_tab === 1 ? 'min-height: 560px;' : 'min-height: 390px;'",
                        ),
                    ):
                        with vuetify.VCardTitle():
                            html.H2(
                                "{{ case_creation_tab === 0 ? 'Create New Case' : 'Import Tutorial' }}",
                                classes="setup-card-heading",
                            )
                        with vuetify.VCardText():
                            html.P(
                                "{{ case_creation_tab === 0 ? 'Initialize a blank case with standard structure (0, constant, system).' : 'Clone an official OpenFOAM tutorial into your workspace.' }}",
                                classes="text-caption setup-section-copy",
                            )
                            with vuetify.VTabs(
                                v_model=("case_creation_tab", 0),
                                grow=True,
                                classes="setup-case-tabs",
                            ):
                                vuetify.VTab("Create Blank Case")
                                vuetify.VTab("Import Tutorial", click=ctrl.trigger_fetch_tutorials)

                            with vuetify.VTabsItems(v_model=("case_creation_tab",)):
                                # Create Case Panel
                                with vuetify.VTabItem():
                                    with vuetify.VContainer(classes="pa-0 setup-tab-form"):
                                        vuetify.VTextField(
                                            v_model=("new_case_name",),
                                            label="New Case Name",
                                            placeholder="e.g., cavity_flow",
                                            outlined=True,
                                            hide_details=True,
                                            classes="setup-name-field",
                                        )
                                        vuetify.VBtn(
                                            "Create Case",
                                            click=ctrl.create_blank_case,
                                            block=True,
                                            classes="theme-btn-success",
                                        )
                                # Import Tutorial Panel
                                with vuetify.VTabItem():
                                    with vuetify.VContainer(classes="pa-0 setup-tab-form"):
                                        html.Div(
                                            "Select Tutorial Source",
                                            classes="tutorial-source-label",
                                        )
                                        vuetify.VTextField(
                                            v_model=("tutorial_search",),
                                            placeholder="Search tutorials...",
                                            prepend_inner_icon="mdi-magnify",
                                            outlined=True,
                                            hide_details=True,
                                            classes="setup-tutorial-field",
                                        )
                                        with vuetify.VRow(classes="tutorial-picker-row"):
                                            with vuetify.VCol(cols="12", md="8", classes="tutorial-list-column"):
                                                with vuetify.VList(classes="tutorial-list pa-0"):
                                                    with vuetify.VListItemGroup(
                                                        v_model=("selected_tutorial",),
                                                        color="cyan darken-3",
                                                    ):
                                                        with vuetify.VListItem(
                                                            v_for="tutorial in filtered_tutorials",
                                                            key=("tutorial",),
                                                            value=("tutorial",),
                                                            classes="tutorial-list-item",
                                                        ):
                                                            vuetify.VListItemTitle("{{ tutorial }}")
                                                    with html.Div(
                                                        classes="tutorial-list-message",
                                                        v_if="tutorials_loading",
                                                    ):
                                                        vuetify.VProgressCircular(
                                                            indeterminate=True,
                                                            size=24,
                                                            width=3,
                                                            color="cyan darken-2",
                                                            classes="mr-2",
                                                        )
                                                        html.Span("Loading tutorials…")
                                                    html.Div(
                                                        "No tutorials found",
                                                        classes="tutorial-list-message",
                                                        v_if="!tutorials_loading && filtered_tutorials.length === 0",
                                                    )
                                            with vuetify.VCol(cols="12", md="4", classes="tutorial-action-column"):
                                                with vuetify.VBtn(
                                                    click=ctrl.import_tutorial_case,
                                                    block=True,
                                                    classes="theme-btn-info tutorial-import-button",
                                                    disabled=("!selected_tutorial || tutorials_loading",),
                                                ):
                                                    vuetify.VIcon("mdi-download", classes="mr-2")
                                                    html.Span("Import Tutorial")

                # Advanced Settings Expansion Panel
                with vuetify.VExpansionPanels(classes="glass-card setup-advanced-card"):
                    with vuetify.VExpansionPanel():
                        with vuetify.VExpansionPanelHeader(classes="subtitle-2 font-weight-bold"):
                            html.Span("Advanced Settings (Docker, Case Path)")
                        with vuetify.VExpansionPanelContent():
                            vuetify.VTextField(
                                v_model=("case_root",),
                                label="Case Root Directory",
                                outlined=True,
                                dense=True,
                            )
                            vuetify.VTextField(
                                v_model=("docker_image",),
                                label="OpenFOAM Docker Image",
                                outlined=True,
                                dense=True,
                            )
                            vuetify.VTextField(
                                v_model=("openfoam_version",),
                                label="OpenFOAM Version",
                                outlined=True,
                                dense=True,
                            )
                            vuetify.VBtn(
                                "Save Config & Check Docker",
                                click=ctrl.trigger_checks,
                                block=True,
                                classes="theme-btn-warning",
                            )

                # Footer Glass Overlay Card
                with vuetify.VCard(classes="glass-card setup-footer-card"):
                    with html.Div(classes="setup-footer-layout"):
                        with html.Div(classes="setup-footer-identity"):
                            html.Div(
                                "FOAMTrame © 2026",
                                classes="setup-footer-title",
                            )
                            html.Div(
                                "Licensed under GNU GPLv3",
                                classes="setup-footer-license",
                            )
                        with html.Div(classes="setup-footer-powered"):
                            html.Span(
                                "Powered by",
                                classes="setup-footer-label",
                            )
                            html.Img(
                                src="/static/icons/docker-logo.avif",
                                alt="Docker Logo",
                                classes="setup-footer-docker-logo",
                            )
                            html.Img(
                                src="/static/icons/trame-text.svg",
                                alt="Trame Logo",
                                classes="setup-footer-trame-logo",
                            )
                        with html.Div(
                            classes="footer-openfoam-version d-flex align-center",
                            title=("openfoam_runtime_source",),
                        ):
                            html.Img(
                                src=(
                                    "(String(openfoam_runtime_version || openfoam_version || '').match(/\\d/g) || []).length >= 4 "
                                    "? '/static/icons/openfoam-vXXXX_series.svg' "
                                    ": '/static/icons/openfoam-vXX_series.png'",
                                ),
                                alt="OpenFOAM Logo",
                                classes="footer-openfoam-logo",
                            )
                            html.Span(
                                "{{ openfoam_runtime_label }}",
                                classes="setup-footer-version-text",
                            )

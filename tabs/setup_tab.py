from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import posixpath
import shutil
import threading
from pathlib import Path
from trame.widgets import html, vuetify

logger = logging.getLogger("FOAMTrame")

CONFIG_FILE = Path("case_config.json")


# --- Configuration helpers ---
def load_config() -> dict:
    defaults = {
        "CASE_ROOT": str(Path("tutorial_cases").resolve()),
        "DOCKER_IMAGE": "haldardhruv/ubuntu_noble_openfoam:v12",
        "OPENFOAM_VERSION": "12",
        "ACTIVE_CASE": "",
    }
    if not CONFIG_FILE.exists():
        return defaults
    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return {**defaults, **data}
    except Exception:
        return defaults


def save_config(updates: dict) -> bool:
    config = load_config()
    config.update(updates)
    try:
        with CONFIG_FILE.open("w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return True
    except Exception:
        return False


def get_docker_client():
    try:
        import docker
        client = docker.from_env(timeout=5)
        client.ping()
        return client
    except Exception:
        return None


# --- Setup Tab Controller and State ---
def setup_setup_tab(server):
    state, ctrl = server.state, server.controller

    # Load initial config
    config = load_config()
    state.setdefault("case_root", config["CASE_ROOT"])
    state.setdefault("docker_image", config["DOCKER_IMAGE"])
    state.setdefault("openfoam_version", config["OPENFOAM_VERSION"])

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

    @ctrl.add("on_server_ready")
    def capture_server_event_loop(**_):
        """Capture the wslink loop used for thread-safe client state pushes."""
        server_event_loop[0] = asyncio.get_running_loop()
        server.force_state_push(
            "tutorials_list",
            "filtered_tutorials",
            "tutorials_loaded",
            "tutorials_loading",
        )

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
        state.setup_status = "Checking Docker executable..."
        state.setup_status_color = "info"
        state.dirty("setup_status", "setup_status_color", "docker_checking")
        state.flush()

        if not shutil.which("docker"):
            state.setup_status = "Docker executable not found in PATH."
            state.setup_status_color = "error"
            state.docker_checking = False
            state.dirty("setup_status", "setup_status_color", "docker_checking")
            state.flush()
            return

        state.setup_status = "Connecting to Docker daemon..."
        state.dirty("setup_status")
        state.flush()

        client = get_docker_client()
        if not client:
            state.setup_status = "Cannot connect to Docker daemon. Make sure Docker Desktop is running."
            state.setup_status_color = "error"
            state.docker_checking = False
            state.dirty("setup_status", "setup_status_color", "docker_checking")
            state.flush()
            return

        state.setup_status = f"Checking Docker image {state.docker_image}..."
        state.dirty("setup_status")
        state.flush()

        try:
            import docker.errors
            client.images.get(state.docker_image)
            state.setup_status = "Docker integration ready."
            state.setup_status_color = "success"
            state.docker_checking = False
            state.dirty("setup_status", "setup_status_color", "docker_checking")
            state.flush()
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
            state.dirty("setup_status", "setup_status_color", "docker_checking")
            state.flush()

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
                    with vuetify.VCard(classes="pa-4 glass-card setup-main-card setup-case-card"):
                        with vuetify.VCardTitle():
                            html.H2("Active Case Selection", classes="setup-card-heading")
                        with vuetify.VCardText():
                            html.P(
                                "Select the active OpenFOAM case to run or configure. This will be used in subsequent tabs.",
                                classes="text-caption text-secondary",
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
                    with vuetify.VCard(classes="pa-4 glass-card setup-main-card setup-creation-card"):
                        with vuetify.VCardTitle():
                            html.H2("Case Creation & Imports", classes="setup-card-heading")
                        with vuetify.VCardText():
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
                                        vuetify.VTextField(
                                            v_model=("tutorial_search",),
                                            label="Search Tutorials",
                                            outlined=True,
                                            hide_details=True,
                                            classes="setup-tutorial-field",
                                        )
                                        vuetify.VSelect(
                                            v_model=("selected_tutorial",),
                                            items=("filtered_tutorials",),
                                            label="Select OpenFOAM Tutorial",
                                            outlined=True,
                                            hide_details=True,
                                            classes="setup-tutorial-field",
                                            loading=("tutorials_loading",),
                                            disabled=("tutorials_loading",),
                                            no_data_text=(
                                                "tutorials_loading ? 'Loading tutorials…' : 'No tutorials found'",
                                            ),
                                        )
                                        vuetify.VBtn(
                                            "Import Tutorial Case",
                                            click=ctrl.import_tutorial_case,
                                            block=True,
                                            classes="theme-btn-info",
                                        )

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
                with vuetify.VCard(classes="pa-3 glass-card setup-footer-card"):
                    with html.Div(classes="d-flex flex-wrap align-center justify-space-between text-center gap-2"):
                        html.Div(
                            "FOAMTrame © 2026",
                            classes="text-subtitle-2 font-weight-bold mx-2",
                            style="color: #0f172a;",
                        )
                        html.Div(
                            "Licensed under GNU GPLv3",
                            classes="text-caption font-weight-medium mx-2",
                            style="color: #475569;",
                        )
                        with html.Div(classes="d-flex align-center justify-center mx-2"):
                            html.Span(
                                "Powered by:",
                                classes="text-caption font-weight-medium mr-2",
                                style="color: #475569;",
                            )
                            html.Img(
                                src="/static/icons/docker-logo.avif",
                                alt="Docker Logo",
                                height="26",
                                classes="mr-3",
                                style="object-fit: contain;",
                            )
                            html.Img(
                                src="/static/icons/trame-text.svg",
                                alt="Trame Logo",
                                height="22",
                                style="object-fit: contain;",
                            )

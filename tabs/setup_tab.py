from __future__ import annotations

import logging
import threading
import requests
from trame.widgets import html, vuetify

logger = logging.getLogger("FOAMFlask")

FLASK_URL = "http://127.0.0.1:5000"

def setup_setup_tab(server):
    state, ctrl = server.state, server.controller

    # State variables
    state.setdefault("case_root", "")
    state.setdefault("docker_image", "")
    state.setdefault("openfoam_version", "")
    state.setdefault("setup_status", "Connecting to backend...")
    state.setdefault("setup_status_color", "info")
    state.setdefault("active_case", "")
    state.setdefault("cases_list", [])
    state.setdefault("new_case_name", "")
    state.setdefault("tutorials_list", [])
    state.setdefault("tutorial_search", "")
    state.setdefault("filtered_tutorials", [])
    state.setdefault("selected_tutorial", "")
    state.setdefault("case_creation_tab", 0)
    state.setdefault("tutorials_loaded", False)

    # Helper function to load initial configuration from Flask
    def sync_config():
        try:
            r1 = requests.get(f"{FLASK_URL}/get_case_root", timeout=5).json()
            state.case_root = r1.get("caseDir", "")
            
            r2 = requests.get(f"{FLASK_URL}/get_docker_config", timeout=5).json()
            state.docker_image = r2.get("dockerImage", "")
            state.openfoam_version = r2.get("openfoamVersion", "")
            
            # Fetch active case
            r3 = requests.get(f"{FLASK_URL}/get_active_case", timeout=5).json()
            active = r3.get("activeCase", "")
            
            # Populate cases_list
            res = requests.get(f"{FLASK_URL}/api/cases/list", timeout=5).json()
            cases = res.get("cases", [])
            state.cases_list = cases
            
            if active in cases:
                state.active_case = active
            elif cases:
                state.active_case = cases[0]
            else:
                state.active_case = ""
                
            state.flush()
            trigger_checks()
        except Exception as e:
            state.setup_status = f"Backend unavailable: {e}"
            state.setup_status_color = "error"
            state.flush()

    def scan_cases():
        try:
            res = requests.get(f"{FLASK_URL}/api/cases/list", timeout=5).json()
            state.cases_list = res.get("cases", [])
            state.flush()
        except Exception as e:
            logger.error(f"Error scanning cases from Flask: {e}")

    ctrl.scan_cases = scan_cases

    def run_docker_checks():
        import time
        for _ in range(15):
            try:
                res = requests.get(f"{FLASK_URL}/api/startup_status", timeout=5).json()
                status = res.get("status")
                state.setup_status = res.get("message", "Checked.")
                
                if status == "completed":
                    state.setup_status_color = "success"
                    state.flush()
                    fetch_tutorials()
                    break
                elif status == "warning":
                    state.setup_status_color = "warning"
                    state.flush()
                    fetch_tutorials()
                    break
                elif status == "failed":
                    state.setup_status_color = "error"
                    state.flush()
                    break
                else:
                    state.setup_status_color = "warning"
                
                state.flush()
                time.sleep(1.5)
            except Exception as e:
                state.setup_status = f"Error checking Docker: {e}"
                state.setup_status_color = "error"
                state.flush()
                break

    def fetch_tutorials():
        if state.tutorials_loaded:
            return
        try:
            res = requests.get(f"{FLASK_URL}/api/tutorials", timeout=30).json()
            tuts = res.get("tutorials", [])
            if tuts:
                state.tutorials_list = tuts
                state.filtered_tutorials = tuts
                state.tutorials_loaded = True
                state.flush()
        except Exception as e:
            logger.error(f"Error fetching tutorials: {e}")

    # Listeners for state changes
    @state.change("case_root")
    def on_case_root_change(case_root, **_):
        if not case_root:
            return
        def save():
            try:
                requests.post(f"{FLASK_URL}/set_case", json={"caseDir": case_root}, timeout=5)
                scan_cases()
            except Exception:
                pass
        threading.Thread(target=save, daemon=True).start()

    @state.change("active_case")
    def on_active_case_change(active_case, **_):
        if not active_case:
            return
        def save():
            try:
                requests.post(f"{FLASK_URL}/set_active_case", json={"activeCase": active_case}, timeout=5)
            except Exception:
                pass
        threading.Thread(target=save, daemon=True).start()

    @state.change("docker_image", "openfoam_version")
    def on_docker_config_change(docker_image, openfoam_version, **_):
        if not docker_image or not openfoam_version:
            return
        def save():
            try:
                requests.post(
                    f"{FLASK_URL}/set_docker_config",
                    json={"dockerImage": docker_image, "openfoamVersion": openfoam_version},
                    timeout=5
                )
                state.tutorials_loaded = False
                state.flush()
                run_docker_checks()
            except Exception:
                pass
        threading.Thread(target=save, daemon=True).start()

    @state.change("tutorial_search", "tutorials_list")
    def on_tutorial_search_change(**_):
        query = state.tutorial_search.lower()
        if not query:
            state.filtered_tutorials = state.tutorials_list
        else:
            state.filtered_tutorials = [t for t in state.tutorials_list if query in t.lower()]
        state.flush()

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
        def create():
            try:
                res = requests.post(f"{FLASK_URL}/api/case/create", json={"caseName": name}, timeout=5).json()
                if res.get("success"):
                    state.new_case_name = ""
                    scan_cases()
                    state.active_case = name
                    state.flush()
            except Exception as e:
                logger.error(f"Failed to create case: {e}")
        threading.Thread(target=create, daemon=True).start()
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
                res = requests.post(f"{FLASK_URL}/load_tutorial", json={"tutorial": tut}, timeout=60).json()
                if "error" not in res.get("output", "").lower():
                    state.setup_status = "Tutorial imported successfully."
                    state.setup_status_color = "success"
                    scan_cases()
                    import posixpath
                    state.active_case = posixpath.basename(tut)
                else:
                    state.setup_status = res.get("output", "Import failed.")
                    state.setup_status_color = "error"
                state.flush()
            except Exception as e:
                state.setup_status = f"Import failed: {e}"
                state.setup_status_color = "error"
                state.flush()
        threading.Thread(target=run_import, daemon=True).start()
    ctrl.import_tutorial_case = import_tutorial_case

    # Sync and initialize config from Flask
    threading.Thread(target=sync_config, daemon=True).start()


def build_setup_drawer():
    from trame.app import get_server
    server = get_server()
    ctrl = server.controller
    with html.Div(v_show="active_tab === 0"):
        vuetify.VNavigationDrawer(
            permanent=True,
            width="100%",
            classes="glass-drawer",
        )


def build_setup_content():
    from trame.app import get_server
    server = get_server()
    ctrl = server.controller
    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-6",
        v_if="active_tab === 0",
    ):
        with vuetify.VRow(classes="justify-center"):
            with vuetify.VCol(cols="12", md="8", lg="6"):
                # Header card
                with vuetify.VCard(classes="pa-4 mb-4 glass-card"):
                    with vuetify.VCardTitle(classes="headline font-weight-bold"):
                        html.Span("FOAMFlask Setup")
                    with vuetify.VCardText():
                        vuetify.VAlert(
                            "{{ setup_status }}",
                            type=("setup_status_color", "info"),
                            dense=True,
                            outlined=True,
                            classes="mb-4",
                        )

                # Active Case Card
                with vuetify.VCard(classes="pa-4 mb-4 glass-card"):
                    with vuetify.VCardTitle(classes="subtitle-1 font-weight-bold"):
                        html.Span("Active Case Selection")
                    with vuetify.VCardText():
                        html.P(
                            "Select the active OpenFOAM case to run or configure. This will be used in subsequent tabs.",
                            classes="text-caption text-secondary",
                        )
                        with vuetify.VRow(align="center"):
                            with vuetify.VCol(cols="8"):
                                vuetify.VSelect(
                                    v_model=("active_case",),
                                    items=("cases_list",),
                                    label="Choose Case",
                                    outlined=True,
                                    dense=True,
                                    hide_details=True,
                                )
                            with vuetify.VCol(cols="4"):
                                vuetify.VBtn(
                                    "Refresh List",
                                    click=ctrl.scan_cases,
                                    block=True,
                                    classes="theme-btn-primary",
                                )

                # Case Management Tabs Card
                with vuetify.VCard(classes="pa-4 mb-4 glass-card"):
                    with vuetify.VCardTitle(classes="subtitle-1 font-weight-bold"):
                        html.Span("Case Creation & Imports")
                    with vuetify.VCardText():
                        with vuetify.VTabs(v_model=("case_creation_tab", 0), grow=True):
                            vuetify.VTab("Create Blank Case")
                            vuetify.VTab("Import Tutorial", click=ctrl.trigger_fetch_tutorials)
                        
                        with vuetify.VTabsItems(v_model=("case_creation_tab",)):
                            # Create Case Panel
                            with vuetify.VTabItem():
                                with vuetify.VContainer(classes="pa-3"):
                                    vuetify.VTextField(
                                        v_model=("new_case_name",),
                                        label="New Case Name",
                                        placeholder="e.g., cavity_flow",
                                        outlined=True,
                                        dense=True,
                                    )
                                    vuetify.VBtn(
                                        "Create Case",
                                        click=ctrl.create_blank_case,
                                        block=True,
                                        classes="theme-btn-success",
                                    )
                            # Import Tutorial Panel
                            with vuetify.VTabItem():
                                with vuetify.VContainer(classes="pa-3"):
                                    vuetify.VTextField(
                                        v_model=("tutorial_search",),
                                        label="Search Tutorials",
                                        outlined=True,
                                        dense=True,
                                        hide_details=True,
                                        classes="mb-3",
                                    )
                                    # List filtered tutorials
                                    vuetify.VSelect(
                                        v_model=("selected_tutorial",),
                                        items=("filtered_tutorials",),
                                        label="Select OpenFOAM Tutorial",
                                        outlined=True,
                                        dense=True,
                                        classes="mb-3",
                                    )
                                    vuetify.VBtn(
                                        "Import Tutorial Case",
                                        click=ctrl.import_tutorial_case,
                                        block=True,
                                        classes="theme-btn-info",
                                    )

                # Advanced Settings Expansion Panel
                with vuetify.VExpansionPanels(classes="glass-card"):
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

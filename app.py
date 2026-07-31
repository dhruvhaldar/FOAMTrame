from __future__ import annotations

from trame.app import get_server
from trame.ui.vuetify import SinglePageWithDrawerLayout
from trame.widgets import vuetify, html

from tabs.geometry_tab import (
    build_geometry_content,
    build_geometry_drawer,
    setup_geometry_tab,
)
from tabs.meshing_tab import (
    build_meshing_content,
    build_meshing_drawer,
    setup_meshing_tab,
)
from tabs.plots_tab import (
    build_plots_content,
    build_plots_drawer,
    setup_plots_tab,
)
from tabs.run_log_tab import (
    build_run_log_content,
    build_run_log_drawer,
    setup_run_log_tab,
)
from tabs.setup_tab import (
    build_setup_content,
    build_setup_drawer,
    setup_setup_tab,
)
from tabs.visualizer_tab import (
    build_visualizer_content,
    build_visualizer_drawer,
    setup_visualizer_tab,
)

server = get_server(client_type="vue2")
server.cli.add_argument("--data", help="Optional dataset to load at startup")
state, ctrl = server.state, server.controller

# Setup tab modules
setup_setup_tab(server)
setup_geometry_tab(server)
setup_meshing_tab(server)
setup_run_log_tab(server)
setup_plots_tab(server)
load_dataset = setup_visualizer_tab(server)

state.setdefault("active_tab", 0)

with SinglePageWithDrawerLayout(server) as layout:
    layout.title.set_text("FOAMFlask_v2")
    layout.icon.hide()
    
    with layout:
        html.Style("""
            body.v-application {
                background: linear-gradient(180deg, hsla(192, 100%, 86%, 1) 0%, hsla(292, 37%, 88%, 1) 100%) !important;
            }
            .v-application--wrap {
                background: transparent !important;
            }
            .theme--light.v-card.glass-card {
                background: rgba(255, 255, 255, 0.45) !important;
                backdrop-filter: blur(12px) !important;
                -webkit-backdrop-filter: blur(12px) !important;
                border: 1px solid rgba(255, 255, 255, 0.6) !important;
                border-radius: 16px !important;
                box-shadow: 0 4px 30px rgba(0, 0, 0, 0.05), inset 0 0 10px rgba(255, 255, 255, 0.25) !important;
            }
            .theme--light.v-sheet.glass-drawer {
                background: rgba(255, 255, 255, 0.3) !important;
                backdrop-filter: blur(12px) !important;
                -webkit-backdrop-filter: blur(12px) !important;
                border-right: 1px solid rgba(255, 255, 255, 0.4) !important;
            }
            .theme--light.v-app-bar.glass-navbar {
                background: rgba(255, 255, 255, 0.25) !important;
                backdrop-filter: blur(12px) !important;
                -webkit-backdrop-filter: blur(12px) !important;
                border-bottom: 1px solid rgba(255, 255, 255, 0.4) !important;
                box-shadow: none !important;
            }
            .v-btn.theme-btn-primary {
                background-color: #06b6d4 !important;
                color: white !important;
            }
            .v-btn.theme-btn-success {
                background-color: #22c55e !important;
                color: white !important;
            }
            .v-btn.theme-btn-warning {
                background-color: #f59e0b !important;
                color: white !important;
            }
            .v-btn.theme-btn-info {
                background-color: #06b6d4 !important;
                color: white !important;
            }
        """)

    layout.toolbar.classes = "glass-navbar"
    with layout.toolbar:
        with vuetify.VTabs(
            v_model=("active_tab", 0),
            dense=True,
            background_color="transparent",
            classes="ml-4",
        ):
            vuetify.VTab("Setup")
            vuetify.VTab("Geometry")
            vuetify.VTab("Meshing")
            vuetify.VTab("Run/Log")
            vuetify.VTab("Plots")
            vuetify.VTab("Post")
        vuetify.VSpacer()
        vuetify.VBtn(
            "Reset camera",
            click=ctrl.reset_camera,
            icon="mdi-camera-retake-outline",
            text=True,
            v_if="active_tab === 4 || active_tab === 5",
        )

    layout.drawer.classes = "glass-drawer"
    with layout.drawer:
        build_setup_drawer()
        build_geometry_drawer()
        build_meshing_drawer()
        build_run_log_drawer()
        build_plots_drawer()
        build_visualizer_drawer(ctrl)

    with layout.content:
        build_setup_content()
        build_geometry_content()
        build_meshing_content()
        build_run_log_content()
        build_plots_content()
        build_visualizer_content(ctrl)


def main():
    args, _ = server.cli.parse_known_args()
    if args.data:
        try:
            load_dataset(args.data)
        except Exception as exc:
            state.error_message = str(exc)
    server.start(port=8087)


if __name__ == "__main__":
    main()

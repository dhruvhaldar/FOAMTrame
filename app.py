from __future__ import annotations

from trame.app import get_server
from trame.ui.vuetify import SinglePageWithDrawerLayout
from trame.widgets import vuetify

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

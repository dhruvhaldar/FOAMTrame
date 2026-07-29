from __future__ import annotations

from trame.app import get_server
from trame.ui.vuetify import SinglePageWithDrawerLayout
from trame.widgets import vuetify

from run import build_run_content, build_run_drawer, setup_run
from visualizer import (
    build_visualizer_content,
    build_visualizer_drawer,
    setup_visualizer,
)

server = get_server(client_type="vue2")
server.cli.add_argument("--data", help="Optional dataset to load at startup")
state, ctrl = server.state, server.controller

# Setup tabs
load_dataset = setup_visualizer(server)
setup_run(server)

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
            vuetify.VTab("Visualizer")
            vuetify.VTab("Run")
        vuetify.VSpacer()
        vuetify.VBtn(
            "Reset camera",
            click=ctrl.reset_camera,
            icon="mdi-camera-retake-outline",
            text=True,
            v_if="active_tab === 0",
        )

    with layout.drawer:
        build_visualizer_drawer()
        build_run_drawer()

    with layout.content:
        build_visualizer_content(ctrl)
        build_run_content()


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

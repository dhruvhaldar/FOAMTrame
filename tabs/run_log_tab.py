from __future__ import annotations

from trame.widgets import html, vuetify


def setup_run_log_tab(server):
    state, ctrl = server.state, server.controller
    # State defaults or handlers for Run/Log tab can be placed here


def build_run_log_drawer():
    with html.Div(v_show="active_tab === 3"):
        pass


def build_run_log_content():
    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-6",
        v_if="active_tab === 3",
    ):
        html.Div(classes="fill-height w-100")

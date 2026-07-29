from __future__ import annotations

from trame.widgets import html, vuetify


def setup_run(server):
    state, ctrl = server.state, server.controller
    # State defaults or controller actions for Run tab can be placed here


def build_run_drawer():
    with html.Div(v_show="active_tab === 1"):
        pass


def build_run_content():
    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-6",
        v_if="active_tab === 1",
    ):
        html.Div(classes="fill-height w-100")

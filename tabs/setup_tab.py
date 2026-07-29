from __future__ import annotations

from trame.widgets import html, vuetify


def setup_setup_tab(server):
    state, ctrl = server.state, server.controller
    # State defaults or handlers for Setup tab can be placed here


def build_setup_drawer():
    with html.Div(v_show="active_tab === 0"):
        pass


def build_setup_content():
    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-6",
        v_if="active_tab === 0",
    ):
        html.Div(classes="fill-height w-100")

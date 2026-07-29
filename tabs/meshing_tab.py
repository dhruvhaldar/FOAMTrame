from __future__ import annotations

from trame.widgets import html, vuetify


def setup_meshing_tab(server):
    state, ctrl = server.state, server.controller
    # State defaults or handlers for Meshing tab can be placed here


def build_meshing_drawer():
    with html.Div(v_show="active_tab === 2"):
        pass


def build_meshing_content():
    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-6",
        v_if="active_tab === 2",
    ):
        html.Div(classes="fill-height w-100")

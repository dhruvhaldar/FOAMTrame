from __future__ import annotations

from trame.app import get_server
from trame.ui.vuetify import SinglePageWithDrawerLayout
from trame.widgets import vuetify, html, client

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
    layout.title.set_text("FOAMTrame")
    layout.title.style = "min-width: 160px; overflow: visible;"
    layout.icon.hide()
    
    # Inject CSS style sheet into the HTML head using client.Style
    client.Style("""
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
        
        .v-application {
            font-family: 'Inter', sans-serif !important;
        }
        .theme--light.v-application {
            background: linear-gradient(180deg, hsla(192, 100%, 86%, 1) 0%, hsla(292, 37%, 88%, 1) 100%) !important;
        }
        .v-application--wrap {
            background: transparent !important;
        }
        /* Rounded corners for cards, sheets, alerts, and panels */
        .v-application .v-sheet,
        .v-application .v-card,
        .v-application .v-alert,
        .v-application .v-expansion-panels,
        .v-application .v-expansion-panel {
            border-radius: 16px !important;
        }
        /* Rounded corners for input fields (text-fields, selects, textareas) */
        .v-application .v-input input,
        .v-application .v-input .v-input__control,
        .v-application .v-input .v-input__slot,
        .v-application .v-select__slot,
        .v-application .v-text-field--outlined fieldset {
            border-radius: 12px !important;
        }
        /* High-end Glassmorphism Cards */
        .v-application .glass-card {
            background: rgba(255, 255, 255, 0.55) !important;
            backdrop-filter: blur(24px) !important;
            -webkit-backdrop-filter: blur(24px) !important;
            border: 1px solid rgba(255, 255, 255, 0.7) !important;
            border-radius: 20px !important;
            box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.05), inset 0 0 16px rgba(255, 255, 255, 0.3) !important;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        }
        .v-application .glass-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 16px 48px 0 rgba(31, 38, 135, 0.08), inset 0 0 24px rgba(255, 255, 255, 0.4) !important;
            border-color: rgba(255, 255, 255, 0.9) !important;
        }
        /* Advanced Expansion Panel Glass fix */
        .v-application .v-expansion-panels.glass-card,
        .v-application .v-expansion-panel {
            background: rgba(255, 255, 255, 0.55) !important;
            border-radius: 20px !important;
        }
        .v-application .v-expansion-panel-header {
            background: transparent !important;
        }
        .v-application .v-expansion-panel-content__wrap {
            background: transparent !important;
        }
        /* Glass Sidebar and Navbar */
        .v-application .glass-drawer {
            background: rgba(255, 255, 255, 0.4) !important;
            backdrop-filter: blur(24px) !important;
            -webkit-backdrop-filter: blur(24px) !important;
            border-right: 1px solid rgba(255, 255, 255, 0.5) !important;
        }
        .v-application .glass-navbar {
            background: rgba(255, 255, 255, 0.35) !important;
            backdrop-filter: blur(20px) !important;
            -webkit-backdrop-filter: blur(20px) !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.5) !important;
            box-shadow: none !important;
        }
        /* Navbar Project Title Visibility */
        .v-application .v-toolbar__title {
            overflow: visible !important;
            white-space: nowrap !important;
            text-overflow: clip !important;
            flex: none !important;
            margin-right: 24px !important;
        }
        /* Active Case Name Pill Truncation and Squishing Prevention */
        .v-application .v-chip {
            overflow: visible !important;
            white-space: nowrap !important;
            flex: none !important;
            flex-shrink: 0 !important;
            margin-right: 24px !important;
        }
        .v-application .v-chip .v-chip__content {
            overflow: visible !important;
            white-space: nowrap !important;
        }
        /* Centered pill navigation tabs layout spacing fix */
        .glass-navbar .v-tabs {
            height: 36px !important;
            align-self: center !important;
        }
        .glass-navbar .v-tabs-bar {
            height: 36px !important;
            background-color: transparent !important;
        }
        .glass-navbar .v-tabs-bar__content {
            height: 36px !important;
            align-items: center !important;
        }
        .glass-navbar .v-tab {
            text-transform: none !important;
            font-weight: 700 !important;
            letter-spacing: normal !important;
            font-size: 0.92rem !important;
            border-radius: 12px !important;
            margin: 0 4px !important;
            min-width: 110px !important;  /* Uniform width for equal spacing */
            max-width: 110px !important;  /* Prevent stretching */
            width: 110px !important;      /* Force identical widths */
            flex: none !important;        /* Prevent flexbox resizing */
            padding: 0 8px !important;
            justify-content: center !important;
            text-align: center !important;
            height: 36px !important;
            color: #334155 !important; /* slate-700 */
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
            align-self: center !important;
        }
        .glass-navbar .v-tab:hover:not(.v-tab--active) {
            background: rgba(255, 255, 255, 0.3) !important;
            color: #0284c7 !important;
        }
        .glass-navbar .v-tab--active {
            color: white !important;
            background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%) !important;
            box-shadow: 0 4px 12px rgba(14, 165, 233, 0.3) !important;
        }
        .glass-navbar .v-tabs-slider-wrapper {
            display: none !important;
        }
        /* Glassify inner tabs and card components (e.g. Case Creation tabs) */
        .v-application .glass-card .v-tabs,
        .v-application .glass-card .v-tabs-bar,
        .v-application .glass-card .v-tabs-items,
        .v-application .glass-card .v-tab-item {
            background-color: transparent !important;
        }
        /* Pill Styling for sub-tabs inside cards */
        .v-application .glass-card .v-tab {
            text-transform: none !important;
            font-weight: 700 !important;
            letter-spacing: normal !important;
            font-size: 0.9rem !important;
            border-radius: 12px !important;
            height: 36px !important;
            color: #475569 !important; /* slate-600 */
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1) !important;
            margin: 4px 6px !important;
            background: rgba(0, 0, 0, 0.03) !important;
        }
        .v-application .glass-card .v-tab:hover:not(.v-tab--active) {
            background: rgba(0, 0, 0, 0.06) !important;
            color: #0284c7 !important;
        }
        .v-application .glass-card .v-tab--active {
            color: white !important;
            background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%) !important;
            box-shadow: 0 4px 12px rgba(14, 165, 233, 0.2) !important;
        }
        .v-application .glass-card .v-tabs-slider-wrapper {
            display: none !important;
        }
        /* Hide Default Footer */
        .v-footer {
            display: none !important;
        }
        /* Premium Button Accents */
        .v-application .v-btn.theme-btn-primary {
            background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%) !important;
            color: white !important;
            text-transform: none !important;
            font-weight: 600 !important;
            border-radius: 10px !important;
            box-shadow: 0 4px 14px 0 rgba(14, 165, 233, 0.3) !important;
        }
        .v-application .v-btn.theme-btn-success {
            background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
            color: white !important;
            text-transform: none !important;
            font-weight: 600 !important;
            border-radius: 10px !important;
            box-shadow: 0 4px 14px 0 rgba(16, 185, 129, 0.3) !important;
        }
        .v-application .v-btn.theme-btn-warning {
            background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%) !important;
            color: white !important;
            text-transform: none !important;
            font-weight: 600 !important;
            border-radius: 10px !important;
            box-shadow: 0 4px 14px 0 rgba(245, 158, 11, 0.3) !important;
        }
        .v-application .v-btn.theme-btn-info {
            background: linear-gradient(135deg, #06b6d4 0%, #0891b2 100%) !important;
            color: white !important;
            text-transform: none !important;
            font-weight: 600 !important;
            border-radius: 10px !important;
            box-shadow: 0 4px 14px 0 rgba(6, 182, 212, 0.3) !important;
        }
        .v-application .v-btn.theme-btn-error {
            background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important;
            color: white !important;
            text-transform: none !important;
            font-weight: 600 !important;
            border-radius: 10px !important;
            box-shadow: 0 4px 14px 0 rgba(239, 68, 68, 0.4) !important;
        }
        .v-application .v-btn.theme-btn-outlined {
            border-radius: 10px !important;
            text-transform: none !important;
            font-weight: 600 !important;
        }
        /* Premium Scrollbar */
        ::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(255, 255, 255, 0.1);
        }
        ::-webkit-scrollbar-thumb {
            background: rgba(3, 105, 161, 0.2);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(3, 105, 161, 0.4);
        }
    """)

    layout.toolbar.classes = "glass-navbar"
    with layout.toolbar:
        # Active case display chip next to FOAMTrame title
        vuetify.VChip(
            "{{ active_case }}",
            color="cyan lighten-5",
            text_color="cyan darken-3",
            classes="ml-3 font-weight-bold",
            label=True,
            small=True,
            v_if="active_case",
        )
        with vuetify.VTabs(
            v_model=("active_tab", 0),
            dense=True,
            background_color="transparent",
            classes="ml-4",
            hide_slider=True,
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
            v_if="active_tab === 5",
        )

    state.setdefault("drawer_open", False)

    @state.change("active_tab")
    def _on_tab_change(active_tab, **_):
        state.drawer_open = (int(active_tab) != 0)
        state.flush()

    layout.drawer.classes = "glass-drawer"
    layout.drawer.v_model = ("drawer_open",)
    with layout.drawer:
        build_setup_drawer()
        build_geometry_drawer()
        build_meshing_drawer()
        build_run_log_drawer()
        build_plots_drawer()
        build_visualizer_drawer(ctrl)

    with layout.content:
        with vuetify.VOverlay(
            v_model=("docker_checking", True),
            absolute=True,
            opacity=0.7,
            color="#0f172a",
            classes="d-flex flex-column align-center justify-center text-center",
            style="z-index: 9999;",
        ):
            vuetify.VProgressCircular(
                indeterminate=True,
                size=64,
                width=6,
                color="cyan lighten-2",
                classes="mb-4",
            )
            html.H3(
                "{{ setup_status }}",
                classes="white--text font-weight-medium mb-1",
            )
            html.P(
                "Please wait while Docker integration is initialized...",
                classes="cyan--text text--lighten-4 text-caption mb-0",
            )

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

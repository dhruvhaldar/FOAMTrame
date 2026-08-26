from __future__ import annotations

import sys

from runtime import configure_logging, install_asyncio_exception_handler, settings
from app_state import load_security_preferences
from security import (
    apply_trame_security,
    trame_bind_host,
    trame_session_timeout_seconds,
)

configure_logging()

from trame.app import get_server
from trame.ui.vuetify import SinglePageWithDrawerLayout
from trame.widgets import vuetify, html, client

from tabs.geometry_tab import (
    build_geometry_content,
    build_geometry_drawer,
    setup_geometry_tab,
)
from tabs.documentation_tab import (
    build_documentation_content,
    build_documentation_drawer,
    setup_documentation_tab,
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
from tabs.settings_tab import (
    build_settings_content,
    build_settings_drawer,
    setup_settings_tab,
)
from tabs.visualizer_tab import (
    build_visualizer_content,
    build_visualizer_drawer,
    setup_visualizer_tab,
)

server = get_server(client_type="vue2")
assert server is not None
server.cli.add_argument("--data", help="Optional dataset to load at startup")
server.serve["static"] = "static"
state, ctrl = server.state, server.controller
startup_security_preferences = load_security_preferences()
apply_trame_security(server, startup_security_preferences)

# Set browser page title and favicon
state.trame__title = "FOAMTrame"
state.trame__favicon = "/static/icons/logo.svg"

# Setup tab modules
setup_setup_tab(server)
setup_geometry_tab(server)
setup_meshing_tab(server)
setup_run_log_tab(server)
setup_plots_tab(server)
load_dataset = setup_visualizer_tab(server)
setup_settings_tab(server)
setup_documentation_tab(server)

state.setdefault("active_tab", 0)

with SinglePageWithDrawerLayout(server) as layout:
    layout.title.set_text("")
    with layout.title:
        with html.Div(classes="d-flex align-center"):
            html.Img(
                src="/static/icons/logo.svg",
                alt="App Logo",
                height="34",
                classes="mr-2",
                style="object-fit: contain;",
            )
            html.H1("FOAMTrame", classes="foamtrame-brand")
    layout.title.style = "min-width: 206px; overflow: visible;"
    layout.icon.hide()

    # Inject CSS style sheet into the HTML head using client.Style
    client.Style("""
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
        
        .foamtrame-brand {
            font-size: 1.5rem !important;
            font-weight: 700 !important; /* font-bold */
            color: #000000 !important; /* text-black */
            margin: 0 !important;
            padding: 0 !important;
            line-height: 1.2 !important;
        }

        .v-application {
            --foam-control-radius: 12px;
            --foam-surface-radius: 16px;
            font-family: 'Inter', sans-serif !important;
        }
        .theme--light.v-application {
            background: linear-gradient(180deg, hsla(192, 100%, 86%, 1) 0%, hsla(292, 37%, 88%, 1) 100%) !important;
        }
        .v-application--wrap {
            background: transparent !important;
        }
        /* Core Design System Tokens & Global Consistency */
        .v-application .v-sheet,
        .v-application .v-card,
        .v-application .v-alert,
        .v-application .v-expansion-panels,
        .v-application .v-expansion-panel,
        .v-application .v-menu__content,
        .v-application .v-dialog {
            border-radius: var(--foam-surface-radius) !important;
        }
        /* Consistent Rounded Corners for Form Inputs, Buttons, Chips, and Tabs */
        .v-application .v-input input,
        .v-application .v-input .v-input__control,
        .v-application .v-input .v-input__slot,
        .v-application .v-select__slot,
        .v-application .v-text-field--outlined fieldset,
        .v-application .v-file-input .v-input__slot,
        .v-application .v-btn,
        .v-application .v-chip,
        .v-application .v-btn-toggle {
            border-radius: var(--foam-control-radius) !important;
        }
        /* Keep binary and single-choice controls responsive across the app. */
        .v-application .v-input--selection-controls__input,
        .v-application .v-input--selection-controls__input .v-icon,
        .v-application .v-input--selection-controls__ripple,
        .v-application .v-input--switch__thumb,
        .v-application .v-input--switch__track {
            transition-duration: 120ms !important;
            transition-timing-function: cubic-bezier(0.2, 0.8, 0.2, 1) !important;
        }
        .v-application .v-input--selection-controls__ripple .v-ripple__animation {
            animation-duration: 120ms !important;
            transition-duration: 120ms !important;
        }
        @media (prefers-reduced-motion: reduce) {
            .v-application .v-input--selection-controls__input,
            .v-application .v-input--selection-controls__input .v-icon,
            .v-application .v-input--selection-controls__ripple,
            .v-application .v-input--selection-controls__ripple .v-ripple__animation,
            .v-application .v-input--switch__thumb,
            .v-application .v-input--switch__track {
                animation-duration: 1ms !important;
                transition-duration: 1ms !important;
            }
        }
        /* High-end Glassmorphism Cards */
        .v-application .glass-card {
            background: rgba(255, 255, 255, 0.55) !important;
            backdrop-filter: blur(24px) !important;
            -webkit-backdrop-filter: blur(24px) !important;
            border: 1px solid rgba(255, 255, 255, 0.7) !important;
            border-radius: var(--foam-surface-radius) !important;
            box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.05), inset 0 0 16px rgba(255, 255, 255, 0.3) !important;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        }
        .v-application .glass-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 16px 48px 0 rgba(31, 38, 135, 0.08), inset 0 0 24px rgba(255, 255, 255, 0.4) !important;
            border-color: rgba(255, 255, 255, 0.9) !important;
        }
        /* Setup screen: let the cards comfortably fill the available viewport. */
        .v-application .setup-page {
            min-height: calc(100vh - 48px);
        }
        .v-application .setup-page-row {
            width: 100%;
            min-height: 100%;
            margin: 0;
        }
        .v-application .setup-card-stack {
            display: flex;
            flex-direction: column;
            gap: clamp(12px, 1.8vh, 22px);
            width: 100%;
            max-width: 1040px;
            min-height: calc(100vh - 96px);
            padding-top: 0;
            padding-bottom: 0;
        }
        .v-application .setup-glass-shell {
            position: relative;
            isolation: isolate;
            display: flex;
            flex: 1 1 auto;
            flex-direction: column;
            gap: clamp(14px, 1.8vh, 22px);
            min-height: auto;
            padding: clamp(18px, 2.2vh, 28px);
            overflow: hidden;
            background: linear-gradient(
                145deg,
                rgba(255, 255, 255, 0.28) 0%,
                rgba(255, 255, 255, 0.11) 52%,
                rgba(224, 242, 254, 0.16) 100%
            );
            border: 1px solid rgba(255, 255, 255, 0.78);
            border-radius: 22px;
            box-shadow:
                0 18px 55px rgba(14, 116, 144, 0.10),
                0 4px 18px rgba(71, 85, 105, 0.06),
                inset 0 1px 0 rgba(255, 255, 255, 0.92),
                inset 0 0 32px rgba(255, 255, 255, 0.22);
            backdrop-filter: blur(18px) saturate(135%);
            -webkit-backdrop-filter: blur(18px) saturate(135%);
        }
        .v-application .setup-glass-shell::before {
            content: "";
            position: absolute;
            z-index: -1;
            inset: 0;
            pointer-events: none;
            background:
                radial-gradient(circle at 12% 0%, rgba(255, 255, 255, 0.62), transparent 34%),
                linear-gradient(125deg, rgba(255, 255, 255, 0.32), transparent 38%);
        }
        .v-application .setup-glass-shell::after {
            content: "";
            position: absolute;
            z-index: -1;
            right: -15%;
            bottom: -45%;
            width: 65%;
            aspect-ratio: 1;
            border-radius: 50%;
            pointer-events: none;
            background: rgba(125, 211, 252, 0.12);
            filter: blur(35px);
        }
        .v-application .setup-glass-shell > .setup-main-card {
            z-index: 1;
            background: rgba(255, 255, 255, 0.50) !important;
            border: 1px solid rgba(255, 255, 255, 0.76) !important;
            box-shadow:
                0 10px 28px rgba(30, 64, 175, 0.07),
                0 2px 8px rgba(15, 23, 42, 0.04),
                inset 0 1px 0 rgba(255, 255, 255, 0.90) !important;
            backdrop-filter: blur(28px) saturate(125%) !important;
            -webkit-backdrop-filter: blur(28px) saturate(125%) !important;
        }
        .v-application .setup-main-card {
            display: flex;
            flex-direction: column;
            justify-content: center;
            padding: clamp(24px, 3vh, 40px) !important;
        }
        .v-application .setup-main-card .v-card__title,
        .v-application .setup-main-card .v-card__text {
            width: 100%;
        }
        .v-application .setup-main-card .v-card__title {
            padding-bottom: clamp(12px, 1.8vh, 22px);
        }
        .v-application .setup-card-heading {
            color: #0f172a;
            font-size: clamp(1.45rem, 1.1rem + 0.65vw, 1.85rem) !important;
            font-weight: 800 !important;
            line-height: 1.2 !important;
            letter-spacing: -0.025em;
            margin: 0;
        }
        .v-application .setup-main-card .v-card__text,
        .v-application .setup-main-card .text-caption {
            font-size: clamp(1.05rem, 0.86rem + 0.34vw, 1.22rem) !important;
            line-height: 1.55 !important;
        }
        .v-application .setup-main-card .v-card__text > p {
            margin-bottom: clamp(18px, 2.2vh, 28px);
        }
        .v-application .setup-section-copy {
            color: #0c6e87 !important;
            line-height: 1.5;
            margin: 0;
        }
        .v-application .setup-main-card .v-label,
        .v-application .setup-main-card input,
        .v-application .setup-main-card .v-select__selection,
        .v-application .setup-main-card .v-btn,
        .v-application .setup-main-card .v-tab {
            font-size: clamp(1.05rem, 0.9rem + 0.28vw, 1.2rem) !important;
        }
        .v-application .setup-main-card .v-input__slot {
            min-height: 56px !important;
        }
        .v-application .setup-name-field input,
        .v-application .setup-tutorial-field input,
        .v-application .setup-tutorial-field .v-select__selection {
            align-self: center !important;
            max-height: none !important;
            padding-top: 0 !important;
            padding-bottom: 0 !important;
        }
        .v-application .setup-main-card .v-btn {
            min-height: 56px !important;
            height: 56px !important;
        }
        .v-application .setup-creation-card .v-tabs,
        .v-application .setup-creation-card .v-tabs-bar {
            height: 56px !important;
        }
        .v-application .setup-creation-card .v-tabs-items {
            margin-top: clamp(14px, 1.8vh, 22px);
        }
        .v-application .setup-tab-form {
            display: flex;
            flex-direction: column;
            gap: clamp(14px, 1.8vh, 20px);
            width: 100%;
            /* Outlined labels rise above their input and would otherwise be
               clipped by the v-window used for tab content. */
            padding-top: 8px !important;
        }
        .v-application .setup-tab-form .v-input {
            width: 100%;
            margin: 0 !important;
            padding: 0 !important;
        }
        .v-application .setup-control-row {
            margin-top: 0;
            margin-bottom: 0;
        }
        .v-application .setup-advanced-card .v-expansion-panel-header {
            min-height: 64px;
            font-size: clamp(1rem, 0.86rem + 0.25vw, 1.15rem) !important;
            line-height: 1.35;
            transition: none !important;
        }
        .v-application .setup-advanced-card {
            transition: none !important;
        }
        .v-application .setup-advanced-card:hover {
            transform: none;
        }
        .v-application .setup-advanced-card .expand-transition-enter-active,
        .v-application .setup-advanced-card .expand-transition-leave-active,
        .v-application .setup-advanced-card .v-expansion-panel-content {
            transition: none !important;
        }
        .v-application .setup-advanced-card .v-expansion-panel-header__icon {
            transition: none !important;
        }
        .v-application .setup-footer-card {
            padding: 14px 20px !important;
            overflow: hidden;
        }
        .v-application .setup-footer-layout {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            align-items: center;
            column-gap: 18px;
            row-gap: 10px;
            width: 100%;
        }
        .v-application .setup-footer-identity {
            min-width: 0;
            text-align: left;
        }
        .v-application .setup-footer-title {
            color: #0f172a;
            font-size: 0.96rem;
            font-weight: 700;
            line-height: 1.3;
        }
        .v-application .setup-footer-license,
        .v-application .setup-footer-label {
            color: #64748b;
            font-size: 0.76rem;
            font-weight: 500;
            line-height: 1.35;
        }
        .v-application .setup-footer-license {
            margin-top: 2px;
        }
        .v-application .setup-footer-powered {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 10px;
            grid-column: 1 / -1;
            grid-row: 2;
            padding-top: 9px;
            border-top: 1px solid rgba(100, 116, 139, 0.14);
            white-space: nowrap;
        }
        .v-application .setup-footer-docker-logo {
            width: auto;
            height: 25px;
            object-fit: contain;
        }
        .v-application .setup-footer-trame-logo {
            width: auto;
            height: 20px;
            object-fit: contain;
        }
        /* High-contrast success notices that still fit the cyan/teal palette. */
        .v-application .setup-status-alert.v-alert--outlined.success--text {
            background: rgba(209, 250, 229, 0.88) !important;
            border-color: #10b981 !important;
            color: #065f46 !important;
            box-shadow: 0 4px 14px rgba(5, 150, 105, 0.10) !important;
        }
        .v-application .setup-status-alert.v-alert--outlined.success--text .v-alert__icon,
        .v-application .setup-status-alert.v-alert--outlined.success--text .v-alert__content {
            color: #065f46 !important;
        }
        .v-application .setup-status-alert .v-alert__content {
            font-weight: 600;
            min-width: 0;
            max-width: 100%;
            overflow-wrap: anywhere;
            word-break: break-word;
            white-space: normal;
        }
        /* Readable tinted notifications for plot synchronization states. */
        .v-application .plots-status-alert {
            border: 1px solid currentColor !important;
            box-shadow: 0 4px 16px rgba(15, 23, 42, 0.06) !important;
        }
        .v-application .plots-status-alert.v-alert--text::before {
            opacity: 0 !important;
        }
        .v-application .plots-status-alert.info--text {
            background: rgba(224, 242, 254, 0.92) !important;
            border-color: #38bdf8 !important;
            color: #0369a1 !important;
        }
        .v-application .plots-status-alert.success--text {
            background: rgba(209, 250, 229, 0.92) !important;
            border-color: #34d399 !important;
            color: #065f46 !important;
        }
        .v-application .plots-status-alert.warning--text {
            background: rgba(254, 243, 199, 0.94) !important;
            border-color: #f59e0b !important;
            color: #92400e !important;
        }
        .v-application .plots-status-alert.error--text {
            background: rgba(254, 226, 226, 0.94) !important;
            border-color: #f87171 !important;
            color: #991b1b !important;
        }
        .v-application .plots-status-alert .v-alert__icon,
        .v-application .plots-status-alert .v-alert__content {
            color: inherit !important;
        }
        .v-application .plots-status-alert .v-alert__content {
            font-weight: 600;
        }
        .v-application .plot-card {
            overflow: hidden;
        }
        .v-application .plot-rendered-image,
        .v-application .plots-maximized-image {
            background: transparent !important;
        }
        .v-application .plots-maximized-dialog {
            background:
                radial-gradient(circle at 78% 10%, rgba(6, 182, 212, 0.18), transparent 34%),
                linear-gradient(180deg, #d8f5fb 0%, #eee2f1 100%) !important;
        }
        .v-application .plots-maximized-body {
            height: calc(100vh - 48px);
            overflow: auto;
        }
        .v-application .plots-maximized-sidebar {
            background: rgba(255, 255, 255, 0.48);
            border: 1px solid rgba(255, 255, 255, 0.72);
            border-radius: 16px;
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            min-width: 0;
            overflow: hidden;
        }
        .v-application .plots-maximized-sidebar .v-btn {
            width: 100% !important;
            max-width: 100% !important;
            min-width: 0 !important;
            min-height: 40px;
            height: auto !important;
            padding: 8px 12px !important;
        }
        .v-application .plots-maximized-sidebar .v-btn__content {
            display: block;
            width: 100%;
            max-width: 100%;
            white-space: normal !important;
            overflow-wrap: anywhere;
            word-break: normal;
            line-height: 1.25;
            text-align: left;
        }
        .v-application .plots-maximized-image .v-image__image {
            image-rendering: auto;
        }
        @media (max-width: 959px) {
            .v-application .plots-maximized-body {
                height: auto;
                min-height: calc(100vh - 48px);
            }
            .v-application .plots-maximized-sidebar {
                margin-bottom: 12px;
            }
            .v-application .plots-maximized-sidebar .v-btn {
                min-height: 38px;
            }
        }
        .v-application .setup-case-card {
            flex: 1 0 295px;
            min-height: 295px;
            transform-origin: center;
            transition:
                opacity 260ms ease,
                filter 260ms ease,
                transform 260ms ease,
                box-shadow 300ms ease,
                border-color 300ms ease !important;
        }
        .v-application .setup-case-card:has(.setup-empty-state) {
            background: rgba(226, 232, 240, 0.58) !important;
            border-color: rgba(100, 116, 139, 0.38) !important;
            box-shadow:
                0 8px 30px rgba(71, 85, 105, 0.08),
                inset 0 0 28px rgba(255, 255, 255, 0.38) !important;
        }
        .v-application .setup-case-card:has(.setup-empty-state) .setup-card-heading {
            color: #475569;
        }
        .v-application .setup-empty-state {
            padding: clamp(14px, 1.8vh, 20px);
            margin-bottom: clamp(14px, 1.8vh, 22px);
            color: #334155;
            background: rgba(248, 250, 252, 0.72);
            border: 1px solid rgba(148, 163, 184, 0.45);
            border-radius: 14px;
            backdrop-filter: blur(12px);
            -webkit-backdrop-filter: blur(12px);
        }
        .v-application .setup-empty-state-icon {
            color: #64748b !important;
            font-size: 2rem !important;
        }
        .v-application .setup-empty-state-title {
            color: #334155;
            font-size: clamp(1rem, 0.9rem + 0.2vw, 1.12rem);
            font-weight: 700;
            line-height: 1.3;
        }
        .v-application .setup-empty-state-copy {
            color: #64748b;
            font-size: clamp(0.9rem, 0.82rem + 0.14vw, 1rem);
            line-height: 1.45;
            margin-top: 3px;
        }
        .v-application .setup-case-card .v-input--is-disabled .v-input__slot {
            background: rgba(226, 232, 240, 0.72) !important;
            border-color: rgba(100, 116, 139, 0.3) !important;
            cursor: not-allowed !important;
        }
        .v-application .setup-case-card .v-input--is-disabled .v-label,
        .v-application .setup-case-card .v-input--is-disabled input,
        .v-application .setup-case-card .v-input--is-disabled .v-select__selection,
        .v-application .setup-case-card .v-input--is-disabled .v-icon {
            color: #64748b !important;
            opacity: 0.82 !important;
        }
        .v-application .setup-creation-card {
            flex: 0 0 auto;
            min-height: 280px;
            justify-content: flex-start;
        }
        .v-application .setup-advanced-card,
        .v-application .setup-footer-card {
            flex: 0 0 auto;
        }
        .v-application .footer-openfoam-version {
            grid-column: 2;
            grid-row: 1;
            justify-self: end;
            gap: 7px;
            min-height: 30px;
            padding: 4px 10px;
            color: #0c6e87;
            background: rgba(207, 250, 254, 0.68);
            border: 1px solid rgba(6, 154, 181, 0.34);
            border-radius: 999px;
            white-space: nowrap;
        }
        .v-application .footer-openfoam-logo {
            display: block;
            flex: 0 0 auto;
            width: auto;
            height: 22px;
            max-width: 62px;
            object-fit: contain;
        }
        .v-application .setup-footer-version-text {
            font-size: 0.78rem;
            font-weight: 700;
            line-height: 1.2;
        }
        @media (max-width: 900px) {
            .v-application .setup-footer-layout {
                grid-template-columns: 1fr;
                justify-items: center;
                gap: 11px;
            }
            .v-application .setup-footer-identity {
                grid-column: 1;
                grid-row: 1;
                text-align: center;
            }
            .v-application .footer-openfoam-version {
                grid-column: 1;
                grid-row: 2;
                justify-self: center;
            }
            .v-application .setup-footer-powered {
                grid-column: 1;
                grid-row: 3;
                width: 100%;
            }
        }
        .v-application .run-log-drawer {
            max-height: calc(100vh - 48px);
            overflow-y: auto;
            scrollbar-width: thin;
            scrollbar-color: rgba(71, 85, 105, 0.5) transparent;
        }
        .v-application .run-log-drawer::-webkit-scrollbar,
        .v-application .case-workflow-list::-webkit-scrollbar {
            width: 8px;
        }
        .v-application .run-log-drawer::-webkit-scrollbar-track,
        .v-application .case-workflow-list::-webkit-scrollbar-track {
            background: transparent;
        }
        .v-application .case-workflow-list::-webkit-scrollbar-track {
            margin-block: 7px;
        }
        .v-application .run-log-drawer::-webkit-scrollbar-thumb,
        .v-application .case-workflow-list::-webkit-scrollbar-thumb {
            min-height: 30px;
            background: rgba(71, 85, 105, 0.5);
            background-clip: padding-box;
            border: 2px solid transparent;
            border-radius: 999px;
        }
        .v-application .run-log-drawer::-webkit-scrollbar-thumb:hover,
        .v-application .case-workflow-list::-webkit-scrollbar-thumb:hover {
            background: rgba(51, 65, 85, 0.68);
            background-clip: padding-box;
        }
        .v-application .capability-summary {
            display: flex;
            align-items: center;
            padding: 8px 10px;
            color: #0c6e87;
            background: rgba(207, 250, 254, 0.62);
            border: 1px solid rgba(6, 154, 181, 0.28);
            border-radius: 10px;
            font-size: 0.78rem;
            line-height: 1.3;
        }
        .v-application .capability-summary__content {
            display: flex;
            flex-wrap: wrap;
            align-items: baseline;
            column-gap: 8px;
            row-gap: 3px;
            min-width: 0;
            line-height: 1.35;
        }
        .v-application .capability-summary__count {
            font-weight: 500;
        }
        .v-application .capability-summary__solver {
            display: inline-flex;
            align-items: baseline;
            gap: 4px;
            white-space: nowrap;
        }
        .v-application .capability-summary__dot {
            color: #069ab5;
            font-size: 1rem;
            line-height: 0;
            margin-right: 1px;
        }
        .v-application .capability-summary__solver strong {
            color: #075f75;
            font-weight: 700;
        }
        .v-application .case-workflow-list {
            max-height: 250px;
            overflow-y: auto;
            scrollbar-width: thin;
            scrollbar-color: rgba(71, 85, 105, 0.5) transparent;
            background: rgba(255, 255, 255, 0.45) !important;
            border: 1px solid rgba(255, 255, 255, 0.72);
            border-radius: 12px;
        }
        .v-application .case-workflow-item + .case-workflow-item {
            border-top: 1px solid rgba(100, 116, 139, 0.12);
        }
        .v-application .case-workflow-item {
            min-height: 56px;
            height: auto !important;
            align-items: flex-start;
        }
        .v-application .case-workflow-item .v-list-item__icon {
            align-self: flex-start;
        }
        .v-application .case-workflow-item .v-list-item__title,
        .v-application .case-action-reason {
            display: block;
            max-width: 100%;
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
            overflow-wrap: anywhere;
            -webkit-line-clamp: unset !important;
        }
        .v-application .case-workflow-item .v-list-item__title {
            line-height: 1.25;
            margin-bottom: 2px;
        }
        .v-application .case-action-reason {
            line-height: 1.28;
            font-size: 0.69rem;
        }
        .v-application .clean-preview-list,
        .v-application .guided-run-list {
            max-height: 300px;
            overflow-y: auto;
            background: rgba(255, 255, 255, 0.52) !important;
            border-radius: 12px;
        }
        .v-application .run-log-drawer .v-btn.v-btn--disabled {
            color: #64748b !important;
            background: rgba(226, 232, 240, 0.72) !important;
            border-color: rgba(100, 116, 139, 0.3) !important;
            box-shadow: none !important;
            opacity: 0.78;
        }
        .v-application .run-log-drawer .v-btn.v-btn--disabled .v-btn__content {
            color: #64748b !important;
        }

        @media (max-height: 820px), (max-width: 959px) {
            .v-application .setup-page {
                min-height: auto;
            }
            .v-application .setup-card-stack {
                min-height: auto;
            }
            .v-application .setup-main-card {
                flex: none;
                min-height: auto !important;
            }
        }

        /* The permanent drawer reduces the real content width on tablets and
           small laptops, so switch controls to their compact layout early. */
        @media (max-width: 1100px) {
            .v-application .setup-main-card {
                padding: 24px !important;
            }
            .v-application .setup-case-card .row > .col-8,
            .v-application .setup-case-card .row > .col-4 {
                flex: 0 0 100%;
                max-width: 100%;
            }
            .v-application .setup-case-card .row > .col-4 {
                padding-top: 4px;
            }
            .v-application .setup-creation-card .v-tabs-bar__content {
                gap: 8px;
            }
            .v-application .setup-creation-card .v-tab {
                min-width: 0 !important;
                margin: 4px 0 !important;
                padding: 0 10px !important;
                white-space: normal !important;
                line-height: 1.15 !important;
            }
        }

        @media (max-width: 600px) {
            .v-application .setup-page {
                padding: 12px !important;
            }
            .v-application .setup-card-stack {
                gap: 12px;
                padding-left: 0;
                padding-right: 0;
            }
            .v-application .setup-glass-shell {
                gap: 12px;
                padding: 10px;
                border-radius: 18px;
            }
            .v-application .setup-main-card {
                padding: 16px !important;
            }
            .v-application .setup-card-heading {
                font-size: 1.35rem !important;
                padding-left: 0;
                padding-right: 0;
            }
            .v-application .setup-main-card .v-card__text {
                padding-left: 0;
                padding-right: 0;
            }
            .v-application .setup-main-card .v-card__text,
            .v-application .setup-main-card .text-caption,
            .v-application .setup-main-card .v-label,
            .v-application .setup-main-card input,
            .v-application .setup-main-card .v-select__selection,
            .v-application .setup-main-card .v-btn,
            .v-application .setup-main-card .v-tab {
                font-size: 1rem !important;
            }
        }
        /* Advanced Expansion Panel Glass fix */
        .v-application .v-expansion-panels.glass-card,
        .v-application .v-expansion-panel {
            background: rgba(255, 255, 255, 0.55) !important;
            border-radius: 16px !important;
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
            height: 48px !important;
            min-height: 48px !important;
        }
        .v-application .glass-navbar .v-toolbar__content {
            height: 48px !important;
            min-height: 48px !important;
            width: 100% !important;
            max-width: 1520px !important;
            margin: 0 auto !important;
            padding: 0 18px !important;
        }
        /* Navbar Project Title Visibility */
        .v-application .glass-navbar .v-toolbar__title {
            overflow: visible !important;
            white-space: nowrap !important;
            text-overflow: clip !important;
            flex: none !important;
            margin-right: 14px !important;
        }
        /* Compact active-case badge next to the project title. */
        .v-application .active-case-chip {
            max-width: 190px;
            height: 24px !important;
            overflow: hidden !important;
            white-space: nowrap !important;
            flex: none !important;
            flex-shrink: 0 !important;
            margin-right: 14px !important;
            padding: 0 10px !important;
            border: 1px solid rgba(6, 154, 181, 0.14);
            font-size: 0.78rem !important;
        }
        .v-application .active-case-chip .v-chip__content {
            display: block !important;
            min-width: 0;
            overflow: hidden !important;
            text-overflow: ellipsis;
            white-space: nowrap !important;
        }
        /* Compact natural-width navigation with a moving pill. */
        .glass-navbar .v-tabs {
            height: 38px !important;
            align-self: center !important;
            min-width: 0 !important;
            overflow: hidden !important;
        }
        .glass-navbar .compact-navbar-tabs {
            flex: 1 1 auto !important;
            width: auto !important;
            max-width: none !important;
            margin-left: 0 !important;
        }
        .glass-navbar .v-tabs-bar {
            height: 38px !important;
            background-color: transparent !important;
        }
        .glass-navbar .v-tabs-bar__content {
            width: 100% !important;
            height: 38px !important;
            align-items: center !important;
            justify-content: space-between !important;
            position: relative !important;
            isolation: isolate;
        }
        .glass-navbar .v-tab {
            text-transform: none !important;
            font-weight: 700 !important;
            letter-spacing: normal !important;
            font-size: 0.95rem !important;
            border-radius: 9px !important;
            margin: 0 2px !important;
            min-width: auto !important;
            max-width: none !important;
            width: auto !important;
            flex: 0 0 auto !important;
            padding: 0 18px !important;
            justify-content: center !important;
            text-align: center !important;
            height: 38px !important;
            color: #334155 !important; /* slate-700 */
            transition: none !important;
            align-self: center !important;
            position: relative;
            z-index: 1;
        }
        .glass-navbar .v-tab:hover:not(.v-tab--active) {
            background: transparent !important;
            color: #0c6e87 !important;
        }
        .glass-navbar .v-tab::before,
        .glass-navbar .v-tab:hover::before,
        .glass-navbar .v-tab:focus::before {
            background: transparent !important;
            opacity: 0 !important;
        }
        .glass-navbar .v-tab--active {
            color: white !important;
            background: transparent !important;
            box-shadow: none !important;
        }
        .glass-navbar .v-tabs-slider-wrapper {
            display: block !important;
            z-index: 0 !important;
            height: 38px !important;
            bottom: 0 !important;
            border-radius: 9px !important;
            overflow: visible !important;
            transition: none !important;
        }
        .glass-navbar .v-tabs-slider {
            width: 100% !important;
            height: 100% !important;
            border-radius: 9px !important;
            background: linear-gradient(135deg, #069ab5 0%, #0c6e87 100%) !important;
            box-shadow:
                0 4px 12px rgba(6, 154, 181, 0.30),
                inset 0 1px 0 rgba(255, 255, 255, 0.24) !important;
        }
        @media (max-width: 1300px) {
            .v-application .active-case-chip {
                max-width: 140px;
            }
            .glass-navbar .v-tab {
                padding-right: 13px !important;
                padding-left: 13px !important;
                font-size: 0.88rem !important;
            }
        }
        @media (max-width: 1100px) {
            .v-application .active-case-chip {
                display: none !important;
            }
            .v-application .glass-navbar .v-toolbar__title {
                min-width: 190px !important;
                margin-right: 10px !important;
            }
        }
        @media (max-width: 900px) {
            .v-application .glass-navbar .v-toolbar__content {
                padding-right: 10px !important;
                padding-left: 10px !important;
            }
            .glass-navbar .v-tabs {
                margin-left: 0 !important;
            }
            /* At narrower widths Vuetify's arrows keep every tab reachable. */
            .glass-navbar .v-tabs-bar__content {
                justify-content: flex-start !important;
            }
            .glass-navbar .v-tab {
                padding-right: 12px !important;
                padding-left: 12px !important;
            }
        }
        @media (max-width: 700px) {
            .v-application .glass-navbar .v-toolbar__content {
                padding-right: 6px !important;
                padding-left: 6px !important;
            }
            .v-application .glass-navbar .v-toolbar__title {
                min-width: 44px !important;
                max-width: 44px !important;
                margin-right: 6px !important;
            }
            .v-application .glass-navbar .v-toolbar__title img {
                height: 30px !important;
                margin-right: 0 !important;
            }
            .foamtrame-brand {
                display: none !important;
            }
            .glass-navbar .v-tab {
                padding-right: 11px !important;
                padding-left: 11px !important;
                font-size: 0.82rem !important;
            }
        }
        @media (max-width: 420px) {
            .v-application .glass-navbar .v-toolbar__title {
                min-width: 38px !important;
                max-width: 38px !important;
                margin-right: 2px !important;
            }
            .v-application .glass-navbar .v-toolbar__title img {
                height: 27px !important;
            }
            .glass-navbar .v-tab {
                padding-right: 10px !important;
                padding-left: 10px !important;
            }
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
            color: #0c6e87 !important;
        }
        .v-application .glass-card .v-tab--active {
            color: white !important;
            background: linear-gradient(135deg, #069ab5 0%, #0c6e87 100%) !important;
            box-shadow: 0 4px 12px rgba(6, 154, 181, 0.24) !important;
        }
        .v-application .glass-card .v-tabs-slider-wrapper {
            display: none !important;
        }
        /* Setup mode selector: compact, evenly inset segmented control. */
        .v-application .setup-glass-shell .setup-creation-card .v-tabs,
        .v-application .setup-glass-shell .setup-creation-card .v-tabs-bar {
            height: 56px !important;
        }
        .v-application .setup-case-tabs .v-tabs-bar {
            box-sizing: border-box;
            padding: 4px;
            overflow: hidden;
            background: rgba(226, 232, 240, 0.58) !important;
            border: 1px solid rgba(255, 255, 255, 0.72);
            border-radius: var(--foam-control-radius) !important;
            box-shadow:
                inset 0 1px 2px rgba(15, 23, 42, 0.08),
                0 8px 24px rgba(14, 116, 144, 0.08);
            backdrop-filter: blur(14px) saturate(130%);
            -webkit-backdrop-filter: blur(14px) saturate(130%);
        }
        .v-application .setup-case-tabs .v-tabs-bar__content {
            gap: 4px !important;
            height: 100% !important;
        }
        .v-application .setup-case-tabs .v-tab {
            flex: 1 1 0 !important;
            min-width: 0 !important;
            height: 100% !important;
            margin: 0 !important;
            isolation: isolate;
            overflow: hidden;
            color: #475569 !important;
            background: transparent !important;
            border-radius: calc(var(--foam-control-radius) - 4px) !important;
            box-shadow: none !important;
            transition:
                color 240ms cubic-bezier(0.4, 0, 0.2, 1),
                background-color 200ms ease !important;
        }
        .v-application .setup-case-tabs .v-tab::after {
            content: "";
            position: absolute;
            z-index: -1;
            inset: 0;
            pointer-events: none;
            opacity: 0;
            border: 1px solid rgba(255, 255, 255, 0.38);
            border-radius: inherit;
            background: linear-gradient(135deg, #0aa6c0 0%, #087f99 52%, #0c6e87 100%);
            box-shadow:
                0 5px 14px rgba(6, 154, 181, 0.26),
                inset 0 1px 0 rgba(255, 255, 255, 0.28);
            transform: scale(0.975);
            transition:
                opacity 240ms cubic-bezier(0.4, 0, 0.2, 1),
                transform 280ms cubic-bezier(0.22, 1, 0.36, 1);
        }
        .v-application .setup-case-tabs .v-tab--active {
            color: #ffffff !important;
            background: transparent !important;
            text-shadow: 0 1px 1px rgba(15, 23, 42, 0.16);
        }
        .v-application .setup-case-tabs .v-tab--active::after {
            opacity: 1;
            transform: scale(1);
        }
        .v-application .setup-case-tabs .v-tab:hover:not(.v-tab--active) {
            color: #0c6e87 !important;
            background: rgba(255, 255, 255, 0.34) !important;
        }
        .v-application .setup-case-tabs .v-tab:focus-visible {
            outline: 2px solid rgba(6, 154, 181, 0.62);
            outline-offset: -3px;
        }
        .v-application .setup-case-tabs .v-tabs-slider-wrapper {
            display: none !important;
        }
        @media (prefers-reduced-motion: reduce) {
            .v-application .setup-case-tabs .v-tab,
            .v-application .setup-case-tabs .v-tab::after {
                transition-duration: 1ms !important;
            }
        }
        @media (max-width: 1100px) {
            .v-application .setup-glass-shell .setup-creation-card .v-tab {
                min-width: 0 !important;
                margin: 0 !important;
                padding: 0 10px !important;
                white-space: normal !important;
                line-height: 1.15 !important;
            }
        }
        .v-application .tutorial-source-label {
            color: #334155;
            font-size: clamp(1rem, 0.9rem + 0.2vw, 1.15rem);
            font-weight: 600;
            line-height: 1.4;
        }
        .v-application .tutorial-picker-row {
            width: 100%;
            margin: 0 !important;
        }
        .v-application .tutorial-list-column {
            display: flex;
            min-width: 0;
            padding: 0 6px 0 0;
        }
        .v-application .tutorial-action-column {
            display: flex;
            min-width: 0;
            padding: 0 0 0 6px;
        }
        .v-application .tutorial-list {
            position: relative;
            width: 100%;
            height: 174px;
            overflow-y: auto;
            background: rgba(255, 255, 255, 0.72) !important;
            border: 1px solid rgba(100, 116, 139, 0.34);
            border-radius: 12px !important;
            box-shadow: inset 0 1px 3px rgba(15, 23, 42, 0.04);
        }
        .v-application .tutorial-list-item {
            min-height: 34px !important;
            padding: 0 16px !important;
            border-left: 3px solid transparent;
        }
        .v-application .tutorial-list-item:hover {
            background: rgba(6, 154, 181, 0.08) !important;
        }
        .v-application .tutorial-list-item.v-item--active {
            color: #0c6e87 !important;
            background: rgba(6, 154, 181, 0.14) !important;
            border-left-color: #069ab5;
            font-weight: 700;
        }
        .v-application .tutorial-list-message {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
            color: #64748b;
            background: rgba(248, 250, 252, 0.82);
            text-align: center;
        }
        .v-application .setup-glass-shell .tutorial-import-button {
            height: 100% !important;
            min-height: 174px !important;
            white-space: normal;
        }
        @media (max-width: 959px) {
            .v-application .tutorial-list-column,
            .v-application .tutorial-action-column {
                padding-left: 0;
                padding-right: 0;
            }
            .v-application .tutorial-action-column {
                padding-top: 12px;
            }
            .v-application .setup-glass-shell .tutorial-import-button {
                min-height: 64px !important;
            }
        }
        /* Hide Default Footer */
        .v-footer {
            display: none !important;
        }
        /* Premium Button Accents with Consistent Border Radius & Elevation */
        .v-application .v-btn.theme-btn-primary {
            background: linear-gradient(135deg, #069ab5 0%, #0c6e87 100%) !important;
            color: white !important;
            text-transform: none !important;
            font-weight: 600 !important;
            border-radius: 12px !important;
            box-shadow: 0 4px 14px 0 rgba(6, 154, 181, 0.30) !important;
        }
        .v-application .v-btn.theme-btn-success {
            background: linear-gradient(135deg, #10b981 0%, #059669 100%) !important;
            color: white !important;
            text-transform: none !important;
            font-weight: 600 !important;
            border-radius: 12px !important;
            box-shadow: 0 4px 14px 0 rgba(16, 185, 129, 0.3) !important;
        }
        .v-application .v-btn.theme-btn-warning {
            background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%) !important;
            color: white !important;
            text-transform: none !important;
            font-weight: 600 !important;
            border-radius: 12px !important;
            box-shadow: 0 4px 14px 0 rgba(245, 158, 11, 0.3) !important;
        }
        .v-application .v-btn.theme-btn-info {
            background: linear-gradient(135deg, #06b6d4 0%, #0891b2 100%) !important;
            color: white !important;
            text-transform: none !important;
            font-weight: 600 !important;
            border-radius: 12px !important;
            box-shadow: 0 4px 14px 0 rgba(6, 182, 212, 0.3) !important;
        }
        .v-application .v-btn.theme-btn-error {
            background: linear-gradient(135deg, #ef4444 0%, #dc2626 100%) !important;
            color: white !important;
            text-transform: none !important;
            font-weight: 600 !important;
            border-radius: 12px !important;
            box-shadow: 0 4px 14px 0 rgba(239, 68, 68, 0.4) !important;
        }
        .v-application .v-btn.theme-btn-outlined {
            border-radius: 12px !important;
            text-transform: none !important;
            font-weight: 600 !important;
        }
        /* Settings / portable app-state management */
        .glass-navbar .v-tab.settings-nav-tab {
            min-width: 42px !important;
            max-width: 42px !important;
            width: 42px !important;
            padding: 0 8px !important;
        }
        .glass-navbar .settings-nav-tab .v-icon {
            font-size: 1.2rem;
        }
        .v-application .settings-page {
            min-height: calc(100vh - 48px);
        }
        .v-application .settings-page-row {
            width: 100%;
            margin: 0;
        }
        .v-application .settings-glass-card {
            max-width: 1040px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.34) !important;
            border-color: rgba(255, 255, 255, 0.82) !important;
            backdrop-filter: blur(28px) saturate(130%) !important;
            -webkit-backdrop-filter: blur(28px) saturate(130%) !important;
        }
        .v-application .settings-title {
            color: #0f172a;
            font-size: clamp(1.6rem, 1.2rem + 0.7vw, 2rem);
            font-weight: 800;
            line-height: 1.2;
            margin: 0;
        }
        .v-application .settings-title-icon {
            color: #0c6e87 !important;
            font-size: 2rem !important;
        }
        .v-application .settings-description,
        .v-application .settings-action-description {
            color: #0c6e87;
            font-size: 1rem;
            line-height: 1.55;
            margin-bottom: 0;
        }
        .v-application .settings-action-card {
            background: rgba(255, 255, 255, 0.52) !important;
            border: 1px solid rgba(255, 255, 255, 0.76) !important;
            box-shadow: 0 8px 26px rgba(15, 118, 145, 0.07) !important;
            backdrop-filter: blur(20px) !important;
            -webkit-backdrop-filter: blur(20px) !important;
        }
        .v-application .settings-action-layout {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 24px;
        }
        .v-application .settings-action-copy {
            min-width: 0;
        }
        .v-application .settings-action-title {
            color: #0f172a;
            font-size: 1.3rem;
            font-weight: 700;
            line-height: 1.3;
            margin: 0 0 6px;
        }
        .v-application .settings-action-button,
        .v-application .settings-restore-button,
        .v-application .settings-security-save-button {
            min-height: 52px !important;
            text-transform: none !important;
            white-space: nowrap;
        }
        .v-application .settings-security-card .v-input {
            margin-top: 0;
        }
        .v-application .security-setting-switch .v-label {
            color: #334155;
            font-weight: 600;
            line-height: 1.35;
        }
        .v-application .security-api-key-layout {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            align-items: center;
            gap: 12px;
        }
        .v-application .security-generate-key-button {
            min-height: 48px !important;
            text-transform: none !important;
        }
        .v-application .security-settings-alert {
            border: 1px solid rgba(6, 154, 181, 0.2);
            background: rgba(224, 247, 250, 0.46) !important;
        }
        @media (max-width: 700px) {
            .v-application .settings-page {
                min-height: auto;
                padding: 12px !important;
            }
            .v-application .settings-glass-card {
                padding: 18px !important;
            }
            .v-application .settings-action-layout {
                align-items: stretch;
                flex-direction: column;
                gap: 16px;
            }
            .v-application .settings-action-button {
                width: 100%;
            }
            .v-application .security-api-key-layout {
                grid-template-columns: 1fr;
            }
            .v-application .security-generate-key-button {
                width: 100%;
            }
        }
        /* Premium Scrollbar */
        .v-application .documentation-page {
            max-width: 1180px;
            margin: 0 auto;
        }
        .v-application .documentation-card {
            min-height: calc(100vh - 112px);
        }
        .v-application .documentation-content {
            color: #1e293b;
            font-size: 1rem;
            line-height: 1.75;
            overflow-wrap: anywhere;
        }
        .v-application .documentation-content h1,
        .v-application .documentation-content h2,
        .v-application .documentation-content h3,
        .v-application .documentation-content h4 {
            color: #0c6e87;
            line-height: 1.25;
            margin: 1.6em 0 0.65em;
            scroll-margin-top: 72px;
        }
        .v-application .documentation-content h1:first-child,
        .v-application .documentation-content h2:first-child {
            margin-top: 0;
        }
        .v-application .documentation-content h2 {
            border-bottom: 1px solid rgba(6, 154, 181, 0.22);
            font-size: 1.75rem;
            padding-bottom: 0.4em;
        }
        .v-application .documentation-content h3 { font-size: 1.3rem; }
        .v-application .documentation-content p,
        .v-application .documentation-content ul,
        .v-application .documentation-content ol { margin-bottom: 1em; }
        .v-application .documentation-content a {
            color: #067f99;
            font-weight: 600;
        }
        .v-application .documentation-content pre {
            background: #0f172a;
            border-radius: 12px;
            color: #e2e8f0;
            overflow-x: auto;
            padding: 16px;
        }
        .v-application .documentation-content code {
            background: rgba(6, 154, 181, 0.1);
            border-radius: 5px;
            color: #075d71;
            font-size: 0.9em;
            padding: 0.15em 0.35em;
        }
        .v-application .documentation-content pre code {
            background: transparent;
            color: inherit;
            padding: 0;
        }
        .v-application .documentation-content blockquote {
            border-left: 4px solid #069ab5;
            color: #475569;
            margin: 1em 0;
            padding: 0.65em 1em;
        }
        .v-application .documentation-table-wrap {
            margin: 1em 0;
            overflow-x: auto;
        }
        .v-application .documentation-content table {
            border-collapse: collapse;
            min-width: 100%;
        }
        .v-application .documentation-content th,
        .v-application .documentation-content td {
            border: 1px solid rgba(12, 110, 135, 0.2);
            padding: 10px 12px;
            text-align: left;
            vertical-align: top;
        }
        .v-application .documentation-content th {
            background: rgba(6, 154, 181, 0.09);
            color: #075d71;
        }
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
    layout.toolbar.height = 48
    with layout.toolbar:
        # Active case display chip next to FOAMTrame title
        vuetify.VChip(
            "{{ active_case }}",
            color="cyan lighten-5",
            text_color="cyan darken-3",
            classes="ml-2 font-weight-bold active-case-chip",
            label=True,
            small=True,
            v_if="active_case",
        )
        with vuetify.VTabs(
            v_model=("active_tab", 0),
            dense=True,
            background_color="transparent",
            classes="ml-2 compact-navbar-tabs",
            show_arrows=True,
        ):
            vuetify.VTab("Setup")
            vuetify.VTab("Geometry")
            vuetify.VTab("Meshing")
            vuetify.VTab("Run/Log")
            vuetify.VTab("Plots")
            vuetify.VTab("Post")
            with vuetify.VTab(
                classes="settings-nav-tab",
                title="Documentation",
                aria_label="Documentation",
            ):
                vuetify.VIcon("mdi-book-open-page-variant-outline")
            with vuetify.VTab(
                classes="settings-nav-tab",
                title="Settings",
                aria_label="Settings",
            ):
                vuetify.VIcon("mdi-cog-outline")
    state.setdefault("drawer_open", True)

    @state.change("active_tab")
    def _on_tab_change(active_tab, **_):
        state.drawer_open = True
        ctrl.plots_set_visible(active_tab)

    layout.drawer.classes = "glass-drawer"
    layout.drawer.v_model = ("drawer_open",)
    # Run/Log contains capability explanations and workflow controls that need
    # more horizontal room. Keep the standard drawer on compact viewports so
    # the main content is not unnecessarily crowded.
    layout.drawer.width = (
        "active_tab === 3 && !$vuetify.breakpoint.smAndDown ? 360 : 300",
    )
    with layout.drawer:
        build_setup_drawer()
        build_geometry_drawer()
        build_meshing_drawer()
        build_run_log_drawer()
        build_plots_drawer()
        build_visualizer_drawer(ctrl)
        build_documentation_drawer(ctrl)
        build_settings_drawer()

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
        build_documentation_content()
        build_settings_content()


def main():
    assert server is not None
    install_asyncio_exception_handler()
    args, _ = server.cli.parse_known_args()
    if args.data:
        try:
            load_dataset(args.data)
        except Exception as exc:
            state.error_message = str(exc)
    # Trame initializes args.port to its own default (8080), so checking that
    # value cannot distinguish an explicit --port from no user override.
    # Passing None preserves an explicit Trame CLI value; otherwise FOAMTrame
    # supplies its historical/configured default.
    explicit_port = any(
        token in {"--port", "-p"} or token.startswith("--port=")
        for token in sys.argv[1:]
    )
    port = None if explicit_port else settings.default_port
    explicit_host = any(
        token == "--host" or token.startswith("--host=") for token in sys.argv[1:]
    )
    host = None if explicit_host else trame_bind_host(startup_security_preferences)
    explicit_timeout = any(
        token == "--timeout" or token.startswith("--timeout=") for token in sys.argv[1:]
    )
    timeout = (
        None
        if explicit_timeout
        else trame_session_timeout_seconds(startup_security_preferences)
    )
    server.start(port=port, host=host, timeout=timeout)


if __name__ == "__main__":
    main()

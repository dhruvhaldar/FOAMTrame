from __future__ import annotations

import base64
import io
import logging
import os
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

from trame.widgets import html, vuetify

logger = logging.getLogger("FOAMTrame")

# Matplotlib backend must be set before importing pyplot
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_POLL_INTERVAL = 1  # seconds between data refreshes (default)

# Fields always attempted for residuals
_RESIDUAL_FIELDS = ["Ux", "Uy", "Uz", "p", "k", "epsilon", "omega", "T", "rho"]

# Colour cycle for consistent field colours (from FOAMFlask's plotlyColors)
_COLORS = [
    "#1dbde6",  # blue
    "#d62728",  # red
    "#2ca02c",  # green
    "#e377c2",  # magenta
    "#17becf",  # cyan
    "#ff7f0e",  # orange
    "#9467bd",  # purple
    "#8c564b",  # brown
    "#e377c2",  # pink
    "#7f7f7f",  # gray
    "#bcbd22",  # yellow
]

MODE_CACHED = "cached"
MODE_LIVE = "live"


# ---------------------------------------------------------------------------
# Chart rendering helpers
# ---------------------------------------------------------------------------

def _fig_to_b64(fig: plt.Figure) -> str:
    """Render a matplotlib figure to a base64-encoded PNG data URI."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=110)
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("ascii")
    plt.close(fig)
    return f"data:image/png;base64,{encoded}"


def _make_empty_chart(message: str = "No data yet") -> str:
    """Return a dark placeholder chart when no data is available."""
    fig, ax = plt.subplots(figsize=(6, 2.5), facecolor="#0f172a")
    ax.set_facecolor("#0f172a")
    ax.text(
        0.5, 0.5, message,
        transform=ax.transAxes,
        ha="center", va="center",
        color="#94a3b8", fontsize=10,
        multialignment="center",
    )
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    return _fig_to_b64(fig)


def _draw_mode_badge(ax, mode: str):
    """Draw a small mode badge on the top right of the axis."""
    mode_label = "LIVE" if mode == MODE_LIVE else "CACHED"
    mode_color = "#ef4444" if mode == MODE_LIVE else "#06b6d4"
    ax.text(
        0.98, 0.96, mode_label,
        transform=ax.transAxes, ha="right", va="top",
        fontsize=6, color=mode_color, fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.2", facecolor="#0f172a", edgecolor=mode_color, alpha=0.8),
    )


def _build_line_chart(
    time_vals: List[float],
    fields_data: Dict[str, List[float]],
    target_fields: List[str],
    title: str,
    y_label: str,
    mode: str,
    color_offset: int = 0
) -> str:
    """Generic helper to build line charts."""
    if not time_vals or not target_fields:
        return _make_empty_chart(f"No active fields for {title}")

    fig, ax = plt.subplots(figsize=(6, 2.8), facecolor="#0f172a")
    ax.set_facecolor("#0f172a")

    plotted = False
    for i, field in enumerate(target_fields):
        values = fields_data.get(field, [])
        n = min(len(time_vals), len(values))
        if n < 1:
            continue
        color = _COLORS[(i + color_offset) % len(_COLORS)]
        ax.plot(
            list(time_vals)[:n], list(values)[:n],
            label=field,
            color=color,
            linewidth=1.5,
            alpha=0.9,
        )
        plotted = True

    if not plotted:
        plt.close(fig)
        return _make_empty_chart(f"No data plotted for {title}")

    ax.set_xlabel("Time (s)", color="#94a3b8", fontsize=8)
    ax.set_ylabel(y_label, color="#94a3b8", fontsize=8)
    ax.tick_params(colors="#94a3b8", labelsize=7)
    for spine in ax.spines.values():
        spine.set_edgecolor("#334155")
    ax.legend(
        fontsize=7, framealpha=0.3, facecolor="#1e293b",
        edgecolor="#334155", labelcolor="#e2e8f0",
        loc="upper left"
    )

    _draw_mode_badge(ax, mode)
    fig.tight_layout()
    return _fig_to_b64(fig)


def _build_residuals_chart(residuals: Dict[str, list], mode: str) -> str:
    """Render residuals on a log-scale chart."""
    time_vals = list(residuals.get("time", []))
    if not time_vals:
        return _make_empty_chart(
            "No residuals log found\n(log.foamRun missing or simulation not started)"
        )

    active_fields = [
        f for f in _RESIDUAL_FIELDS
        if f in residuals and len(residuals[f]) > 0
    ]

    for f in residuals:
        if f != "time" and f not in active_fields and len(residuals[f]) > 0:
            active_fields.append(f)

    if not active_fields:
        return _make_empty_chart("No residual fields found in log")

    fig, ax = plt.subplots(figsize=(6, 2.8), facecolor="#0f172a")
    ax.set_facecolor("#0f172a")

    for i, field in enumerate(active_fields):
        values = list(residuals[field])
        n = min(len(time_vals), len(values))
        if n < 1:
            continue
        color = _COLORS[i % len(_COLORS)]
        ax.semilogy(
            time_vals[:n], values[:n],
            label=field,
            color=color,
            linewidth=1.4,
            alpha=0.9,
        )

    ax.set_xlabel("Time (s)", color="#94a3b8", fontsize=8)
    ax.set_ylabel("Residual", color="#94a3b8", fontsize=8)
    ax.tick_params(colors="#94a3b8", labelsize=7)
    for spine in ax.spines.values():
        spine.set_edgecolor("#334155")
    ax.yaxis.grid(True, color="#1e293b", linewidth=0.5)
    ax.legend(
        fontsize=7, framealpha=0.3, facecolor="#1e293b",
        edgecolor="#334155", labelcolor="#e2e8f0",
        loc="upper left"
    )

    _draw_mode_badge(ax, mode)
    fig.tight_layout()
    return _fig_to_b64(fig)


# ---------------------------------------------------------------------------
# Tab setup
# ---------------------------------------------------------------------------

def setup_plots_tab(server):
    state, ctrl = server.state, server.controller

    # --- State defaults ---
    state.setdefault("plots_scalar_chart", _make_empty_chart("Select an active case to start"))
    state.setdefault("plots_umag_chart", _make_empty_chart("Select an active case to start"))
    state.setdefault("plots_ucomponents_chart", _make_empty_chart("Select an active case to start"))
    state.setdefault("plots_residuals_chart", _make_empty_chart("Select an active case to start"))

    state.setdefault("plots_available_fields", [])
    state.setdefault("plots_selected_fields", [])
    state.setdefault("plots_status", "Idle")
    state.setdefault("plots_polling", False)
    state.setdefault("plots_poll_interval", _POLL_INTERVAL)
    state.setdefault("plots_mode", MODE_CACHED)

    _stop_event = threading.Event()
    _poller_thread: list = [None]

    def _get_case_dir() -> Optional[Path]:
        from tabs.setup_tab import load_config
        config = load_config()
        case_root = config.get("CASE_ROOT", "")
        active_case = getattr(state, "active_case", "") or ""
        if not case_root or not active_case:
            return None
        path = Path(case_root) / active_case
        return path if path.is_dir() else None

    def _poll_once():
        from backend.plots.realtime_plots import (
            OpenFOAMFieldParser,
            clear_cache,
        )

        case_dir = _get_case_dir()
        if case_dir is None:
            state.plots_status = "No active case selected"
            state.flush()
            return

        mode = getattr(state, "plots_mode", MODE_CACHED)
        case_dir_str = str(case_dir)

        if mode == MODE_LIVE:
            clear_cache(case_dir_str)

        try:
            parser = OpenFOAMFieldParser(case_dir_str)

            try:
                case_mtime = os.stat(case_dir_str).st_mtime
            except OSError:
                state.plots_status = "Case directory not accessible"
                state.flush()
                return

            field_data = parser.get_all_time_series_data(
                max_points=200,
                known_case_mtime=case_mtime,
            )

            time_vals = field_data.get("time", []) if field_data else []

            if field_data:
                # Available fields
                available = sorted(
                    k for k in field_data if k != "time" and len(field_data[k]) > 0
                )
                state.plots_available_fields = available

                # Auto-select fields to plot if empty
                selected = list(getattr(state, "plots_selected_fields", []) or [])
                selected = [f for f in selected if f in available]
                if not selected and available:
                    selected = [f for f in available if f not in ["Ux", "Uy", "Uz", "U_mag"]]
                    if not selected:
                        selected = available[:3]
                    state.plots_selected_fields = selected

                # 1. Scalar Plot (selected scalar fields, e.g. p, T, rho)
                state.plots_scalar_chart = _build_line_chart(
                    time_vals, field_data, selected, "Scalar Fields", "Value", mode, color_offset=0
                )

                # 2. Velocity Magnitude Plot (U_mag)
                umag_fields = [f for f in ["U_mag"] if f in available]
                state.plots_umag_chart = _build_line_chart(
                    time_vals, field_data, umag_fields, "Velocity Magnitude", "Velocity (m/s)", mode, color_offset=3
                )

                # 3. Velocity Components Plot (Ux, Uy, Uz)
                ucomp_fields = [f for f in ["Ux", "Uy", "Uz"] if f in available]
                state.plots_ucomponents_chart = _build_line_chart(
                    time_vals, field_data, ucomp_fields, "Velocity Components", "Velocity (m/s)", mode, color_offset=5
                )
            else:
                state.plots_scalar_chart = _make_empty_chart("No time step data found")
                state.plots_umag_chart = _make_empty_chart("No velocity data found")
                state.plots_ucomponents_chart = _make_empty_chart("No velocity component data found")

            # 4. Solver Residuals Plot
            residuals = parser.get_residuals_from_log()
            state.plots_residuals_chart = _build_residuals_chart(residuals, mode)

            n_steps = len(list(time_vals))
            mode_tag = "🔴 LIVE" if mode == MODE_LIVE else "🔵 CACHED"
            state.plots_status = (
                f"{mode_tag}  ·  {time.strftime('%H:%M:%S')}  ·  {n_steps} steps"
            )

        except Exception as exc:
            logger.error(f"[plots_tab] Poll error: {exc}")
            state.plots_status = f"Error: {exc}"

        state.flush()

    def _poller_loop():
        while not _stop_event.is_set():
            if getattr(state, "active_tab", -1) == 4:
                _poll_once()
            interval = float(getattr(state, "plots_poll_interval", _POLL_INTERVAL))
            _stop_event.wait(timeout=max(0.5, interval))

    def start_polling():
        if _poller_thread[0] and _poller_thread[0].is_alive():
            return
        _stop_event.clear()
        t = threading.Thread(target=_poller_loop, daemon=True)
        t.start()
        _poller_thread[0] = t
        state.plots_polling = True
        state.plots_status = "Polling started"
        state.flush()

    def stop_polling():
        _stop_event.set()
        state.plots_polling = False
        state.plots_status = "Polling stopped"
        state.flush()

    def refresh_now():
        threading.Thread(target=_poll_once, daemon=True).start()

    def set_mode_cached():
        state.plots_mode = MODE_CACHED
        state.flush()
        threading.Thread(target=_poll_once, daemon=True).start()

    def set_mode_live():
        state.plots_mode = MODE_LIVE
        state.flush()
        threading.Thread(target=_poll_once, daemon=True).start()

    ctrl.plots_start_polling = start_polling
    ctrl.plots_stop_polling = stop_polling
    ctrl.plots_refresh_now = refresh_now
    ctrl.plots_set_mode_cached = set_mode_cached
    ctrl.plots_set_mode_live = set_mode_live

    @state.change("active_case")
    def on_active_case_change_plots(**_):
        state.plots_available_fields = []
        state.plots_selected_fields = []
        state.plots_scalar_chart = _make_empty_chart("Loading...")
        state.plots_umag_chart = _make_empty_chart("Loading...")
        state.plots_ucomponents_chart = _make_empty_chart("Loading...")
        state.plots_residuals_chart = _make_empty_chart("Loading...")
        state.flush()
        if getattr(state, "plots_polling", False):
            threading.Thread(target=_poll_once, daemon=True).start()

    @state.change("plots_selected_fields")
    def on_field_selection_change(**_):
        threading.Thread(target=_poll_once, daemon=True).start()

    start_polling()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def build_plots_drawer():
    from trame.app import get_server
    server = get_server()
    ctrl = server.controller

    with html.Div(v_show="active_tab === 4", classes="pa-4"):
        # Mode selector
        html.Div("Mode", classes="text-overline text--secondary mb-1")
        with html.Div(classes="mb-4"):
            html.P(
                "Cached: incremental updates (low I/O).\nLive: full re-read (always current).",
                classes="text-caption text--secondary mb-2 style-white-space-pre-line",
                style="white-space: pre-line;",
            )
            with vuetify.VBtnToggle(
                v_model=("plots_mode", MODE_CACHED),
                mandatory=True,
                dense=True,
                classes="w-100",
            ):
                vuetify.VBtn(
                    "Cached",
                    value=MODE_CACHED,
                    small=True,
                    click=ctrl.plots_set_mode_cached,
                    classes="flex-grow-1",
                )
                vuetify.VBtn(
                    "Live",
                    value=MODE_LIVE,
                    small=True,
                    click=ctrl.plots_set_mode_live,
                    classes="flex-grow-1",
                )

        vuetify.VDivider(classes="my-3")

        # Polling controls
        html.Div("Polling Controls", classes="text-overline text--secondary mb-1")
        with html.Div(classes="mb-4"):
            with vuetify.VRow(dense=True, classes="mb-2"):
                with vuetify.VCol(cols="6"):
                    vuetify.VBtn(
                        "Start",
                        click=ctrl.plots_start_polling,
                        block=True,
                        small=True,
                        classes="theme-btn-success",
                        disabled=("plots_polling",),
                    )
                with vuetify.VCol(cols="6"):
                    vuetify.VBtn(
                        "Stop",
                        click=ctrl.plots_stop_polling,
                        block=True,
                        small=True,
                        classes="theme-btn-warning",
                        disabled=("!plots_polling",),
                    )
            vuetify.VBtn(
                "Refresh Now",
                click=ctrl.plots_refresh_now,
                block=True,
                small=True,
                classes="theme-btn-primary mb-3",
            )
            vuetify.VTextField(
                v_model=("plots_poll_interval", _POLL_INTERVAL),
                label="Interval (s)",
                type="number",
                outlined=True,
                dense=True,
                hide_details=True,
            )

        vuetify.VDivider(classes="my-3")

        # Field selector
        html.Div("Field Selection", classes="text-overline text--secondary mb-1")
        vuetify.VSelect(
            v_model=("plots_selected_fields", []),
            items=("plots_available_fields", []),
            label="Scalar fields to plot",
            multiple=True,
            chips=True,
            small_chips=True,
            outlined=True,
            dense=True,
            hide_details=True,
        )


def build_plots_content():
    with vuetify.VContainer(
        fluid=True,
        classes="fill-height pa-4 overflow-y-auto",
        v_if="active_tab === 4",
        style="max-height: calc(100vh - 64px);",
    ):
        with vuetify.VRow(dense=True):
            with vuetify.VCol(cols="12"):
                vuetify.VAlert(
                    "{{ plots_status }}",
                    dense=True,
                    outlined=True,
                    type=("plots_polling ? (plots_mode === 'live' ? 'error' : 'info') : 'warning'",),
                    classes="mb-2",
                )

        with vuetify.VRow(dense=True):
            # 1. Scalar fields chart
            with vuetify.VCol(cols="12", md="6", classes="pa-2"):
                with vuetify.VCard(classes="glass-card pa-3 h-100"):
                    with vuetify.VCardTitle(classes="subtitle-2 font-weight-bold pb-1"):
                        html.Span("Scalar Fields Over Time")
                    with vuetify.VCardText(classes="pa-1"):
                        vuetify.VImg(
                            src=("plots_scalar_chart",),
                            contain=True,
                            max_width="100%",
                            style="border-radius: 8px;",
                        )

            # 2. Velocity magnitude chart
            with vuetify.VCol(cols="12", md="6", classes="pa-2"):
                with vuetify.VCard(classes="glass-card pa-3 h-100"):
                    with vuetify.VCardTitle(classes="subtitle-2 font-weight-bold pb-1"):
                        html.Span("Velocity Magnitude (U_mag)")
                    with vuetify.VCardText(classes="pa-1"):
                        vuetify.VImg(
                            src=("plots_umag_chart",),
                            contain=True,
                            max_width="100%",
                            style="border-radius: 8px;",
                        )

        with vuetify.VRow(dense=True):
            # 3. Velocity components chart
            with vuetify.VCol(cols="12", md="6", classes="pa-2"):
                with vuetify.VCard(classes="glass-card pa-3 h-100"):
                    with vuetify.VCardTitle(classes="subtitle-2 font-weight-bold pb-1"):
                        html.Span("Velocity Components (Ux, Uy, Uz)")
                    with vuetify.VCardText(classes="pa-1"):
                        vuetify.VImg(
                            src=("plots_ucomponents_chart",),
                            contain=True,
                            max_width="100%",
                            style="border-radius: 8px;",
                        )

            # 4. Residuals chart
            with vuetify.VCol(cols="12", md="6", classes="pa-2"):
                with vuetify.VCard(classes="glass-card pa-3 h-100"):
                    with vuetify.VCardTitle(classes="subtitle-2 font-weight-bold pb-1"):
                        html.Span("Solver Residuals (log scale)")
                    with vuetify.VCardText(classes="pa-1"):
                        vuetify.VImg(
                            src=("plots_residuals_chart",),
                            contain=True,
                            max_width="100%",
                            style="border-radius: 8px;",
                        )

from __future__ import annotations

import base64
import asyncio
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
import matplotlib.ticker as mticker

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


def _build_line_chart(
    time_vals: List[float],
    fields_data: Dict[str, List[float]],
    target_fields: List[str],
    title: str,
    y_label: str,
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

    fig.tight_layout()
    return _fig_to_b64(fig)


def _build_residuals_chart(residuals: Dict[str, list]) -> str:
    """Render residuals on a log-scale chart."""
    active_fields = [
        f for f in _RESIDUAL_FIELDS
        if f in residuals and len(residuals[f]) > 0
    ]

    for f in residuals:
        if f != "time" and f not in active_fields and len(residuals[f]) > 0:
            active_fields.append(f)

    if not active_fields:
        return _make_empty_chart(
            "No solver residuals yet\n(waiting for log.foamRun output)"
        )

    fig, ax = plt.subplots(figsize=(6, 2.8), facecolor="#0f172a")
    ax.set_facecolor("#0f172a")

    for i, field in enumerate(active_fields):
        values = list(residuals[field])
        n = len(values)
        if n < 1:
            continue
        color = _COLORS[i % len(_COLORS)]
        ax.semilogy(
            range(1, n + 1), values,
            label=field,
            color=color,
            linewidth=1.4,
            alpha=0.9,
        )

    ax.set_xlabel("Solver iteration", color="#94a3b8", fontsize=8)
    ax.set_ylabel("Residual", color="#94a3b8", fontsize=8)
    # Plain scientific notation avoids Matplotlib's math-text parser. Besides
    # being clearer at small sizes, this removes a thread-sensitive parser path
    # that can fail on labels such as ``$\mathdefault{10^{-3}}$``.
    ax.yaxis.set_major_formatter(mticker.LogFormatter(base=10, labelOnlyBase=False))
    ax.tick_params(colors="#94a3b8", labelsize=7)
    for spine in ax.spines.values():
        spine.set_edgecolor("#334155")
    ax.yaxis.grid(True, color="#1e293b", linewidth=0.5)
    ax.legend(
        fontsize=7, framealpha=0.3, facecolor="#1e293b",
        edgecolor="#334155", labelcolor="#e2e8f0",
        loc="upper left"
    )

    fig.tight_layout()
    return _fig_to_b64(fig)


# ---------------------------------------------------------------------------
# Tab setup
# ---------------------------------------------------------------------------

def setup_plots_tab(server):
    state, ctrl = server.state, server.controller

    # --- State defaults ---
    initial_case = getattr(state, "active_case", "") or ""
    loading_chart = _make_empty_chart("Loading...")
    initial_chart = (
        loading_chart
        if initial_case
        else _make_empty_chart("Select an active case to start")
    )
    state.setdefault("plots_scalar_chart", initial_chart)
    state.setdefault("plots_umag_chart", initial_chart)
    state.setdefault("plots_ucomponents_chart", initial_chart)
    state.setdefault("plots_residuals_chart", initial_chart)

    state.setdefault("plots_available_fields", [])
    state.setdefault("plots_selected_fields", [])
    state.setdefault(
        "plots_status",
        f"Loading plot data for {initial_case}..."
        if initial_case
        else "Waiting for an active case",
    )
    state.setdefault("plots_status_type", "info")
    state.setdefault("plots_mode", MODE_CACHED)
    state.setdefault("plots_loading", bool(initial_case))

    _stop_event = threading.Event()
    _wake_event = threading.Event()
    _poll_lock = threading.Lock()
    _poller_thread: list = [None]
    _plots_visible = [False]
    _simulation_running = [False]
    _refresh_requested = [True]
    _server_event_loop = [None]
    _loaded_case = [None]
    _chart_signatures: dict[str, object] = {}
    plot_state_keys = (
        "plots_scalar_chart",
        "plots_umag_chart",
        "plots_ucomponents_chart",
        "plots_residuals_chart",
        "plots_available_fields",
        "plots_selected_fields",
        "plots_status",
        "plots_status_type",
        "plots_mode",
        "plots_loading",
    )

    def request_refresh():
        _refresh_requested[0] = True
        _wake_event.set()

    def publish_plot_state():
        """Publish background plot changes on Trame's wslink event loop."""
        state.dirty(*plot_state_keys)
        state.flush()
        loop = _server_event_loop[0]
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(server.force_state_push, *plot_state_keys)

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
        from backend.plots.realtime_plots import OpenFOAMFieldParser

        case_dir = _get_case_dir()
        if case_dir is None:
            state.plots_status = "No active case selected"
            state.plots_status_type = "warning"
            state.plots_loading = False
            publish_plot_state()
            return

        if not _poll_lock.acquire(blocking=False):
            return

        mode = MODE_LIVE if _simulation_running[0] else MODE_CACHED
        state.plots_mode = mode
        case_dir_str = str(case_dir)
        first_load = _loaded_case[0] != case_dir_str

        try:
            if first_load:
                state.plots_loading = True
                state.plots_status = f"Loading plot data for {case_dir.name}..."
                state.plots_status_type = "info"
                publish_plot_state()

            parser = OpenFOAMFieldParser(case_dir_str)

            try:
                case_mtime = os.stat(case_dir_str).st_mtime
            except OSError:
                state.plots_status = "Case directory not accessible"
                state.plots_status_type = "error"
                return

            time_dirs = parser.get_time_directories(known_mtime=case_mtime)
            latest_dir_mtime = None
            if time_dirs:
                try:
                    latest_dir_mtime = os.stat(
                        str(parser.get_data_root() / time_dirs[-1])
                    ).st_mtime
                except OSError:
                    pass

            field_data = parser.get_all_time_series_data(
                max_points=200,
                known_case_mtime=case_mtime,
                known_latest_mtime=latest_dir_mtime,
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

                # Publish field discovery before the more expensive PNG renders.
                # The selector is therefore usable as soon as case data is found.
                if first_load:
                    publish_plot_state()

                series_signature = (
                    tuple(selected),
                    len(time_vals),
                    time_vals[-1] if time_vals else None,
                    tuple(
                        (field, len(field_data.get(field, [])),
                         field_data[field][-1] if field_data.get(field) else None)
                        for field in available
                    ),
                )

                # Rendering four PNGs is substantially more expensive than checking
                # the filesystem. Only redraw field charts when their data changed.
                if _chart_signatures.get("series") != series_signature:
                    state.plots_scalar_chart = _build_line_chart(
                        time_vals, field_data, selected, "Scalar Fields", "Value", color_offset=0
                    )
                    if first_load:
                        publish_plot_state()

                    umag_fields = [f for f in ["U_mag"] if f in available]
                    ucomp_fields = [f for f in ["Ux", "Uy", "Uz"] if f in available]
                    state.plots_umag_chart = _build_line_chart(
                        time_vals, field_data, umag_fields, "Velocity Magnitude", "Velocity (m/s)", color_offset=3
                    )
                    if first_load:
                        publish_plot_state()
                    state.plots_ucomponents_chart = _build_line_chart(
                        time_vals, field_data, ucomp_fields, "Velocity Components", "Velocity (m/s)", color_offset=5
                    )
                    if first_load:
                        publish_plot_state()
                    _chart_signatures["series"] = series_signature
            else:
                state.plots_scalar_chart = _make_empty_chart("No time step data found")
                state.plots_umag_chart = _make_empty_chart("No velocity data found")
                state.plots_ucomponents_chart = _make_empty_chart("No velocity component data found")

            # 4. Solver Residuals Plot
            residuals = parser.get_residuals_from_log()
            residual_signature = (
                tuple(
                    (field, len(values), values[-1] if len(values) else None)
                    for field, values in residuals.items()
                ),
            )
            if _chart_signatures.get("residuals") != residual_signature:
                state.plots_residuals_chart = _build_residuals_chart(residuals)
                _chart_signatures["residuals"] = residual_signature

            n_steps = len(time_vals)
            if mode == MODE_LIVE:
                state.plots_status = f"LIVE · updating automatically · {n_steps} time steps"
                state.plots_status_type = "success"
            else:
                state.plots_status = f"CACHED · synchronized at {time.strftime('%H:%M:%S')} · {n_steps} time steps"
                state.plots_status_type = "info"
            state.plots_loading = False
            _loaded_case[0] = case_dir_str

        except Exception as exc:
            logger.error(f"[plots_tab] Poll error: {exc}")
            state.plots_status = f"Error: {exc}"
            state.plots_status_type = "error"
            state.plots_loading = False
        finally:
            try:
                publish_plot_state()
            finally:
                _poll_lock.release()

    def _poller_loop():
        while not _stop_event.is_set():
            _wake_event.clear()
            is_live = _simulation_running[0]
            is_visible = _plots_visible[0]
            should_refresh = _refresh_requested[0] or is_live or is_visible
            _refresh_requested[0] = False
            if should_refresh:
                try:
                    _poll_once()
                except Exception:
                    logger.exception("[plots_tab] Automatic update failed")
            _wake_event.wait(timeout=_POLL_INTERVAL if is_live else None)

    def start_polling():
        if _poller_thread[0] and _poller_thread[0].is_alive():
            return
        _stop_event.clear()
        t = threading.Thread(target=_poller_loop, daemon=True)
        t.start()
        _poller_thread[0] = t
        request_refresh()

    def stop_polling():
        _stop_event.set()
        _wake_event.set()

    def set_plots_visible(active_tab):
        _plots_visible[0] = int(active_tab) == 4
        if _plots_visible[0]:
            request_refresh()

    ctrl.plots_start_polling = start_polling
    ctrl.plots_stop_polling = stop_polling
    ctrl.plots_wake = request_refresh
    ctrl.plots_set_visible = set_plots_visible

    @ctrl.add("on_server_ready")
    def on_plots_server_ready(**_):
        _server_event_loop[0] = asyncio.get_running_loop()
        start_polling()
        request_refresh()

    @ctrl.add("on_client_connected")
    def on_plots_client_connected(**_):
        # A client may connect after the initial cached render completed.
        # Always publish a fresh snapshot for that client.
        request_refresh()

    @state.change("active_case")
    def on_active_case_change_plots(**_):
        state.plots_available_fields = []
        state.plots_selected_fields = []
        state.plots_scalar_chart = loading_chart
        state.plots_umag_chart = loading_chart
        state.plots_ucomponents_chart = loading_chart
        state.plots_residuals_chart = loading_chart
        _chart_signatures.clear()
        _loaded_case[0] = None
        state.plots_loading = True
        state.plots_status = "Loading plot data for the active case..."
        state.plots_status_type = "info"
        state.flush()
        request_refresh()

    @state.change("plots_selected_fields")
    def on_field_selection_change(**_):
        _chart_signatures.pop("series", None)
        request_refresh()

    @state.change("active_tab")
    def on_plots_tab_visibility_change(active_tab, **_):
        set_plots_visible(active_tab)

    @state.change("is_running")
    def on_simulation_state_change(is_running, **_):
        # A run transition invalidates prior data once. During the run, the
        # parser's append-only caches are retained for efficient incremental I/O.
        from backend.plots.realtime_plots import clear_cache

        was_running = _simulation_running[0]
        _simulation_running[0] = bool(is_running)
        case_dir = _get_case_dir()
        if case_dir is not None and was_running != _simulation_running[0]:
            clear_cache(str(case_dir))
        _chart_signatures.clear()
        state.plots_mode = MODE_LIVE if _simulation_running[0] else MODE_CACHED
        state.flush()
        request_refresh()

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def build_plots_drawer():
    from trame.app import get_server
    server = get_server()

    with html.Div(v_show="active_tab === 4", classes="pa-4"):
        html.Div("Automatic Updates", classes="text-overline text--secondary mb-1")
        with vuetify.VCard(classes="glass-card pa-3 mb-4", outlined=True):
            with html.Div(classes="d-flex align-center mb-1"):
                vuetify.VIcon(
                    "mdi-access-point",
                    color=("plots_mode === 'live' ? 'success' : 'cyan darken-2'",),
                    small=True,
                    classes="mr-2",
                )
                html.Strong("{{ plots_mode === 'live' ? 'Live' : 'Cached' }}")
            html.P(
                "{{ plots_mode === 'live' ? 'New solver data is detected every second.' : 'The completed result is served from the synchronized cache.' }}",
                classes="text-caption text--secondary mb-0",
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
        style="max-height: calc(100vh - 48px);",
    ):
        with vuetify.VRow(dense=True):
            with vuetify.VCol(cols="12"):
                with vuetify.VAlert(
                    dense=True,
                    text=True,
                    type=("plots_status_type", "info"),
                    classes="mb-2 plots-status-alert",
                ):
                    vuetify.VProgressCircular(
                        v_if="plots_loading",
                        indeterminate=True,
                        size=20,
                        width=2,
                        color="info",
                        classes="mr-3",
                    )
                    html.Span("{{ plots_status }}")

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

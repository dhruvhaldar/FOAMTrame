from __future__ import annotations

import base64
import asyncio
import io
import logging
import os
import threading
import time
from html import escape
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from cachebox import LRUCache, cached
from PIL import Image
from trame.widgets import client, html, vuetify

logger = logging.getLogger("FOAMTrame")

from app_state import load_plot_preferences, update_plot_preferences

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_POLL_INTERVAL = 1  # seconds between data refreshes (default)
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_HEROS_FONT_PATH = _PROJECT_ROOT / "static" / "fonts" / "texgyreheros-regular.otf"
_ROBOTO_FONT_PATH = _PROJECT_ROOT / "static" / "fonts" / "Roboto-Variable.ttf"
_LIBERATION_SERIF_FONT_PATH = (
    _PROJECT_ROOT / "static" / "fonts" / "LiberationSerif-Regular.ttf"
)
_FOAMFLASK_LOGO_PATH = _PROJECT_ROOT / "static" / "icons" / "foamflask-plot-logo.png"
_matplotlib_lock = threading.Lock()
_matplotlib_loaded = False
matplotlib: Any = None
plt: Any = None
mticker: Any = None
font_manager: Any = None
AnnotationBbox: Any = None
OffsetImage: Any = None


def _load_matplotlib() -> None:
    """Load the plotting stack on first render, after the web server can start."""
    global _matplotlib_loaded
    global AnnotationBbox, OffsetImage, font_manager, matplotlib, mticker, plt
    if _matplotlib_loaded:
        return
    with _matplotlib_lock:
        if _matplotlib_loaded:
            return
        import matplotlib as matplotlib_module

        matplotlib_module.use("Agg")
        import matplotlib.pyplot as pyplot_module
        import matplotlib.ticker as ticker_module
        from matplotlib import font_manager as font_manager_module
        from matplotlib.offsetbox import AnnotationBbox as annotation_bbox_class
        from matplotlib.offsetbox import OffsetImage as offset_image_class

        matplotlib = matplotlib_module
        plt = pyplot_module
        mticker = ticker_module
        font_manager = font_manager_module
        AnnotationBbox = annotation_bbox_class
        OffsetImage = offset_image_class

        for font_path in (
            _HEROS_FONT_PATH,
            _ROBOTO_FONT_PATH,
            _LIBERATION_SERIF_FONT_PATH,
        ):
            if font_path.is_file():
                font_manager.fontManager.addfont(str(font_path))
        _matplotlib_loaded = True


def _placeholder_chart(message: str) -> str:
    """Return a cheap startup placeholder without importing Matplotlib."""
    label = escape(message, quote=True)
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="840" height="392" '
        'viewBox="0 0 840 392" role="img">'
        '<rect width="100%" height="100%" fill="none"/>'
        '<text x="50%" y="50%" text-anchor="middle" dominant-baseline="middle" '
        'fill="#475569" font-family="Arial, sans-serif" font-size="20">'
        f"{label}</text></svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


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

_CHARTS = {
    "scalar": ("Scalar Fields Over Time", "plots_scalar_chart"),
    "umag": ("Velocity Magnitude (U_mag)", "plots_umag_chart"),
    "ucomponents": ("Velocity Components (Ux, Uy, Uz)", "plots_ucomponents_chart"),
    "residuals": ("Solver Residuals (log scale)", "plots_residuals_chart"),
}

_LIGHT_COLORS = [
    "#007c91",
    "#b91c1c",
    "#15803d",
    "#a21caf",
    "#0369a1",
    "#c2410c",
    "#6d28d9",
    "#7c2d12",
    "#be185d",
    "#334155",
    "#854d0e",
]


def _font_properties(font_choice: str) -> font_manager.FontProperties:
    _load_matplotlib()
    if font_choice == "helvetica_neue" and _HEROS_FONT_PATH.is_file():
        return font_manager.FontProperties(fname=str(_HEROS_FONT_PATH))
    if font_choice == "roboto" and _ROBOTO_FONT_PATH.is_file():
        return font_manager.FontProperties(fname=str(_ROBOTO_FONT_PATH))
    if font_choice == "times_new_roman":
        if _LIBERATION_SERIF_FONT_PATH.is_file():
            return font_manager.FontProperties(fname=str(_LIBERATION_SERIF_FONT_PATH))
        return font_manager.FontProperties(family=["DejaVu Serif"])
    return font_manager.FontProperties(
        family=["Arial", "Liberation Sans", "DejaVu Sans"]
    )


def _plot_style(
    background: str = "glass",
    font_choice: str = "helvetica_neue",
    logo_mode: str = "none",
    custom_logo_data: str = "",
    *,
    export: bool = False,
    maximized: bool = False,
) -> Dict[str, Any]:
    """Return a contrast-safe style; exports always use white paper."""
    effective_background = "white" if export else background
    backgrounds = {
        "glass": {
            "figure": "none",
            "axes": "none",
            "text": "#0f172a",
            "muted": "#475569",
            "grid": "#94a3b8",
            "spine": "#64748b",
            "legend": (1.0, 1.0, 1.0, 0.62),
            "transparent": True,
        },
        "white": {
            "figure": "#ffffff",
            "axes": "#ffffff",
            "text": "#111827",
            "muted": "#475569",
            "grid": "#cbd5e1",
            "spine": "#94a3b8",
            "legend": "#ffffff",
            "transparent": False,
        },
        "grey": {
            "figure": "#e5e7eb",
            "axes": "#f1f5f9",
            "text": "#111827",
            "muted": "#475569",
            "grid": "#94a3b8",
            "spine": "#64748b",
            "legend": "#f8fafc",
            "transparent": False,
        },
        "black": {
            "figure": "#0f172a",
            "axes": "#0f172a",
            "text": "#f8fafc",
            "muted": "#cbd5e1",
            "grid": "#334155",
            "spine": "#64748b",
            "legend": "#1e293b",
            "transparent": False,
        },
    }
    style: Dict[str, Any] = dict(
        backgrounds.get(effective_background, backgrounds["glass"])
    )
    style.update(
        {
            "background": effective_background,
            "font": _font_properties(font_choice),
            "colors": _COLORS if effective_background == "black" else _LIGHT_COLORS,
            "logo_mode": logo_mode,
            "custom_logo_data": custom_logo_data,
            "figsize": (6, 2.8),
            "dpi": 140,
            "font_scale": 1.0,
            "line_scale": 1.0,
        }
    )
    if maximized:
        style.update(
            figsize=(12, 5.8),
            dpi=180,
            font_scale=1.45,
            line_scale=1.25,
        )
    elif export:
        style.update(
            figsize=(10, 5),
            dpi=200,
            font_scale=1.3,
            line_scale=1.15,
        )
    return style


@cached(LRUCache(maxsize=4))
def _logo_array(logo_mode: str, custom_logo_data: str = "") -> Optional[np.ndarray]:
    _load_matplotlib()
    try:
        if logo_mode == "foamflask" and _FOAMFLASK_LOGO_PATH.is_file():
            with Image.open(_FOAMFLASK_LOGO_PATH) as image:
                return np.asarray(image.convert("RGBA").copy())
        if logo_mode == "custom" and custom_logo_data:
            encoded = custom_logo_data.split(",", 1)[-1]
            # Trame transports uploads as Base64; this is not encryption.
            raw = base64.b64decode(encoded, validate=True)  # nosec
            with Image.open(io.BytesIO(raw)) as image:
                image = image.convert("RGBA")
                image.thumbnail((240, 120), Image.Resampling.LANCZOS)
                return np.asarray(image.copy())
    except Exception as exc:
        logger.warning("Could not render plot logo: %s", exc)
    return None


def _add_plot_logo(ax, style: Dict[str, Any]):
    """Place the logo in a reserved right margin, never over plotted data."""
    _load_matplotlib()
    logo = _logo_array(style["logo_mode"], style["custom_logo_data"])
    if logo is None:
        return None
    longest_edge = max(logo.shape[0], logo.shape[1])
    zoom = min(0.32, 34 * style.get("font_scale", 1.0) / max(longest_edge, 1))
    artist = AnnotationBbox(
        OffsetImage(logo, zoom=zoom),
        (1.02, 1.0),
        xycoords="axes fraction",
        box_alignment=(0, 1),
        frameon=False,
        pad=0,
        clip_on=False,
        zorder=20,
    )
    ax.add_artist(artist)
    return artist


def _add_non_overlapping_legend(ax, style: Dict[str, Any]):
    """Place a responsive legend in reserved space above the data axes.

    A fixed in-axes corner can obscure peaks, residual drops, or flat series.
    Keeping the legend just outside the axes guarantees that it never covers a
    plotted value while retaining it inside the exported chart image.
    """
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return None
    legend_font = style["font"].copy()
    legend_font.set_size(7 * style.get("font_scale", 1.0))
    columns = min(4, len(handles))
    return ax.legend(
        handles,
        labels,
        prop=legend_font,
        framealpha=0.9,
        facecolor=style["legend"],
        edgecolor=style["spine"],
        labelcolor=style["text"],
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        borderaxespad=0,
        ncol=columns,
    )


# ---------------------------------------------------------------------------
# Chart rendering helpers
# ---------------------------------------------------------------------------


def _fig_to_b64(fig: plt.Figure, style: Optional[Dict[str, Any]] = None) -> str:
    """Render a matplotlib figure to a base64-encoded PNG data URI."""
    _load_matplotlib()
    style = style or _plot_style()
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        bbox_inches="tight",
        dpi=style.get("dpi", 140),
        transparent=style["transparent"],
        facecolor=style["figure"] if not style["transparent"] else "none",
    )
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode("ascii")
    plt.close(fig)
    return f"data:image/png;base64,{encoded}"


def _make_empty_chart(
    message: str = "No data yet", style: Optional[Dict[str, Any]] = None
) -> str:
    """Return a placeholder chart matching the selected presentation style."""
    style = style or _plot_style()
    fig, ax = plt.subplots(
        figsize=style.get("figsize", (6, 2.5)), facecolor=style["figure"]
    )
    ax.set_facecolor(style["axes"])
    ax.text(
        0.5,
        0.5,
        message,
        transform=ax.transAxes,
        ha="center",
        va="center",
        color=style["muted"],
        fontsize=10 * style.get("font_scale", 1.0),
        fontproperties=style["font"],
        multialignment="center",
    )
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)
    return _fig_to_b64(fig, style)


def _build_line_chart(
    time_vals: List[float],
    fields_data: Dict[str, List[float]],
    target_fields: List[str],
    title: str,
    y_label: str,
    color_offset: int = 0,
    style: Optional[Dict[str, Any]] = None,
) -> str:
    """Generic helper to build line charts."""
    style = style or _plot_style()
    if not time_vals or not target_fields:
        return _make_empty_chart(f"No active fields for {title}", style)

    fig, ax = plt.subplots(
        figsize=style.get("figsize", (6, 2.8)), facecolor=style["figure"]
    )
    ax.set_facecolor(style["axes"])

    plotted = False
    for i, field in enumerate(target_fields):
        values = fields_data.get(field, [])
        n = min(len(time_vals), len(values))
        if n < 1:
            continue
        colors = style["colors"]
        color = colors[(i + color_offset) % len(colors)]
        ax.plot(
            list(time_vals)[:n],
            list(values)[:n],
            label=field,
            color=color,
            linewidth=1.5 * style.get("line_scale", 1.0),
            alpha=0.9,
        )
        plotted = True

    if not plotted:
        plt.close(fig)
        return _make_empty_chart(f"No data plotted for {title}", style)

    font_scale = style.get("font_scale", 1.0)
    ax.set_xlabel(
        "Time (s)",
        color=style["muted"],
        fontsize=8 * font_scale,
        fontproperties=style["font"],
    )
    ax.set_ylabel(
        y_label,
        color=style["muted"],
        fontsize=8 * font_scale,
        fontproperties=style["font"],
    )
    ax.tick_params(colors=style["muted"], labelsize=7 * font_scale)
    for label in (*ax.get_xticklabels(), *ax.get_yticklabels()):
        label.set_fontproperties(style["font"])
    for spine in ax.spines.values():
        spine.set_edgecolor(style["spine"])
    ax.grid(True, color=style["grid"], linewidth=0.55, alpha=0.38)
    _add_non_overlapping_legend(ax, style)

    _add_plot_logo(ax, style)
    fig.tight_layout()
    return _fig_to_b64(fig, style)


def _build_residuals_chart(
    residuals: Dict[str, list], style: Optional[Dict[str, Any]] = None
) -> str:
    """Render residuals on a log-scale chart."""
    style = style or _plot_style()
    active_fields = [
        f for f in _RESIDUAL_FIELDS if f in residuals and len(residuals[f]) > 0
    ]

    for f in residuals:
        if f != "time" and f not in active_fields and len(residuals[f]) > 0:
            active_fields.append(f)

    if not active_fields:
        return _make_empty_chart(
            "No solver residuals yet\n(waiting for log.foamRun output)", style
        )

    fig, ax = plt.subplots(
        figsize=style.get("figsize", (6, 2.8)), facecolor=style["figure"]
    )
    ax.set_facecolor(style["axes"])

    for i, field in enumerate(active_fields):
        values = list(residuals[field])
        n = len(values)
        if n < 1:
            continue
        colors = style["colors"]
        color = colors[i % len(colors)]
        ax.semilogy(
            range(1, n + 1),
            values,
            label=field,
            color=color,
            linewidth=1.4 * style.get("line_scale", 1.0),
            alpha=0.9,
        )

    font_scale = style.get("font_scale", 1.0)
    ax.set_xlabel(
        "Solver iteration",
        color=style["muted"],
        fontsize=8 * font_scale,
        fontproperties=style["font"],
    )
    ax.set_ylabel(
        "Residual",
        color=style["muted"],
        fontsize=8 * font_scale,
        fontproperties=style["font"],
    )
    # Plain scientific notation avoids Matplotlib's math-text parser. Besides
    # being clearer at small sizes, this removes a thread-sensitive parser path
    # that can fail on labels such as ``$\mathdefault{10^{-3}}$``.
    ax.yaxis.set_major_formatter(mticker.LogFormatter(base=10, labelOnlyBase=False))
    ax.tick_params(colors=style["muted"], labelsize=7 * font_scale)
    for label in (*ax.get_xticklabels(), *ax.get_yticklabels()):
        label.set_fontproperties(style["font"])
    for spine in ax.spines.values():
        spine.set_edgecolor(style["spine"])
    ax.yaxis.grid(True, color=style["grid"], linewidth=0.55, alpha=0.42)
    _add_non_overlapping_legend(ax, style)

    _add_plot_logo(ax, style)
    fig.tight_layout()
    return _fig_to_b64(fig, style)


def _render_chart(
    chart_key: str,
    field_data: Dict[str, List[float]],
    residuals: Dict[str, list],
    selected: List[str],
    style: Dict[str, Any],
) -> str:
    time_vals = field_data.get("time", []) if field_data else []
    available = {
        key for key, values in field_data.items() if key != "time" and len(values)
    }
    if chart_key == "scalar":
        return _build_line_chart(
            time_vals, field_data, selected, "Scalar Fields", "Value", 0, style
        )
    if chart_key == "umag":
        return _build_line_chart(
            time_vals,
            field_data,
            ["U_mag"] if "U_mag" in available else [],
            "Velocity Magnitude",
            "Velocity (m/s)",
            3,
            style,
        )
    if chart_key == "ucomponents":
        return _build_line_chart(
            time_vals,
            field_data,
            [field for field in ("Ux", "Uy", "Uz") if field in available],
            "Velocity Components",
            "Velocity (m/s)",
            5,
            style,
        )
    return _build_residuals_chart(residuals, style)


def _uploaded_logo_data(file_value) -> str:
    """Validate an uploaded raster logo and normalize it to a PNG data URL."""
    item = (
        file_value[0]
        if isinstance(file_value, (list, tuple)) and file_value
        else file_value
    )
    content = (
        item.get("content")
        if isinstance(item, dict)
        else getattr(item, "content", None)
    )
    if content is None:
        raise ValueError("The selected logo could not be read")
    if isinstance(content, bytes):
        raw = content
    elif isinstance(content, str):
        # Trame transports uploads as Base64; this is not encryption.
        raw = base64.b64decode(  # nosec
            content.split(",", 1)[-1], validate=True
        )
    elif isinstance(content, (list, tuple)):
        raw = bytes(content)
    else:
        raise ValueError("Unsupported logo encoding")
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Custom logos must be 2 MB or smaller")
    with Image.open(io.BytesIO(raw)) as image:
        if image.format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("Choose a PNG, JPEG, or WebP logo")
        image = image.convert("RGBA")
        image.thumbnail((640, 320), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode(
        "ascii"
    )


# ---------------------------------------------------------------------------
# Tab setup
# ---------------------------------------------------------------------------


def setup_plots_tab(server):
    state, ctrl = server.state, server.controller
    plot_preferences = load_plot_preferences()

    # --- State defaults ---
    initial_case = getattr(state, "active_case", "") or ""
    loading_chart = _placeholder_chart("Loading...")
    initial_chart = (
        loading_chart
        if initial_case
        else _placeholder_chart("Select an active case to start")
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
    state.setdefault("plots_font", plot_preferences["font"])
    state.setdefault("plots_background", plot_preferences["background"])
    state.setdefault("plots_logo_mode", plot_preferences["logo_mode"])
    state.setdefault("plots_logo_upload", None)
    state.setdefault("plots_custom_logo_data", plot_preferences["custom_logo_data"])
    state.setdefault("plots_logo_status", "")
    state.setdefault("plots_maximized", False)
    state.setdefault("plots_active_chart", "scalar")
    state.setdefault("plots_active_chart_title", _CHARTS["scalar"][0])
    state.setdefault("plots_maximized_src", initial_chart)

    _stop_event = threading.Event()
    _wake_event = threading.Event()
    _poll_lock = threading.Lock()
    _poller_thread: list = [None]
    _plots_visible = [False]
    _simulation_running = [False]
    _refresh_requested = [True]
    _server_event_loop = [None]
    _loaded_case = [None]
    _latest_payload: list[Dict[str, Any]] = [
        {"field_data": {}, "residuals": {}, "selected": []}
    ]
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
        "plots_maximized_src",
    )

    def request_refresh():
        _refresh_requested[0] = True
        _wake_event.set()

    def current_appearance() -> tuple[str, str, str, str]:
        return (
            getattr(state, "plots_font", "helvetica_neue"),
            getattr(state, "plots_background", "glass"),
            getattr(state, "plots_logo_mode", "none"),
            getattr(state, "plots_custom_logo_data", "") or "",
        )

    def render_maximized_chart(chart_key: str, *, force: bool = False) -> None:
        payload = _latest_payload[0]
        appearance = current_appearance()
        source_signature = (
            chart_key,
            appearance,
            _chart_signatures.get(
                "residuals" if chart_key == "residuals" else "series"
            ),
        )
        if not force and _chart_signatures.get("maximized") == source_signature:
            return
        style = _plot_style(
            appearance[1],
            appearance[0],
            appearance[2],
            appearance[3],
            maximized=True,
        )
        state.plots_maximized_src = _render_chart(
            chart_key,
            payload["field_data"],
            payload["residuals"],
            payload["selected"],
            style,
        )
        _chart_signatures["maximized"] = source_signature

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
        appearance = current_appearance()
        style = _plot_style(appearance[1], appearance[0], appearance[2], appearance[3])

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
                    selected = [
                        f for f in available if f not in ["Ux", "Uy", "Uz", "U_mag"]
                    ]
                    if not selected:
                        selected = available[:3]
                    state.plots_selected_fields = selected

                # Publish field discovery before the more expensive PNG renders.
                # The selector is therefore usable as soon as case data is found.
                if first_load:
                    publish_plot_state()

                series_signature = (
                    appearance,
                    tuple(selected),
                    len(time_vals),
                    time_vals[-1] if time_vals else None,
                    tuple(
                        (
                            field,
                            len(field_data.get(field, [])),
                            field_data[field][-1] if field_data.get(field) else None,
                        )
                        for field in available
                    ),
                )

                # Rendering four PNGs is substantially more expensive than checking
                # the filesystem. Only redraw field charts when their data changed.
                if _chart_signatures.get("series") != series_signature:
                    state.plots_scalar_chart = _build_line_chart(
                        time_vals,
                        field_data,
                        selected,
                        "Scalar Fields",
                        "Value",
                        color_offset=0,
                        style=style,
                    )
                    if first_load:
                        publish_plot_state()

                    umag_fields = [f for f in ["U_mag"] if f in available]
                    ucomp_fields = [f for f in ["Ux", "Uy", "Uz"] if f in available]
                    state.plots_umag_chart = _build_line_chart(
                        time_vals,
                        field_data,
                        umag_fields,
                        "Velocity Magnitude",
                        "Velocity (m/s)",
                        color_offset=3,
                        style=style,
                    )
                    if first_load:
                        publish_plot_state()
                    state.plots_ucomponents_chart = _build_line_chart(
                        time_vals,
                        field_data,
                        ucomp_fields,
                        "Velocity Components",
                        "Velocity (m/s)",
                        color_offset=5,
                        style=style,
                    )
                    if first_load:
                        publish_plot_state()
                    _chart_signatures["series"] = series_signature
            else:
                state.plots_scalar_chart = _make_empty_chart(
                    "No time step data found", style
                )
                state.plots_umag_chart = _make_empty_chart(
                    "No velocity data found", style
                )
                state.plots_ucomponents_chart = _make_empty_chart(
                    "No velocity component data found", style
                )

            # 4. Solver Residuals Plot
            residuals = parser.get_residuals_from_log()
            residual_signature = (
                appearance,
                tuple(
                    (field, len(values), values[-1] if len(values) else None)
                    for field, values in residuals.items()
                ),
            )
            if _chart_signatures.get("residuals") != residual_signature:
                state.plots_residuals_chart = _build_residuals_chart(residuals, style)
                _chart_signatures["residuals"] = residual_signature

            _latest_payload[0] = {
                "field_data": field_data,
                "residuals": residuals,
                "selected": list(getattr(state, "plots_selected_fields", []) or []),
            }
            active_chart = getattr(state, "plots_active_chart", "scalar")
            active_state_key = _CHARTS.get(active_chart, _CHARTS["scalar"])[1]
            if getattr(state, "plots_maximized", False):
                render_maximized_chart(active_chart)
            else:
                state.plots_maximized_src = getattr(state, active_state_key)

            n_steps = len(time_vals)
            if mode == MODE_LIVE:
                state.plots_status = (
                    f"LIVE · updating automatically · {n_steps} time steps"
                )
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

    def select_plot(chart_key: str, maximize: bool = True):
        if chart_key not in _CHARTS:
            return
        title, state_key = _CHARTS[chart_key]
        state.plots_active_chart = chart_key
        state.plots_active_chart_title = title
        if _poll_lock.acquire(timeout=10):
            try:
                render_maximized_chart(chart_key, force=True)
            finally:
                _poll_lock.release()
        else:
            state.plots_maximized_src = getattr(state, state_key)
        if maximize:
            state.plots_maximized = True
        state.flush()

    def render_plot_export(chart_key: Optional[str] = None):
        key = chart_key or getattr(state, "plots_active_chart", "scalar")
        if key not in _CHARTS:
            key = "scalar"
        if not _poll_lock.acquire(timeout=10):
            raise RuntimeError("Plot data is busy; try saving again in a moment")
        try:
            payload = _latest_payload[0]
            style = _plot_style(
                "white",
                getattr(state, "plots_font", "helvetica_neue"),
                getattr(state, "plots_logo_mode", "none"),
                getattr(state, "plots_custom_logo_data", "") or "",
                export=True,
            )
            image_uri = _render_chart(
                key,
                payload["field_data"],
                payload["residuals"],
                payload["selected"],
                style,
            )
        finally:
            _poll_lock.release()
        case_name = getattr(state, "active_case", "case") or "case"
        safe_case = "".join(
            char if char.isalnum() or char in "-_" else "_" for char in case_name
        )
        return {
            "url": image_uri,
            "name": f"{safe_case}-{key}.png",
        }

    ctrl.plots_select_chart = select_plot
    ctrl.plots_render_export = render_plot_export

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

    @state.change(
        "plots_font", "plots_background", "plots_logo_mode", "plots_custom_logo_data"
    )
    def on_plot_appearance_change(**_):
        update_plot_preferences(
            {
                "font": getattr(state, "plots_font", "helvetica_neue"),
                "background": getattr(state, "plots_background", "glass"),
                "logo_mode": getattr(state, "plots_logo_mode", "none"),
                "custom_logo_data": getattr(state, "plots_custom_logo_data", "") or "",
            }
        )
        _chart_signatures.clear()
        _loaded_case[0] = None
        state.plots_loading = True
        state.plots_status = "Applying plot appearance..."
        state.plots_status_type = "info"
        state.flush()
        request_refresh()

    @state.change("plots_logo_upload")
    def on_plot_logo_upload(plots_logo_upload, **_):
        if not plots_logo_upload:
            return
        try:
            state.plots_custom_logo_data = _uploaded_logo_data(plots_logo_upload)
            state.plots_logo_mode = "custom"
            state.plots_logo_status = "Custom logo ready"
            _logo_array.cache_clear()  # ty: ignore[unresolved-attribute]
        except Exception as exc:
            state.plots_logo_status = str(exc)
        finally:
            state.plots_logo_upload = None
            state.flush()

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

        html.Div("Plot Appearance", classes="text-overline text--secondary mb-1")
        vuetify.VSelect(
            v_model=("plots_font", "helvetica_neue"),
            items=(
                "[{ text: 'Helvetica Neue', value: 'helvetica_neue' }, { text: 'Roboto', value: 'roboto' }, { text: 'Times New Roman', value: 'times_new_roman' }, { text: 'Arial', value: 'arial' }]",
            ),
            label="Font",
            outlined=True,
            dense=True,
            hide_details=True,
            classes="mb-2",
        )
        html.P(
            "Helvetica uses bundled TeX Gyre Heros; Times New Roman uses bundled Liberation Serif.",
            classes="text-caption text--secondary mb-3",
        )
        vuetify.VSelect(
            v_model=("plots_background", "glass"),
            items=(
                "[{ text: 'Glass', value: 'glass' }, { text: 'White', value: 'white' }, { text: 'Black', value: 'black' }, { text: 'Grey', value: 'grey' }]",
            ),
            label="On-screen background",
            outlined=True,
            dense=True,
            hide_details=True,
            classes="mb-2",
        )
        html.P(
            "Saved PNG files always use a white paper background.",
            classes="text-caption text--secondary mb-3",
        )
        vuetify.VSelect(
            v_model=("plots_logo_mode", "none"),
            items=(
                "[{ text: 'No logo', value: 'none' }, { text: 'FOAMFlask logo', value: 'foamflask' }, { text: 'Custom logo', value: 'custom' }]",
            ),
            label="Plot logo",
            outlined=True,
            dense=True,
            hide_details=True,
            classes="mb-2",
        )
        vuetify.VFileInput(
            v_if="plots_logo_mode === 'custom'",
            v_model=("plots_logo_upload", None),
            label="Custom logo",
            accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp",
            prepend_icon="mdi-image-outline",
            outlined=True,
            dense=True,
            show_size=True,
            hide_details=True,
            classes="mb-2",
        )
        html.P(
            "{{ plots_logo_status }}",
            v_if="plots_logo_status",
            classes="text-caption text--secondary mb-3",
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
    from trame.app import get_server

    server = get_server()
    assert server is not None
    state, ctrl = server.state, server.controller
    download_exec = client.JSEval(
        exec="""
          const anchor = document.createElement('a');
          anchor.href = $event.url;
          anchor.download = $event.name;
          document.body.appendChild(anchor);
          anchor.click();
          anchor.remove();
        """
    )

    def export_chart(chart_key: Optional[str] = None):
        try:
            download_exec.exec(ctrl.plots_render_export(chart_key))
            state.plots_status = "White-background PNG download started"
            state.plots_status_type = "success"
        except Exception as exc:
            state.plots_status = f"Could not save plot: {exc}"
            state.plots_status_type = "error"
        state.flush()

    ctrl.plots_export_chart = export_chart

    def plot_card(chart_key: str):
        title, state_key = _CHARTS[chart_key]
        with vuetify.VCol(cols="12", md="6", classes="pa-2"):
            with vuetify.VCard(classes="glass-card plot-card pa-3 h-100"):
                with vuetify.VCardTitle(
                    classes="subtitle-2 font-weight-bold pb-1 d-flex align-center"
                ):
                    html.Span(title)
                    vuetify.VSpacer()
                    with vuetify.VBtn(
                        icon=True,
                        small=True,
                        title="Save as PNG",
                        aria_label=f"Save {title} as PNG",
                        disabled=("plots_loading",),
                        click=lambda key=chart_key: ctrl.plots_export_chart(key),
                    ):
                        vuetify.VIcon("mdi-download-outline", small=True)
                    with vuetify.VBtn(
                        icon=True,
                        small=True,
                        title="Maximize plot",
                        aria_label=f"Maximize {title} plot",
                        click=lambda key=chart_key: ctrl.plots_select_chart(key, True),
                    ):
                        vuetify.VIcon("mdi-arrow-expand-all", small=True)
                with vuetify.VCardText(classes="pa-1"):
                    vuetify.VImg(
                        src=(state_key,),
                        contain=True,
                        max_width="100%",
                        classes="plot-rendered-image",
                        style="border-radius: 8px;",
                        alt=f"{title} plot",
                    )

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
                    role="status",
                    aria_live="polite",
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
            plot_card("scalar")
            plot_card("umag")
        with vuetify.VRow(dense=True):
            plot_card("ucomponents")
            plot_card("residuals")

    with vuetify.VDialog(
        v_model=("plots_maximized", False),
        fullscreen=True,
        hide_overlay=True,
        transition="dialog-bottom-transition",
        aria_labelledby="maximized-plot-title",
    ):
        with vuetify.VCard(classes="plots-maximized-dialog"):
            with vuetify.VToolbar(dense=True, classes="glass-navbar flex-grow-0"):
                with vuetify.VBtn(
                    icon=True,
                    click="plots_maximized = false",
                    title="Close",
                    aria_label="Close maximized plot",
                ):
                    vuetify.VIcon("mdi-close")
                vuetify.VToolbarTitle(
                    "{{ plots_active_chart_title }}", id="maximized-plot-title"
                )
                vuetify.VSpacer()
                with vuetify.VBtn(
                    text=True,
                    disabled=("plots_loading",),
                    click=lambda: ctrl.plots_export_chart(None),
                    classes="theme-btn-primary",
                ):
                    vuetify.VIcon("mdi-download-outline", classes="mr-2")
                    html.Span("Save PNG")
            with vuetify.VContainer(fluid=True, classes="plots-maximized-body pa-4"):
                with vuetify.VRow(classes="fill-height"):
                    with vuetify.VCol(
                        cols="12", md="3", lg="2", classes="plots-maximized-sidebar"
                    ):
                        html.Div(
                            "Other plots", classes="text-overline text--secondary mb-2"
                        )
                        for chart_key, (title, _) in _CHARTS.items():
                            vuetify.VBtn(
                                title,
                                block=True,
                                outlined=(f"plots_active_chart !== '{chart_key}'",),
                                color=(
                                    f"plots_active_chart === '{chart_key}' ? 'primary' : 'grey darken-1'",
                                ),
                                click=lambda key=chart_key: ctrl.plots_select_chart(
                                    key, False
                                ),
                                classes="mb-2 justify-start",
                            )
                    with vuetify.VCol(
                        cols="12",
                        md="9",
                        lg="10",
                        classes="d-flex align-center justify-center",
                    ):
                        vuetify.VImg(
                            src=("plots_maximized_src",),
                            contain=True,
                            max_height="calc(100vh - 120px)",
                            max_width="100%",
                            classes="plots-maximized-image",
                        )

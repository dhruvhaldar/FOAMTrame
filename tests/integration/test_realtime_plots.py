from backend.plots.realtime_plots import OpenFOAMFieldParser, clear_cache
import base64
import io

import matplotlib.pyplot as plt
from PIL import Image

from tabs.plots_tab import (
    _build_line_chart,
    _build_residuals_chart,
    _add_plot_logo,
    _add_non_overlapping_legend,
    _plot_style,
    _font_properties,
    _uploaded_logo_data,
)


def test_residual_log_is_parsed_incrementally(tmp_path):
    log_path = tmp_path / "log.foamRun"
    log_path.write_text(
        "Time = 0.01s\n"
        "GAMG: Solving for p, Initial residual = 1e-2, Final residual = 1e-5, No Iterations 2\n"
        "GAMG: Solving for p, Initial residual = 5e-3, Final residual = 1e-6, No Iterations 1\n",
        encoding="utf-8",
    )

    parser = OpenFOAMFieldParser(tmp_path)
    first = parser.get_residuals_from_log()
    assert list(first["time"]) == [0.01]
    assert list(first["p"]) == [1e-2, 5e-3]

    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(
            "Time = 0.02s\n"
            "GAMG: Solving for p, Initial residual = 1e-3, Final residual = 1e-7, No Iterations 1\n"
        )

    updated = parser.get_residuals_from_log()
    assert list(updated["time"]) == [0.01, 0.02]
    assert list(updated["p"]) == [1e-2, 5e-3, 1e-3]
    chart = _build_residuals_chart(updated)
    assert chart.startswith("data:image/png;base64,")
    clear_cache(str(tmp_path))


def test_plot_appearance_export_and_custom_logo():
    glass = _plot_style("glass", "helvetica_neue")
    roboto = _plot_style("glass", "roboto")
    maximized = _plot_style("glass", "roboto", maximized=True)
    paper = _plot_style("black", "arial", export=True)
    assert glass["transparent"] is True
    assert "Roboto-Variable.ttf" in roboto["font"].get_file()
    assert maximized["figsize"] == (12, 5.8)
    assert maximized["dpi"] == 180
    assert maximized["font_scale"] > glass["font_scale"]
    assert paper["transparent"] is False
    assert paper["figure"] == "#ffffff"

    chart = _build_line_chart(
        [0.0, 1.0],
        {"time": [0.0, 1.0], "p": [1.0, 0.5]},
        ["p"],
        "Pressure",
        "p",
        style=paper,
    )
    png = base64.b64decode(chart.split(",", 1)[1])
    with Image.open(io.BytesIO(png)) as rendered:
        assert rendered.mode in {"RGB", "RGBA"}
        assert rendered.size[0] > 500

    logo_buffer = io.BytesIO()
    Image.new("RGBA", (20, 10), (6, 154, 181, 255)).save(logo_buffer, format="PNG")
    uploaded = _uploaded_logo_data(
        {
            "name": "logo.png",
            "type": "image/png",
            "size": len(logo_buffer.getvalue()),
            "content": base64.b64encode(logo_buffer.getvalue()).decode("ascii"),
        }
    )
    assert uploaded.startswith("data:image/png;base64,")


def test_times_font_uses_bundled_liberation_serif_without_warning(caplog):
    font = _font_properties("times_new_roman")
    font_file = font.get_file()
    assert isinstance(font_file, str)
    assert font_file.endswith("LiberationSerif-Regular.ttf")

    caplog.set_level("WARNING", logger="matplotlib.font_manager")
    _build_line_chart(
        [0.0, 1.0],
        {"time": [0.0, 1.0], "p": [1.0, 0.5]},
        ["p"],
        "Pressure",
        "p",
        style=_plot_style("glass", "times_new_roman"),
    )

    assert not [
        record for record in caplog.records if "Liberation Serif" in record.getMessage()
    ]


def test_plot_legend_is_reserved_outside_data_area():
    style = _plot_style("glass", "roboto")
    fig, ax = plt.subplots(figsize=(6, 2.8))
    for index in range(7):
        ax.plot(
            range(20),
            [((point + index) % 7) + index for point in range(20)],
            label=f"field-{index}",
        )

    legend = _add_non_overlapping_legend(ax, style)
    fig.canvas.draw()
    assert legend is not None
    assert legend.get_window_extent().y0 >= ax.get_window_extent().y1
    plt.close(fig)


def test_plot_logo_is_reserved_outside_data_area():
    style = _plot_style("glass", "roboto", "foamflask")
    fig, ax = plt.subplots(figsize=(6, 2.8))
    ax.plot(range(20), range(20), label="field")

    logo = _add_plot_logo(ax, style)
    fig.canvas.draw()
    assert logo is not None
    assert logo.get_window_extent().x0 >= ax.get_window_extent().x1
    plt.close(fig)

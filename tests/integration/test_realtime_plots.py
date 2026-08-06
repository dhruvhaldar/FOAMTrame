from backend.plots.realtime_plots import OpenFOAMFieldParser, clear_cache
from tabs.plots_tab import _build_residuals_chart


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

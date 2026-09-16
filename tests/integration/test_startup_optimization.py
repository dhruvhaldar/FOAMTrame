from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_meshing_import_does_not_initialize_opengl():
    subprocess.run(
        [
            sys.executable,
            "-c",
            """
import vtk
class GuardedInteractor(vtk.vtkRenderWindowInteractor):
    def Initialize(self):
        raise AssertionError('OpenGL initialized before a viewer was requested')
vtk.vtkRenderWindowInteractor = GuardedInteractor
import tabs.meshing_tab
""",
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_plots_tab_defers_matplotlib_until_a_chart_is_rendered():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import tabs.plots_tab as plots; "
                "assert 'matplotlib.pyplot' not in sys.modules; "
                "assert plots._placeholder_chart('Loading').startswith("
                "'data:image/svg+xml;base64,')"
            ),
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0

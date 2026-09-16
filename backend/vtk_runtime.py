"""Keep VTK diagnostics inside application logging, including on Windows."""

from __future__ import annotations

import logging

import vtk

_output: vtk.vtkOutputWindow | None = None
_logger = logging.getLogger("FOAMTrame.VTK")


@vtk.calldata_type(vtk.VTK_STRING)
def _log_diagnostic(_source, event: str, message: str | None) -> None:
    level = {"ErrorEvent": logging.ERROR, "WarningEvent": logging.WARNING}.get(
        event, logging.INFO
    )
    if message:
        _logger.log(level, "%s", message.rstrip())


def configure_vtk_logging() -> None:
    """Install a non-GUI sink before creating any VTK readers or renderers."""
    global _output
    if _output is None:
        _output = vtk.vtkOutputWindow()
        _output.SetDisplayModeToNever()
        for event in (
            vtk.vtkCommand.ErrorEvent,
            vtk.vtkCommand.WarningEvent,
            vtk.vtkCommand.TextEvent,
        ):
            _output.AddObserver(event, _log_diagnostic)
    vtk.vtkOutputWindow.SetInstance(_output)

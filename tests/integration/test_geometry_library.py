from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.geometry.library import (
    import_resource_geometry,
    is_supported_geometry_name,
    list_case_geometry,
    list_case_geometry_choices,
    list_resource_geometry,
    resolve_case_path,
)

pytestmark = pytest.mark.integration


class FakeContainers:
    def __init__(self, output: bytes = b""):
        self.output = output
        self.calls = []

    def run(self, image, command, **options):
        self.calls.append((image, command, options))
        if options.get("volumes"):
            destination = Path(next(iter(options["volumes"])))
            (destination / command[-1]).write_bytes(b"solid imported\nendsolid\n")
        return self.output


class FakeDockerClient:
    def __init__(self, output: bytes = b""):
        self.containers = FakeContainers(output)


def test_case_geometry_prefers_native_constant_geometry():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        tri_surface = root / "cavity" / "constant" / "triSurface"
        nested = tri_surface / "nested"
        nested.mkdir(parents=True)
        (tri_surface / "body.stl").write_text("solid body", encoding="utf-8")
        (nested / "detail.obj.gz").write_bytes(b"compressed")
        (tri_surface / "notes.txt").write_text("ignore", encoding="utf-8")
        outside = root / "cavity" / "VTK"
        outside.mkdir()
        (outside / "result.vtk").write_text("ignore", encoding="utf-8")
        geometry = root / "cavity" / "constant" / "geometry"
        geometry.mkdir()
        (geometry / "fallback.obj.gz").write_bytes(b"compressed")

        files = list_case_geometry(root, "cavity")

        assert [path.name for path in files] == ["fallback.obj.gz"]
        choices = list_case_geometry_choices(root, "cavity")
        assert list(choices) == ["", "body.stl", "nested/detail.obj.gz"]


def test_case_geometry_loads_constant_geometry_without_tri_surface():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        geometry = root / "aerofoil" / "constant" / "geometry"
        geometry.mkdir(parents=True)
        (geometry / "NACA0012.obj.gz").write_bytes(b"compressed")
        (geometry / "notes.txt").write_text("ignore", encoding="utf-8")

        files = list_case_geometry(root, "aerofoil")

        assert [path.name for path in files] == ["NACA0012.obj.gz"]


def test_case_geometry_uses_tri_surface_without_native_geometry():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        tri_surface = root / "cavity" / "constant" / "triSurface"
        tri_surface.mkdir(parents=True)
        (tri_surface / "body.stl").write_text("solid body", encoding="utf-8")

        files = list_case_geometry(root, "cavity")

        assert [path.name for path in files] == ["body.stl"]


def test_case_path_rejects_traversal():
    with tempfile.TemporaryDirectory() as directory:
        with pytest.raises(ValueError):
            resolve_case_path(directory, "../outside")


def test_resource_listing_filters_unsafe_and_unsupported_names():
    client = FakeDockerClient(
        b"motorBike.stl\naero.obj.gz\nnotes.txt\n../escape.stl\nbad name.stl\n"
    )

    files = list_resource_geometry(client, "openfoam:test", "12")

    assert files == ["aero.obj.gz", "motorBike.stl"]
    image, command, options = client.containers.calls[0]
    assert image == "openfoam:test"
    assert command[-1] == "12"
    assert options["network_disabled"] is True


def test_resource_import_uses_positional_filename_and_case_mount():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "cavity").mkdir()
        client = FakeDockerClient()

        with patch("backend.geometry.library.platform.system", return_value="Windows"):
            imported = import_resource_geometry(
                client, "openfoam:test", "12", root, "cavity", "motorBike.stl"
            )

        assert imported == root / "cavity" / "constant" / "triSurface" / "motorBike.stl"
        image, command, options = client.containers.calls[0]
        assert image == "openfoam:test"
        assert command[-1] == "motorBike.stl"
        assert options["volumes"][imported.parent.as_posix()]["bind"] == "/output"


def test_resource_import_rejects_tri_surface_symlink_outside_case():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        constant = root / "cavity" / "constant"
        constant.mkdir(parents=True)
        outside = root / "shared"
        outside.mkdir()
        try:
            (constant / "triSurface").symlink_to(outside, target_is_directory=True)
        except OSError:
            pytest.skip()

        client = FakeDockerClient()
        with pytest.raises(ValueError, match="resolves outside the active case"):
            import_resource_geometry(
                client, "openfoam:test", "12", root, "cavity", "motorBike.stl"
            )

        assert client.containers.calls == []


@pytest.mark.parametrize(
    "name", ["../escape.stl", "bad name.stl", "script.sh", "nested/body.obj"]
)
def test_resource_name_validation_rejects_unsafe_names(name):
    assert not is_supported_geometry_name(name)

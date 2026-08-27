from dataclasses import replace
from pathlib import Path

import pytest

from backend.case.capabilities import (
    CaseActionService,
    _read_solver,
    _read_solver_file,
    _docker_executables_cached,
    _safe_clean_targets,
    _safe_clean_targets_for_signature,
)


class FakeContainers:
    def __init__(self, executables):
        self.executables = set(executables)
        self.calls = []

    def run(self, image, command, **kwargs):
        self.calls.append((image, command, kwargs))
        requested = command[5:]
        found = [name for name in requested if name in self.executables]
        return ("\n".join(found) + "\n").encode()


class FakeDockerClient:
    def __init__(self, executables):
        self.containers = FakeContainers(executables)


class RecordingContainers:
    def __init__(self):
        self.calls = []
        self.container = object()

    def run(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.container


class RecordingDockerClient:
    def __init__(self):
        self.containers = RecordingContainers()


def build_case(root: Path, *, allrun: bool = False, allclean: bool = False) -> Path:
    case = root / "cavity"
    (case / "0").mkdir(parents=True)
    (case / "constant" / "polyMesh").mkdir(parents=True)
    (case / "system").mkdir()
    (case / "system" / "controlDict").write_text(
        """
        // application fakeFoam;
        application foamRun;
        solver incompressibleFluid;
        """,
        encoding="utf-8",
    )
    (case / "system" / "blockMeshDict").write_text("FoamFile {}", encoding="utf-8")
    (case / "system" / "setFieldsDict").write_text("FoamFile {}", encoding="utf-8")
    (case / "system" / "decomposeParDict").write_text("FoamFile {}", encoding="utf-8")
    if allrun:
        (case / "Allrun").write_text("#!/bin/sh\nfoamRun\n", encoding="utf-8")
    if allclean:
        (case / "Allclean").write_text("#!/bin/sh\ncleanCase\n", encoding="utf-8")
    return case


def inspect(service: CaseActionService, case: Path, executables):
    return service.inspect_case(
        case,
        docker_client=FakeDockerClient(executables),
        docker_image="openfoam:test",
        openfoam_version="12",
    )


def test_case_capabilities_detect_solver_scripts_and_prerequisites(tmp_path):
    service = CaseActionService()
    case = build_case(tmp_path, allrun=True, allclean=True)
    (case / "0.5").mkdir()
    (case / "processor0").mkdir()
    (case / "postProcessing").mkdir()
    (case / "VTK").mkdir()
    (case / "log.foamRun").write_text("done", encoding="utf-8")

    result = inspect(
        service,
        case,
        {
            "bash",
            "foamRun",
            "blockMesh",
            "setFields",
            "decomposePar",
            "reconstructPar",
            "foamToVTK",
        },
    )

    assert result.actions["allrun"].available is True
    assert result.actions["allrun"].preferred is True
    assert result.actions["allclean"].destructive is True
    assert result.actions["solver"].label == "foamRun — incompressibleFluid"
    assert result.actions["solver"].command == "foamRun"
    assert result.actions["blockMesh"].available is True
    assert result.actions["snappyHexMesh"].available is False
    assert result.actions["snappyHexMesh"].reason == "Missing system/snappyHexMeshDict"
    assert result.actions["reconstructPar"].available is True
    assert result.actions["foamToVTK"].available is True
    assert result.clean_target_labels() == [
        "0.5",
        "log.foamRun",
        "postProcessing",
        "processor0",
        "VTK",
    ]


def test_guided_run_contains_only_confident_available_steps(tmp_path):
    service = CaseActionService()
    case = build_case(tmp_path)

    result = inspect(service, case, {"foamRun", "blockMesh", "setFields"})

    assert result.actions["allrun"].available is False
    assert result.actions["allrun"].reason == "No Allrun script supplied"
    assert result.guided_actions == ("blockMesh", "setFields", "solver")
    assert result.guided_labels() == [
        "blockMesh",
        "setFields",
        "foamRun — incompressibleFluid",
    ]


def test_missing_docker_executable_disables_command_with_reason(tmp_path):
    service = CaseActionService()
    case = build_case(tmp_path)

    result = inspect(service, case, {"blockMesh"})

    assert result.actions["blockMesh"].available is True
    assert result.actions["solver"].available is False
    assert (
        "not available in the configured Docker image"
        in result.actions["solver"].reason
    )
    with pytest.raises(ValueError, match="unavailable"):
        service.resolve_actions(result, ["solver"])


def test_safe_clean_removes_only_reviewed_generated_outputs(tmp_path):
    service = CaseActionService()
    case = build_case(tmp_path)
    generated = [
        case / "1",
        case / "2.5e-3",
        case / "processor2",
        case / "postProcessing",
        case / "VTK",
    ]
    for path in generated:
        path.mkdir()
        (path / "result").write_text("generated", encoding="utf-8")
    (case / "log.blockMesh").write_text("generated", encoding="utf-8")

    result = inspect(service, case, {"foamRun", "blockMesh", "setFields"})
    removed = service.clean_case(result)

    assert set(removed) == {
        "1",
        "2.5e-3",
        "processor2",
        "postProcessing",
        "VTK",
        "log.blockMesh",
    }
    assert (case / "0").is_dir()
    assert (case / "constant" / "polyMesh").is_dir()
    assert (case / "system" / "controlDict").is_file()
    assert all(not path.exists() for path in generated)


def test_safe_clean_rejects_normalized_path_outside_case(tmp_path):
    service = CaseActionService()
    case = build_case(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "result"
    marker.write_text("keep", encoding="utf-8")
    inspection = inspect(service, case, {"foamRun", "blockMesh", "setFields"})
    escaped_target = case / "postProcessing" / ".." / ".." / outside.name

    with pytest.raises(ValueError, match="escaped the active case"):
        service.clean_case(replace(inspection, clean_targets=(escaped_target,)))

    assert marker.read_text(encoding="utf-8") == "keep"


def test_shared_runner_launches_only_resolved_fixed_id_actions(tmp_path):
    service = CaseActionService()
    case = build_case(tmp_path)
    inspection = inspect(service, case, {"foamRun", "blockMesh", "setFields"})
    client = RecordingDockerClient()

    container, actions = service.start_run(
        inspection,
        ["blockMesh", "setFields", "solver"],
        docker_client=client,
        docker_image="openfoam:test",
        openfoam_version="12",
    )

    assert container is client.containers.container
    assert [action.id for action in actions] == ["blockMesh", "setFields", "solver"]
    args, kwargs = client.containers.calls[0]
    assert args[0] == "openfoam:test"
    assert args[1][-3:] == ["blockMesh", "setFields", "foamRun"]
    assert kwargs["detach"] is True
    assert kwargs["working_dir"] == "/tmp/FOAM_Run"
    with pytest.raises(ValueError, match="Unknown case action"):
        service.start_run(
            inspection,
            ["foamRun; rm -rf /"],
            docker_client=client,
            docker_image="openfoam:test",
            openfoam_version="12",
        )


def test_cachebox_case_metadata_caches_and_invalidates(tmp_path):
    case = build_case(tmp_path)
    control_dict = case / "system" / "controlDict"

    _read_solver_file.cache_clear()
    assert _read_solver(case) == ("foamRun", "incompressibleFluid")
    assert _read_solver_file.cache_info().hits == 0
    assert _read_solver(case) == ("foamRun", "incompressibleFluid")
    assert _read_solver_file.cache_info().hits == 1

    control_dict.write_text("application simpleFoam;\n", encoding="utf-8")
    assert _read_solver(case) == ("simpleFoam", "")

    _safe_clean_targets_for_signature.cache_clear()
    assert _safe_clean_targets(case) == ()
    assert _safe_clean_targets_for_signature.cache_info().hits == 0
    assert _safe_clean_targets(case) == ()
    assert _safe_clean_targets_for_signature.cache_info().hits == 1

    result_dir = case / "1"
    result_dir.mkdir()
    assert _safe_clean_targets(case) == (result_dir,)


def test_docker_executable_probe_is_briefly_memoized(tmp_path):
    case = build_case(tmp_path)
    client = FakeDockerClient({"foamRun", "blockMesh", "setFields"})
    service = CaseActionService()
    _docker_executables_cached.cache_clear()

    for _ in range(2):
        service.inspect_case(
            case,
            docker_client=client,
            docker_image="openfoam:test",
            openfoam_version="12",
        )

    assert len(client.containers.calls) == 1
    assert _docker_executables_cached.cache_info().hits == 1

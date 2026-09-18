from dataclasses import replace

import pytest

from backend.physics import (
    Boundary,
    Physics,
    apply_physics,
    load_physics,
    merge_dictionary,
    plan_physics,
)
from tests.integration.test_vtk_runtime import write_foam


def make_case(case):
    mesh = case / "constant/polyMesh"
    write_foam(
        mesh / "points", "vectorField", "4\n(\n(0 0 0)\n(1 0 0)\n(0 1 0)\n(0 0 1)\n)"
    )
    write_foam(
        mesh / "faces", "faceList", "4\n(\n3(0 2 1)\n3(0 1 3)\n3(1 2 3)\n3(2 0 3)\n)"
    )
    write_foam(mesh / "owner", "labelList", "4\n(\n0\n0\n0\n0\n)")
    write_foam(mesh / "neighbour", "labelList", "0\n(\n)")
    write_foam(
        mesh / "boundary",
        "polyBoundaryMesh",
        "3\n(\ninlet { type patch; nFaces 1; startFace 0; }\noutlet { type patch; nFaces 1; startFace 1; }\nwalls { type wall; nFaces 2; startFace 2; }\n)",
    )
    return case


BOUNDARIES = [
    Boundary("inlet", "inlet", (3, 0, 0)),
    Boundary("outlet", "outlet", pressure=2),
    Boundary("walls", "wall"),
]


def test_new_case_requires_mesh_then_accepts_physics(tmp_path):
    from backend.case.manager import CaseManager

    case = tmp_path / "new"
    assert CaseManager.create_case_structure(case)["success"]
    assert load_physics(case, "12")[1] == []
    with pytest.raises(ValueError, match="complete single-region mesh"):
        plan_physics(case, Physics(), [])
    make_case(case)
    apply_physics(plan_physics(case, Physics(), BOUNDARIES))
    assert load_physics(case, "12")[1] == BOUNDARIES


@pytest.mark.parametrize("version", ["12", "13", "v2312", "2412"])
@pytest.mark.parametrize("regime", ["steady", "transient"])
@pytest.mark.parametrize("turbulence", ["laminar", "kOmegaSST"])
def test_physics_roundtrip_and_runtime_flavor(tmp_path, version, regime, turbulence):
    case = make_case(tmp_path / "case")
    model = Physics(
        version=version,
        regime=regime,
        turbulence=turbulence,
        initial_velocity=(1, 2, 3),
    )
    plan = plan_physics(case, model, BOUNDARIES)
    modern = version in ("12", "13")
    app = "foamRun" if modern else "simpleFoam" if regime == "steady" else "pimpleFoam"
    assert f"application {app};" in plan.files["system/controlDict"]
    assert ("constant/physicalProperties" in plan.files) == modern
    assert ("0/omega" in plan.files) == (turbulence == "kOmegaSST")
    assert "type pressureInletOutletVelocity" in plan.files["0/U"]
    apply_physics(plan)
    loaded, boundaries = load_physics(case, version)
    assert loaded == model
    assert boundaries == BOUNDARIES
    # Generated dictionaries can be parsed and merged again without macros.
    apply_physics(plan_physics(case, loaded, boundaries))


def test_preserves_unmanaged_entries_and_backs_up(tmp_path):
    case = make_case(tmp_path / "case")
    apply_physics(plan_physics(case, Physics(), BOUNDARIES))
    control = case / "system/controlDict"
    original = control.read_text() + "// custom setting\nwriteObjects no;\n"
    control.write_text(original)
    plan = plan_physics(case, Physics(nu=2e-5), BOUNDARIES)
    backup = apply_physics(plan)
    assert "writeObjects no;" in control.read_text()
    assert (backup / "system/controlDict").read_text() == original
    assert load_physics(case, "12")[0].nu == 2e-5


@pytest.mark.parametrize(
    "change",
    [
        {"nu": -1},
        {"nu": float("nan")},
        {"delta_t": 2000},
        {"write_interval": 1.2},
        {"write_interval": float("inf")},
        {"version": "11"},
    ],
)
def test_invalid_physics_is_rejected_without_writes(tmp_path, change):
    case = make_case(tmp_path / "case")
    with pytest.raises(ValueError):
        plan_physics(case, replace(Physics(), **change), BOUNDARIES)
    assert not (case / "0/U").exists()


def test_requires_complete_compatible_patch_assignments(tmp_path):
    case = make_case(tmp_path / "case")
    for boundaries in (
        BOUNDARIES[:-1],
        [replace(b, role="inlet") for b in BOUNDARIES],
        [replace(b, role="unassigned") for b in BOUNDARIES],
    ):
        with pytest.raises(ValueError):
            plan_physics(case, Physics(), boundaries)


@pytest.mark.parametrize(
    "relative", ["system/controlDict", "constant/polyMesh/boundary"]
)
def test_stale_review_cannot_write(tmp_path, relative):
    case = make_case(tmp_path / "case")
    apply_physics(plan_physics(case, Physics(), BOUNDARIES))
    plan = plan_physics(case, Physics(nu=4e-5), BOUNDARIES)
    path = case / relative
    path.write_text(path.read_text() + "\n// external change\n")
    with pytest.raises(ValueError, match="changed"):
        apply_physics(plan)
    assert load_physics(case, "12")[0].nu == 1.5e-5


def test_rejects_macros_and_unsupported_solver(tmp_path):
    case = make_case(tmp_path / "case")
    (case / "system").mkdir()
    control = case / "system/controlDict"
    for content in (
        '#include "other"\n',
        "application foamRun; solver fluid;",
        "application rhoSimpleFoam;",
    ):
        control.write_text(content)
        with pytest.raises(ValueError):
            plan_physics(case, Physics(), BOUNDARIES)
        assert control.read_text() == content


def test_merge_preserves_nested_unmanaged_entries():
    result = merge_dictionary(
        "solvers { p { solver GAMG; cacheAgglomeration true; } }\ncustom 4;",
        "solvers { p { solver PCG; } U { solver smoothSolver; } }",
    )
    assert "cacheAgglomeration true;" in result
    assert "solver PCG;" in result
    assert "custom 4;" in result


def test_partial_write_failure_restores_originals(tmp_path, monkeypatch):
    import backend.physics as physics

    case = make_case(tmp_path / "case")
    apply_physics(plan_physics(case, Physics(), BOUNDARIES))
    plan = plan_physics(case, Physics(nu=4e-5), BOUNDARIES)
    original_write = physics._atomic_write
    failed = False

    def fail_once(path, content):
        nonlocal failed
        if path == case / "constant/physicalProperties" and not failed:
            failed = True
            raise OSError("disk full")
        original_write(path, content)

    monkeypatch.setattr(physics, "_atomic_write", fail_once)
    with pytest.raises(OSError, match="disk full"):
        apply_physics(plan)
    assert all(
        (case / name).read_bytes() == data for name, data in plan.originals.items()
    )


def test_nonuniform_field_cannot_be_silently_loaded(tmp_path):
    case = make_case(tmp_path / "case")
    apply_physics(plan_physics(case, Physics(), BOUNDARIES))
    (case / "0/p").write_text("internalField nonuniform List<scalar> 1 (2);")
    with pytest.raises(ValueError, match="Non-uniform"):
        load_physics(case, "12")

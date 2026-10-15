"""Reviewed authoring of single-region, constant-viscosity incompressible cases."""

from __future__ import annotations

import difflib
import hashlib
import math
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from backend.meshing.inspection import inspect_case_mesh


@dataclass(frozen=True)
class Boundary:
    name: str
    role: str
    velocity: tuple[float, float, float] = (0, 0, 0)
    pressure: float = 0


@dataclass(frozen=True)
class Physics:
    version: str = "12"
    regime: str = "steady"
    turbulence: str = "laminar"
    nu: float = 1.5e-5
    initial_velocity: tuple[float, float, float] = (0, 0, 0)
    initial_pressure: float = 0
    k: float = 0.01
    omega: float = 1
    end_time: float = 1000
    delta_t: float = 1
    write_interval: float = 100


@dataclass(frozen=True)
class PhysicsPlan:
    case: Path
    files: dict[str, str]
    originals: dict[str, bytes | None]
    mesh_signature: str
    version: str

    def preview(self) -> list[dict[str, str]]:
        return [
            {
                "path": name,
                "content": content,
                "diff": "".join(
                    difflib.unified_diff(
                        (self.originals[name] or b"").decode("utf-8").splitlines(True),
                        content.splitlines(True),
                        fromfile=f"current/{name}",
                        tofile=f"proposed/{name}",
                    )
                )
                or "No changes",
            }
            for name, content in self.files.items()
        ]


def _family(version: str) -> str:
    if version in ("12", "13"):
        return "foundation"
    if re.fullmatch(r"v?\d{4}", version):
        return "opencfd"
    raise ValueError(
        "Physics authoring supports Foundation 12/13 and OpenCFD vXXXX releases."
    )


def _number(value: float) -> str:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("All physical and numerical values must be finite.")
    return f"{number:.12g}"


def _vector(value: tuple[float, float, float]) -> str:
    if len(value) != 3:
        raise ValueError("Velocity requires three components.")
    return "(" + " ".join(_number(v) for v in value) + ")"


def _header(name: str, kind: str = "dictionary") -> str:
    return f"FoamFile\n{{\n    version 2.0;\n    format ascii;\n    class {kind};\n    object {name};\n}}\n"


def _safe_path(case: Path, relative: str) -> Path:
    target = case / relative
    if target.resolve() != target or not target.resolve().is_relative_to(case):
        raise ValueError(f"Refusing a redirected case path: {relative}")
    if target.exists() and not target.is_file():
        raise ValueError(f"Expected a regular file: {relative}")
    return target


def _mesh_signature(case: Path) -> str:
    inspection = inspect_case_mesh(case)
    if not inspection.available or not inspection.patches:
        raise ValueError("Generate or import a complete single-region mesh first.")
    digest = hashlib.sha256()
    for name in ("points", "faces", "owner", "neighbour", "boundary"):
        path = _safe_path(case, f"constant/polyMesh/{name}")
        stat = path.stat()
        digest.update(f"{name}:{stat.st_size}:{stat.st_mtime_ns}".encode())
    digest.update((case / "constant/polyMesh/boundary").read_bytes())
    return digest.hexdigest()


def _entries(text: str) -> dict[str, tuple[int, int, str]]:
    """Locate dictionary entries; refuse macros rather than reinterpret them."""
    masked = re.sub(r"/\*.*?\*/|//[^\n]*", lambda m: " " * len(m[0]), text, flags=re.S)
    if "#" in masked or "$" in masked:
        raise ValueError(
            "Includes and macro expressions require manual dictionary editing; existing files were preserved."
        )
    result = {}
    position = 0
    while position < len(masked):
        match = re.match(r'\s*("[^"\n]+"|[^\s{};]+)\s*', masked[position:])
        if not match:
            if masked[position:].strip():
                raise ValueError(
                    "Unsupported dictionary syntax; existing files were preserved."
                )
            break
        start = position + match.start(1)
        key = match[1]
        position += match.end()
        value_start = position
        braces = 0
        quote = False
        while position < len(masked):
            char = masked[position]
            if char == '"' and (position == 0 or masked[position - 1] != "\\"):
                quote = not quote
            if not quote:
                braces += (char == "{") - (char == "}")
                if braces < 0:
                    raise ValueError("Unbalanced dictionary braces.")
                if (char == ";" and braces == 0) or (char == "}" and braces == 0):
                    position += 1
                    if position < len(masked) and masked[position] == ";":
                        position += 1
                    break
            position += 1
        else:
            raise ValueError("Unterminated dictionary entry.")
        if key in result:
            raise ValueError(
                f"Duplicate dictionary entry {key}; edit this file manually."
            )
        result[key] = (start, position, text[value_start:position].strip())
    return result


def merge_dictionary(existing: str, generated: str) -> str:
    """Replace managed values recursively while retaining unrelated entries."""
    old = _entries(existing)
    changes = []
    additions = []
    for key, (_, _, value) in _entries(generated).items():
        if key not in old:
            additions.append(f"{key} {value}\n")
            continue
        start, end, previous = old[key]
        if value.startswith("{") and previous.startswith("{"):
            value = (
                "{\n"
                + merge_dictionary(
                    previous[1 : previous.rfind("}")], value[1 : value.rfind("}")]
                )
                + "}\n"
            )
        changes.append((start, end, f"{key} {value}"))
    for start, end, replacement in reversed(sorted(changes)):
        existing = existing[:start] + replacement + existing[end:]
    return existing.rstrip() + "\n" + "".join(additions)


def build_physics_files(
    case: Path, physics: Physics, boundaries: list[Boundary]
) -> dict[str, str]:
    family = _family(physics.version)
    if physics.regime not in ("steady", "transient") or physics.turbulence not in (
        "laminar",
        "kOmegaSST",
    ):
        raise ValueError("Choose steady/transient and laminar/k–ω SST.")
    for value in (
        physics.nu,
        physics.end_time,
        physics.delta_t,
        physics.k,
        physics.omega,
    ):
        _number(value)
        if value <= 0:
            raise ValueError("Viscosity, time controls, k and omega must be positive.")
    _number(physics.write_interval)
    if (
        physics.delta_t > physics.end_time
        or int(physics.write_interval) != physics.write_interval
        or physics.write_interval < 1
    ):
        raise ValueError(
            "Time step must not exceed end time; write interval must be a positive integer."
        )
    patches = {p.name: p for p in inspect_case_mesh(case).patches}
    if len(boundaries) != len(patches) or {b.name for b in boundaries} != set(patches):
        raise ValueError("Assign every mesh patch exactly once.")
    fields: dict[str, list[str]] = {"U": [], "p": []}
    if physics.turbulence == "kOmegaSST":
        fields.update(k=[], omega=[], nut=[])
    if any(b.role == "inlet" for b in boundaries) and not any(
        b.role == "outlet" for b in boundaries
    ):
        raise ValueError("Velocity inlets require at least one pressure outlet.")
    for boundary in boundaries:
        patch = patches[boundary.name]
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.+-]*", patch.name):
            raise ValueError(
                "This mesh has patch names requiring manual dictionary editing."
            )
        allowed = {
            "wall": {"wall", "movingWall"},
            "patch": {"inlet", "outlet", "slip"},
            "empty": {"empty"},
            "symmetryPlane": {"symmetryPlane"},
            "symmetry": {"symmetry"},
        }
        if boundary.role not in allowed.get(patch.patch_type, set()):
            raise ValueError(
                f"{patch.name}: choose a supported role compatible with mesh type {patch.patch_type}."
            )
        velocity = _vector(boundary.velocity)
        pressure = _number(boundary.pressure)
        for field in fields:
            role = boundary.role
            if role in ("empty", "symmetry", "symmetryPlane"):
                entry = f"type {role};"
            elif field == "U":
                entry = {
                    "inlet": f"type fixedValue; value uniform {velocity};",
                    "outlet": "type pressureInletOutletVelocity; value uniform (0 0 0);",
                    "wall": "type noSlip;",
                    "movingWall": f"type fixedValue; value uniform {velocity};",
                    "slip": "type slip;",
                }[role]
            elif field == "p":
                entry = (
                    f"type fixedValue; value uniform {pressure};"
                    if role == "outlet"
                    else "type zeroGradient;"
                )
            else:
                value = _number(
                    {"k": physics.k, "omega": physics.omega, "nut": 0}[field]
                )
                if role in ("wall", "movingWall"):
                    kind = {
                        "k": "kqRWallFunction",
                        "omega": "omegaWallFunction",
                        "nut": "nutkWallFunction",
                    }[field]
                    entry = f"type {kind}; value uniform {value};"
                elif field == "nut":
                    entry = "type calculated; value uniform 0;"
                elif role == "inlet":
                    entry = f"type fixedValue; value uniform {value};"
                elif role == "outlet":
                    entry = f"type inletOutlet; inletValue uniform {value}; value uniform {value};"
                else:
                    entry = "type zeroGradient;"
            fields[field].append(f"    {patch.name}\n    {{ {entry} }}\n")
    files = {}
    initial = {
        "U": _vector(physics.initial_velocity),
        "p": _number(physics.initial_pressure),
        "k": _number(physics.k),
        "omega": _number(physics.omega),
        "nut": "0",
    }
    dimensions = {
        "U": "0 1 -1 0 0 0 0",
        "p": "0 2 -2 0 0 0 0",
        "k": "0 2 -2 0 0 0 0",
        "omega": "0 0 -1 0 0 0 0",
        "nut": "0 2 -1 0 0 0 0",
    }
    for field, entries in fields.items():
        files[f"0/{field}"] = (
            _header(field, "volVectorField" if field == "U" else "volScalarField")
            + f"dimensions [{dimensions[field]}];\ninternalField uniform {initial[field]};\nboundaryField\n{{\n"
            + "".join(entries)
            + "}\n"
        )
    modern = family == "foundation"
    transport = "physicalProperties" if modern else "transportProperties"
    files[f"constant/{transport}"] = (
        _header(transport)
        + ("viscosityModel constant;\n" if modern else "transportModel Newtonian;\n")
        + f"nu [0 2 -1 0 0 0 0] {_number(physics.nu)};\n"
    )
    turbulence_file = "momentumTransport" if modern else "turbulenceProperties"
    model = "model" if modern else "RASModel"
    files[f"constant/{turbulence_file}"] = _header(turbulence_file) + (
        "simulationType laminar;\n"
        if physics.turbulence == "laminar"
        else f"simulationType RAS;\nRAS {{ {model} kOmegaSST; turbulence on; printCoeffs on; }}\n"
    )
    steady = physics.regime == "steady"
    application = "foamRun" if modern else "simpleFoam" if steady else "pimpleFoam"
    files["system/controlDict"] = (
        _header("controlDict")
        + f"application {application};\n"
        + ("solver incompressibleFluid;\n" if modern else "")
        + f"startFrom startTime;\nstartTime 0;\nstopAt endTime;\nendTime {_number(physics.end_time)};\ndeltaT {_number(physics.delta_t)};\nwriteControl timeStep;\nwriteInterval {int(physics.write_interval)};\npurgeWrite 0;\nwriteFormat ascii;\nwritePrecision 8;\nwriteCompression off;\nrunTimeModifiable true;\nadjustTimeStep no;\n"
    )
    files["system/fvSchemes"] = (
        _header("fvSchemes")
        + f"ddtSchemes {{ default {'steadyState' if steady else 'Euler'}; }}\n"
        + """gradSchemes { default Gauss linear; }
divSchemes
{
    default none;
    div(phi,U) bounded Gauss upwind;
    div(phi,k) bounded Gauss upwind;
    div(phi,omega) bounded Gauss upwind;
    div((nuEff*dev2(T(grad(U))))) Gauss linear;
}
laplacianSchemes { default Gauss linear corrected; }
interpolationSchemes { default linear; }
snGradSchemes { default corrected; }
wallDist { method meshWave; }
fluxRequired { default no; p; }
"""
    )
    # Explicit entries avoid macro expansion in files this editor must reload.
    solvers = []
    for field in (
        "p",
        "pFinal",
        "pcorr",
        "pcorrFinal",
        "U",
        "UFinal",
        "k",
        "kFinal",
        "omega",
        "omegaFinal",
    ):
        solver = (
            "solver GAMG; smoother GaussSeidel;"
            if field.startswith("p")
            else "solver smoothSolver; smoother symGaussSeidel;"
        )
        solvers.append(
            f"{field} {{ {solver} tolerance 1e-7; relTol {'0' if field.endswith('Final') else '0.1'}; }}"
        )
    algorithm = "SIMPLE" if steady else "PIMPLE"
    files["system/fvSolution"] = (
        _header("fvSolution")
        + "solvers {\n"
        + "\n".join(solvers)
        + f"\n}}\n{algorithm} {{ nNonOrthogonalCorrectors 1; nCorrectors 2; nOuterCorrectors 1; pRefCell 0; pRefValue 0; }}\nrelaxationFactors {{ fields {{ p 0.3; }} equations {{ U 0.7; k 0.7; omega 0.7; }} }}\n"
    )
    return files


def plan_physics(
    case: Path, physics: Physics, boundaries: list[Boundary]
) -> PhysicsPlan:
    case = case.resolve()
    signature = _mesh_signature(case)
    if (case / "constant/regionProperties").exists():
        raise ValueError("Multi-region cases require manual physics setup.")
    control = _safe_path(case, "system/controlDict")
    if control.exists():
        entries = _entries(control.read_text(encoding="utf-8"))
        application = entries.get("application", (0, 0, ""))[2].strip("; \n")
        solver = entries.get("solver", (0, 0, ""))[2].strip("; \n")
        if application not in ("", "foamRun", "simpleFoam", "pimpleFoam") or (
            application == "foamRun" and solver != "incompressibleFluid"
        ):
            raise ValueError(
                "The existing solver is outside the supported incompressible family. Use a new case for guided physics."
            )
    generated = build_physics_files(case, physics, boundaries)
    originals = {}
    for name, content in generated.items():
        path = _safe_path(case, name)
        original = path.read_bytes() if path.exists() else None
        originals[name] = original
        if original is not None:
            if name.startswith("0/") and re.search(rb"\bnonuniform\b", original):
                raise ValueError("Non-uniform fields require manual setup.")
            generated[name] = merge_dictionary(original.decode("utf-8"), content)
    return PhysicsPlan(case, generated, originals, signature, physics.version)


def load_physics(case: Path, version: str) -> tuple[Physics, list[Boundary]]:
    """Read supported literal settings; drafts remain session-only."""
    family = _family(version)

    def values(name: str) -> dict[str, str]:
        path = _safe_path(case.resolve(), name)
        return (
            {k: v[2] for k, v in _entries(path.read_text(encoding="utf-8")).items()}
            if path.exists()
            else {}
        )

    def scalar(value: str, default: float) -> float:
        if "nonuniform" in value:
            raise ValueError("Non-uniform fields require manual setup.")
        matches = re.findall(r"[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?", value)
        return float(matches[-1]) if matches else default

    def vector(value: str) -> tuple[float, float, float]:
        if "nonuniform" in value:
            raise ValueError("Non-uniform fields require manual setup.")
        match = re.search(r"\(([^()]*)\)", value)
        parts = tuple(float(v) for v in match[1].split()) if match else (0.0, 0.0, 0.0)
        if len(parts) != 3:
            raise ValueError("Non-uniform velocity requires manual setup.")
        return (parts[0], parts[1], parts[2])

    def block(value: str) -> dict[str, str]:
        return (
            {k: v[2] for k, v in _entries(value.strip()[1 : value.rfind("}")]).items()}
            if value.strip().startswith("{")
            else {}
        )

    transport = values(
        "constant/physicalProperties"
        if family == "foundation"
        else "constant/transportProperties"
    )
    turbulence = values(
        "constant/momentumTransport"
        if family == "foundation"
        else "constant/turbulenceProperties"
    )
    control = values("system/controlDict")
    u, p = values("0/U"), values("0/p")
    schemes = values("system/fvSchemes")
    regime = (
        "transient"
        if "Euler" in schemes.get("ddtSchemes", "")
        or "backward" in schemes.get("ddtSchemes", "")
        else "steady"
    )
    ras = (
        "kOmegaSST"
        if "kOmegaSST" in turbulence.get("RAS", "")
        and "RAS" in turbulence.get("simulationType", "")
        else "laminar"
    )
    physics = Physics(
        version=version,
        regime=regime,
        turbulence=ras,
        nu=scalar(transport.get("nu", ""), 1.5e-5),
        initial_velocity=vector(u.get("internalField", "")),
        initial_pressure=scalar(p.get("internalField", ""), 0),
        k=scalar(values("0/k").get("internalField", ""), 0.01)
        if ras == "kOmegaSST"
        else 0.01,
        omega=scalar(values("0/omega").get("internalField", ""), 1)
        if ras == "kOmegaSST"
        else 1,
        end_time=scalar(control.get("endTime", ""), 1000),
        delta_t=scalar(control.get("deltaT", ""), 1),
        write_interval=int(scalar(control.get("writeInterval", ""), 100)),
    )
    ub, pb = block(u.get("boundaryField", "")), block(p.get("boundaryField", ""))
    boundaries = []
    for patch in inspect_case_mesh(case).patches:
        uv, pv = block(ub.get(patch.name, "")), block(pb.get(patch.name, ""))
        kind = uv.get("type", "").strip("; \n")
        role = {
            "wall": "wall",
            "empty": "empty",
            "symmetry": "symmetry",
            "symmetryPlane": "symmetryPlane",
        }.get(patch.patch_type, "unassigned")
        if kind == "fixedValue":
            role = "movingWall" if patch.patch_type == "wall" else "inlet"
        elif kind == "pressureInletOutletVelocity" or (
            kind == "zeroGradient" and pv.get("type", "").strip("; \n") == "fixedValue"
        ):
            role = "outlet"
        elif kind == "slip":
            role = "slip"
        boundaries.append(
            Boundary(
                patch.name,
                role,
                vector(uv.get("value", "")),
                scalar(pv.get("value", ""), 0),
            )
        )
    return physics, boundaries


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".physics-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_physics(plan: PhysicsPlan) -> Path:
    """Apply a reviewed snapshot. Caller holds the FIFO's idle-case lock."""
    if _mesh_signature(plan.case) != plan.mesh_signature:
        raise ValueError("Mesh changed after review. Review physics again.")
    for name, original in plan.originals.items():
        path = _safe_path(plan.case, name)
        if (path.read_bytes() if path.exists() else None) != original:
            raise ValueError(f"{name} changed after review. Review physics again.")
    backup_root = plan.case / "system/.foamtrame-backups"
    if backup_root.resolve() != backup_root:
        raise ValueError("Backup directory must remain inside the case.")
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="physics-", dir=backup_root))
    for name, original in plan.originals.items():
        if original is not None:
            _atomic_write(backup / name, original)
    written = []
    try:
        for name, content in plan.files.items():
            _atomic_write(_safe_path(plan.case, name), content.encode("utf-8"))
            written.append(name)
    except Exception:
        for name in reversed(written):
            original = plan.originals[name]
            path = _safe_path(plan.case, name)
            if original is None:
                path.unlink(missing_ok=True)
            else:
                _atomic_write(path, original)
        raise
    return backup

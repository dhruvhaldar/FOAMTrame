from __future__ import annotations

import re
import shutil
import platform
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


_SAFE_EXECUTABLE = re.compile(r"^[A-Za-z][A-Za-z0-9_.+-]{0,63}$")
_TIME_DIRECTORY = re.compile(
    r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$"
)
_PROCESSOR_DIRECTORY = re.compile(r"^processor\d+$")


@dataclass(frozen=True)
class CaseAction:
    id: str
    label: str
    command: str | None
    available: bool
    reason: str
    category: str
    destructive: bool = False
    preferred: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CaseInspection:
    case_path: Path | None
    actions: dict[str, CaseAction]
    guided_actions: tuple[str, ...]
    clean_targets: tuple[Path, ...]
    solver_application: str
    solver_module: str
    docker_checked: bool
    summary: str

    def action_map(self) -> dict[str, dict[str, Any]]:
        return {key: action.to_dict() for key, action in self.actions.items()}

    def guided_labels(self) -> list[str]:
        return [self.actions[action_id].label for action_id in self.guided_actions]

    def clean_target_labels(self) -> list[str]:
        if self.case_path is None:
            return []
        labels = []
        for target in self.clean_targets:
            try:
                labels.append(target.relative_to(self.case_path).as_posix())
            except ValueError:
                continue
        return labels


def _strip_foam_comments(content: str) -> str:
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    return re.sub(r"//.*?$", "", content, flags=re.MULTILINE)


def _dictionary_word(content: str, key: str) -> str:
    match = re.search(rf"\b{re.escape(key)}\s+([A-Za-z][A-Za-z0-9_.+-]*)\s*;", content)
    return match.group(1) if match else ""


def _read_solver(case_path: Path) -> tuple[str, str]:
    control_dict = case_path / "system" / "controlDict"
    if not control_dict.is_file():
        return "", ""
    try:
        content = _strip_foam_comments(
            control_dict.read_text(encoding="utf-8", errors="replace")
        )
    except OSError:
        return "", ""
    return _dictionary_word(content, "application"), _dictionary_word(content, "solver")


def _is_result_time_directory(path: Path) -> bool:
    if not path.is_dir() or not _TIME_DIRECTORY.fullmatch(path.name):
        return False
    try:
        return float(path.name) > 0
    except ValueError:
        return False


def _safe_clean_targets(case_path: Path) -> tuple[Path, ...]:
    targets: list[Path] = []
    try:
        entries = list(case_path.iterdir())
    except OSError:
        return ()
    for entry in entries:
        name = entry.name
        if (
            _is_result_time_directory(entry)
            or (entry.is_dir() and _PROCESSOR_DIRECTORY.fullmatch(name))
            or (entry.is_dir() and name in {"postProcessing", "VTK"})
            or (entry.is_file() and name.startswith("log."))
        ):
            targets.append(entry)
    return tuple(sorted(targets, key=lambda path: path.name.lower()))


def _docker_executables(
    client,
    docker_image: str,
    openfoam_version: str,
    executable_names: Iterable[str],
) -> tuple[bool, set[str], str]:
    names = sorted({name for name in executable_names if _SAFE_EXECUTABLE.fullmatch(name)})
    if client is None:
        return False, set(), "Docker daemon is unavailable"
    if not names:
        return True, set(), ""
    shell_script = r'''
requested="$1"
shift
bashrc="/opt/openfoam${requested}/etc/bashrc"
if [ ! -f "$bashrc" ]; then
    bashrc="$(find /opt -maxdepth 4 -type f -path '*/etc/bashrc' 2>/dev/null | head -n 1)"
fi
[ -n "$bashrc" ] && [ -f "$bashrc" ] || exit 2
source "$bashrc" >/dev/null 2>&1 || exit 3
for executable in "$@"; do
    if command -v "$executable" >/dev/null 2>&1; then
        printf '%s\n' "$executable"
    fi
done
'''
    try:
        output = client.containers.run(
            docker_image,
            [
                "bash",
                "-c",
                shell_script,
                "inspect_case_commands",
                str(openfoam_version),
                *names,
            ],
            remove=True,
            stdout=True,
            stderr=False,
            network_disabled=True,
        )
        found = {
            line.strip()
            for line in output.decode("utf-8", errors="replace").splitlines()
            if _SAFE_EXECUTABLE.fullmatch(line.strip())
        }
        return True, found, ""
    except Exception:
        return False, set(), "Docker image commands could not be inspected"


def _unavailable_action(
    action_id: str,
    label: str,
    reason: str,
    category: str,
    *,
    destructive: bool = False,
) -> CaseAction:
    return CaseAction(
        id=action_id,
        label=label,
        command=None,
        available=False,
        reason=reason,
        category=category,
        destructive=destructive,
    )


class CaseActionService:
    """Capability and action boundary shared by UI and future automation clients."""

    ACTION_ORDER = (
        "allrun",
        "allclean",
        "safe_clean",
        "surfaceFeatureExtract",
        "blockMesh",
        "snappyHexMesh",
        "topoSet",
        "setFields",
        "solver",
        "decomposePar",
        "reconstructPar",
        "foamToVTK",
    )
    GUIDED_ORDER = (
        "surfaceFeatureExtract",
        "blockMesh",
        "snappyHexMesh",
        "topoSet",
        "setFields",
        "solver",
    )

    def inspect_case(
        self,
        case_path: str | Path | None,
        *,
        docker_client=None,
        docker_image: str = "",
        openfoam_version: str = "",
    ) -> CaseInspection:
        path = Path(case_path).resolve() if case_path else None
        if path is None or not path.is_dir():
            reason = "No valid active case selected"
            actions = {
                action_id: _unavailable_action(
                    action_id,
                    action_id,
                    reason,
                    "case",
                    destructive=action_id in {"allclean", "safe_clean"},
                )
                for action_id in self.ACTION_ORDER
            }
            return CaseInspection(
                path,
                actions,
                (),
                (),
                "",
                "",
                False,
                reason,
            )

        application, solver_module = _read_solver(path)
        solver_command = application or ("foamRun" if solver_module else "")
        if solver_command and not _SAFE_EXECUTABLE.fullmatch(solver_command):
            solver_command = ""

        requirements = {
            "surfaceFeatureExtract": any(
                (path / "system" / name).is_file()
                for name in ("surfaceFeaturesDict", "surfaceFeatureExtractDict")
            ),
            "blockMesh": (path / "system" / "blockMeshDict").is_file(),
            "snappyHexMesh": (path / "system" / "snappyHexMeshDict").is_file(),
            "topoSet": (path / "system" / "topoSetDict").is_file(),
            "setFields": (path / "system" / "setFieldsDict").is_file(),
            "decomposePar": (path / "system" / "decomposeParDict").is_file(),
            "reconstructPar": any(
                entry.is_dir() and _PROCESSOR_DIRECTORY.fullmatch(entry.name)
                for entry in path.iterdir()
            ),
            "foamToVTK": any(_is_result_time_directory(entry) for entry in path.iterdir()),
        }
        executable_names = {
            action_id for action_id, required in requirements.items() if required
        }
        allrun_exists = (path / "Allrun").is_file()
        allclean_exists = (path / "Allclean").is_file()
        if allrun_exists or allclean_exists:
            executable_names.add("bash")
        if solver_command:
            executable_names.add(solver_command)
        docker_checked, available_executables, docker_reason = _docker_executables(
            docker_client,
            docker_image,
            openfoam_version,
            executable_names,
        )

        def executable_action(
            action_id: str,
            label: str,
            required: bool,
            missing_reason: str,
            category: str,
            *,
            command: str | None = None,
            detail: str = "",
        ) -> CaseAction:
            executable = command or action_id
            if not required:
                return _unavailable_action(action_id, label, missing_reason, category)
            if not docker_checked:
                return _unavailable_action(action_id, label, docker_reason, category)
            if executable not in available_executables:
                return _unavailable_action(
                    action_id,
                    label,
                    f"{executable} is not available in the configured Docker image",
                    category,
                )
            return CaseAction(
                action_id,
                label,
                executable,
                True,
                "Ready",
                category,
                detail=detail,
            )

        actions: dict[str, CaseAction] = {}
        scripts_supported = docker_checked and "bash" in available_executables
        script_reason = (
            docker_reason
            if not docker_checked
            else "bash is not available in the configured Docker image"
        )
        actions["allrun"] = CaseAction(
            "allrun",
            "Allrun",
            "./Allrun" if allrun_exists and scripts_supported else None,
            allrun_exists and scripts_supported,
            "Ready — preferred case workflow"
            if allrun_exists and scripts_supported
            else (script_reason if allrun_exists else "No Allrun script supplied"),
            "workflow",
            preferred=allrun_exists,
        )
        actions["allclean"] = CaseAction(
            "allclean",
            "Allclean",
            "./Allclean" if allclean_exists and scripts_supported else None,
            allclean_exists and scripts_supported,
            "Requires confirmation"
            if allclean_exists and scripts_supported
            else (script_reason if allclean_exists else "No Allclean script supplied"),
            "cleanup",
            destructive=True,
        )

        clean_targets = _safe_clean_targets(path)
        actions["safe_clean"] = CaseAction(
            "safe_clean",
            "Safe Clean Generated Outputs",
            None,
            bool(clean_targets),
            f"Review {len(clean_targets)} generated path(s) before removal"
            if clean_targets
            else "No generated outputs detected",
            "cleanup",
            destructive=True,
            detail="Does not remove the initial 0 directory or constant/polyMesh.",
        )

        missing_reasons = {
            "surfaceFeatureExtract": "No surfaceFeaturesDict or surfaceFeatureExtractDict",
            "blockMesh": "Missing system/blockMeshDict",
            "snappyHexMesh": "Missing system/snappyHexMeshDict",
            "topoSet": "Missing system/topoSetDict",
            "setFields": "Missing system/setFieldsDict",
            "decomposePar": "Missing system/decomposeParDict",
            "reconstructPar": "No decomposed processor directories",
            "foamToVTK": "No result time directories",
        }
        categories = {
            "surfaceFeatureExtract": "preprocess",
            "blockMesh": "mesh",
            "snappyHexMesh": "mesh",
            "topoSet": "preprocess",
            "setFields": "preprocess",
            "decomposePar": "parallel",
            "reconstructPar": "parallel",
            "foamToVTK": "postprocess",
        }
        for action_id in requirements:
            actions[action_id] = executable_action(
                action_id,
                action_id,
                requirements[action_id],
                missing_reasons[action_id],
                categories[action_id],
            )

        if not (path / "system" / "controlDict").is_file():
            actions["solver"] = _unavailable_action(
                "solver", "Solver", "Missing system/controlDict", "solver"
            )
        elif not solver_command:
            actions["solver"] = _unavailable_action(
                "solver",
                "Solver",
                "No valid application or solver entry in system/controlDict",
                "solver",
            )
        else:
            label = solver_command
            detail = ""
            if solver_command in {"foamRun", "foamMultiRun"} and solver_module:
                label = f"{solver_command} — {solver_module}"
                detail = f"Solver module: {solver_module}"
            actions["solver"] = executable_action(
                "solver",
                label,
                True,
                "Solver is not configured",
                "solver",
                command=solver_command,
                detail=detail,
            )

        guided_actions = tuple(
            action_id
            for action_id in self.GUIDED_ORDER
            if actions[action_id].available
        )
        available_count = sum(action.available for action in actions.values())
        summary = (
            f"Detected {available_count} available action(s)"
            + (f" · solver: {actions['solver'].label}" if actions["solver"].available else "")
        )
        return CaseInspection(
            path,
            actions,
            guided_actions,
            clean_targets,
            application,
            solver_module,
            docker_checked,
            summary,
        )

    def resolve_actions(
        self,
        inspection: CaseInspection,
        action_ids: Iterable[str],
    ) -> list[CaseAction]:
        resolved: list[CaseAction] = []
        for action_id in action_ids:
            action = inspection.actions.get(action_id)
            if action is None:
                raise ValueError(f"Unknown case action: {action_id}")
            if not action.available:
                raise ValueError(f"{action.label} is unavailable: {action.reason}")
            resolved.append(action)
        return resolved

    def start_run(
        self,
        inspection: CaseInspection,
        action_ids: Iterable[str],
        *,
        docker_client,
        docker_image: str,
        openfoam_version: str,
        environment: dict[str, str] | None = None,
    ):
        """Launch a validated action plan and return ``(container, actions)``.

        Callers submit fixed action IDs, never shell text. This is the shared
        execution boundary for the UI and future automation/chatbot tools.
        """
        actions = self.resolve_actions(inspection, action_ids)
        if inspection.case_path is None:
            raise ValueError("No valid active case selected")
        if docker_client is None:
            raise RuntimeError("Docker daemon is unavailable")
        commands = [action.command for action in actions if action.command]
        if not commands:
            raise ValueError("The action plan contains no executable commands")

        case_path = inspection.case_path.resolve()
        host_path = (
            case_path.as_posix() if platform.system() == "Windows" else str(case_path)
        )
        container_case_path = "/tmp/FOAM_Run"
        bashrc = f"/opt/openfoam{openfoam_version}/etc/bashrc"
        shell_script = r'''
source "$1" && cd "$2" || exit $?
shift 2
for command in "$@"; do
    printf '\n[FOAMTrame] >>> %s\n' "$command"
    case "$command" in
        ./*) bash "$command" || exit $? ;;
        *) "$command" || exit $? ;;
    esac
done
'''
        container = docker_client.containers.run(
            docker_image,
            [
                "bash",
                "-c",
                shell_script,
                "run_case_actions",
                bashrc,
                container_case_path,
                *commands,
            ],
            detach=True,
            tty=False,
            volumes={host_path: {"bind": container_case_path, "mode": "rw"}},
            working_dir=container_case_path,
            environment=environment or {},
        )
        return container, actions

    def clean_case(self, inspection: CaseInspection) -> list[str]:
        case_path = inspection.case_path
        if case_path is None:
            raise ValueError("No valid active case selected")
        case_root = case_path.resolve()
        removed: list[str] = []
        # Use the exact preview snapshot; do not re-expand patterns at deletion time.
        for target in inspection.clean_targets:
            target_path = Path(target)
            try:
                target_path.absolute().relative_to(case_root)
            except ValueError as exc:
                raise ValueError("Clean target escaped the active case") from exc
            if not target_path.exists() and not target_path.is_symlink():
                continue
            relative = target_path.relative_to(case_root).as_posix()
            if target_path.is_symlink() or target_path.is_file():
                target_path.unlink()
            elif target_path.is_dir():
                shutil.rmtree(target_path)
            removed.append(relative)
        return removed


case_action_service = CaseActionService()

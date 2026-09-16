"""Derive meshing progress from the authoritative simulation queue."""

from pathlib import Path

MESH_ACTIONS = {"blockMesh", "snappyHexMesh", "snappyHexMeshOverwrite"}


def meshing_progress(
    case_path: Path | None,
    queue: list[dict],
    history: list[dict],
    previous_job_id: int | None = None,
) -> dict:
    result = {
        "busy": False,
        "failed": False,
        "phase": "",
        "message": "",
        "job_id": previous_job_id,
    }
    if case_path is None:
        return result
    for job in queue:
        if job.get("case_path") == str(case_path) and MESH_ACTIONS.intersection(
            job.get("action_ids", [])
        ):
            queued = job.get("status") == "Queued"
            return {
                "busy": True,
                "failed": False,
                "phase": "Meshing queued" if queued else "Generating mesh",
                "message": (
                    "Waiting for the current job to finish. Meshing will start automatically."
                    if queued
                    else "Building the mesh. The viewer will update when meshing finishes."
                ),
                "job_id": job["id"],
            }
    entry = next((item for item in history if item.get("id") == previous_job_id), {})
    status = entry.get("status")
    if status in {"Failed", "Cancelled", "Skipped"}:
        result.update(
            failed=True,
            phase=f"Meshing {status.lower()}",
            message="Open Run/Log to review the outcome before generating another mesh.",
        )
    return result

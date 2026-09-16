from pathlib import Path

import pytest

from backend.meshing.progress import meshing_progress


def job(case: Path, status: str = "Queued") -> dict:
    return {
        "id": 42,
        "case_path": str(case),
        "status": status,
        "action_ids": ["blockMesh", "snappyHexMeshOverwrite"],
    }


@pytest.mark.parametrize(
    "status,phase", [("Queued", "Meshing queued"), ("Running", "Generating mesh")]
)
def test_meshing_waits_for_its_own_job(tmp_path, status, phase):
    result = meshing_progress(tmp_path, [job(tmp_path, status)], [])
    assert result["busy"]
    assert result["phase"] == phase
    assert result["job_id"] == 42


def test_other_cases_and_quality_checks_do_not_block_viewer(tmp_path):
    other = job(tmp_path / "other")
    quality = {**job(tmp_path), "action_ids": ["checkMesh"]}
    assert not meshing_progress(tmp_path, [other, quality], [])["busy"]
    assert not meshing_progress(None, [job(tmp_path)], [])["busy"]


@pytest.mark.parametrize("status", ["Failed", "Cancelled", "Skipped"])
def test_unsuccessful_job_leaves_loading_and_shows_outcome(tmp_path, status):
    result = meshing_progress(tmp_path, [], [{"id": 42, "status": status}], 42)
    assert not result["busy"]
    assert result["failed"]
    assert result["phase"] == f"Meshing {status.lower()}"


def test_complete_job_releases_viewer_and_ignores_other_failures(tmp_path):
    history = [{"id": 99, "status": "Failed"}, {"id": 42, "status": "Completed"}]
    result = meshing_progress(tmp_path, [], history, 42)
    assert not result["busy"]
    assert not result["failed"]


def test_queue_remains_authoritative_until_executor_releases_job(tmp_path):
    history = [{"id": 42, "status": "Completed"}]
    assert meshing_progress(tmp_path, [job(tmp_path, "Running")], history, 42)["busy"]

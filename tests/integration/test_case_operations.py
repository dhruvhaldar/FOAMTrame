from pathlib import Path

import pytest

from backend.case.operations import case_destination, manage_case


def make_case(root: Path) -> Path:
    case = root / "original"
    (case / "system").mkdir(parents=True)
    (case / "constant").mkdir()
    (case / "system/controlDict").write_text(
        "application simpleFoam;", encoding="utf-8"
    )
    (case / "100").mkdir()
    (case / "100/U").write_bytes(b"results")
    return case


def test_copy_rename_delete_preserve_case_data(tmp_path):
    source = make_case(tmp_path)
    copy = manage_case(tmp_path, source.name, "copy", "duplicate")
    assert (copy / "100/U").read_bytes() == b"results"
    (copy / "100/U").write_bytes(b"independent")
    assert (source / "100/U").read_bytes() == b"results"
    renamed = manage_case(tmp_path, copy.name, "rename", "renamed")
    assert not copy.exists()
    trashed = manage_case(tmp_path, renamed.name, "delete")
    assert not renamed.exists()
    assert trashed.parent == tmp_path / ".foamtrame-trash"
    assert (trashed / "100/U").read_bytes() == b"independent"
    assert source.exists()
    assert not list(tmp_path.glob(".foamtrame-copy-*"))


@pytest.mark.parametrize(
    "name", ["../outside", "", ".", "..", "a/b", "a\\b", "CON", "x.", ".hidden"]
)
def test_invalid_destination_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        case_destination(tmp_path, name)


def test_refuses_overwrite_and_workspace_root(tmp_path):
    source = make_case(tmp_path)
    for action in ("copy", "rename"):
        with pytest.raises(ValueError):
            manage_case(tmp_path, source.name, action, source.name)
    with pytest.raises(ValueError):
        manage_case(tmp_path, "..", "delete")
    assert source.exists()


def test_failed_copy_is_not_published(tmp_path, monkeypatch):
    import backend.case.operations as operations

    source = make_case(tmp_path)

    def fail(*args, **kwargs):
        raise OSError("copy failed")

    monkeypatch.setattr(operations.shutil, "copytree", fail)
    with pytest.raises(OSError, match="copy failed"):
        manage_case(tmp_path, source.name, "copy", "duplicate")
    assert not (tmp_path / "duplicate").exists()
    assert not list(tmp_path.glob(".foamtrame-copy-*"))
    assert source.exists()


def test_case_symlink_cannot_escape_workspace(tmp_path):
    source = make_case(tmp_path)
    link = tmp_path / "linked"
    try:
        link.symlink_to(source, target_is_directory=True)
    except OSError:
        pytest.skip()
    with pytest.raises(ValueError):
        manage_case(tmp_path, link.name, "delete")
    assert source.exists()

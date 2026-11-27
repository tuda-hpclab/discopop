# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The workspace: changes in the copy are mapped back to the project's files, and their patch names those files."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from discopop_library.SuggestionCheck.conftest import APPROVED_SOURCE, SOURCE, Project
from discopop_library.SuggestionCheck.facts import SourceFiles
from discopop_library.SuggestionCheck.workspace import Workspace, patch_of


def _change_and_patch(project_root: Path, files: SourceFiles, tmp_path: Path) -> str:
    workspace = Workspace(str(project_root), files)
    try:
        assert os.path.realpath(workspace.root) != os.path.realpath(project_root)
        (Path(workspace.root) / "code.cpp").write_text(APPROVED_SOURCE)
        changes = workspace.changes()
    finally:
        workspace.remove()
    assert changes.unmapped == []
    assert list(changes.mapped) == [1]
    patch = patch_of(changes.mapped, files, 5)
    return patch.entries[1].text


def _applies(patch_text: str, target: Path, tmp_path: Path) -> None:
    patch_file = tmp_path / "1.patch"
    patch_file.write_text(patch_text)
    result = subprocess.run(
        ["patch", "--batch", "--forward", target.as_posix(), patch_file.as_posix()], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert target.read_text() == APPROVED_SOURCE


def test_the_patch_names_the_project_file_not_the_copy(project: Project, tmp_path: Path) -> None:
    text = _change_and_patch(project.root, project.files, tmp_path)
    source = (project.root / "code.cpp").as_posix()
    assert text.startswith("--- " + source + "\t")
    assert "+++ " + source + ".discopop_patch_generator.temp\t" in text
    assert "discopop_suggestion_check_" not in text
    # nothing was written into the project
    assert sorted(p.name for p in project.root.iterdir()) == ["README", "code.cpp"]
    _applies(text, project.root / "code.cpp", tmp_path)


def test_a_project_root_reached_through_a_symbolic_link(project: Project, tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(project.root, target_is_directory=True)
    # the file mapping holds the real path, the project root is given through the link
    _applies(_change_and_patch(link, project.files, tmp_path), project.root / "code.cpp", tmp_path)


def test_a_file_mapping_recorded_through_a_symbolic_link(project: Project, tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(project.root, target_is_directory=True)
    files = SourceFiles({1: link / "code.cpp"}, str(link))
    _applies(_change_and_patch(project.root, files, tmp_path), project.root / "code.cpp", tmp_path)


def test_a_file_outside_the_project_has_no_place_in_the_copy(project: Project, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere.cpp"
    elsewhere.write_text(SOURCE)
    workspace = Workspace(str(project.root), SourceFiles({1: elsewhere}, str(project.root)))
    try:
        assert workspace.relative(elsewhere) is None
        # a sibling directory whose name starts with the project's is outside it, too
        sibling = tmp_path / "project2" / "code.cpp"
        assert workspace.relative(sibling) is None
        with pytest.raises(ValueError):
            workspace.write({1: APPROVED_SOURCE})
    finally:
        workspace.remove()


def test_the_project_stays_untouched_even_if_it_is_read_only(project: Project, tmp_path: Path) -> None:
    project.root.chmod(0o555)
    try:
        if os.access(project.root, os.W_OK):
            pytest.skip("the directory stays writable (running as root?)")
        text = _change_and_patch(project.root, project.files, tmp_path)
    finally:
        project.root.chmod(0o755)
    _applies(text, project.root / "code.cpp", tmp_path)


def test_ignored_files_are_not_copied_but_source_files_always_are(project: Project, tmp_path: Path) -> None:
    (project.root / "dp_build").mkdir()
    (project.root / "dp_build" / "huge.o").write_text("object code")
    (project.root / "notes.log").write_text("log")
    # code.cpp has a file id: an ignore pattern covering it must not take it away from the agent
    workspace = Workspace(str(project.root), project.files, ignore=["dp_build/", "*.log", "*.cpp"])
    try:
        copied = sorted(
            os.path.relpath(os.path.join(d, n), workspace.root) for d, _, ns in os.walk(workspace.root) for n in ns
        )
        assert copied == ["README", "code.cpp"]
        assert workspace.changes().unmapped == []
    finally:
        workspace.remove()


def test_a_mapped_source_file_git_ignores_is_copied(project: Project, tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(project.root)], check=True)
    (project.root / ".gitignore").write_text("generated/\n")
    (project.root / "generated").mkdir()
    generated = project.root / "generated" / "table.h"
    generated.write_text("int table[4];\n")
    (project.root / "generated" / "unmapped.h").write_text("// no file id\n")
    subprocess.run(["git", "-C", str(project.root), "add", "-A"], check=True)
    files = SourceFiles({1: project.root / "code.cpp", 2: generated}, str(project.root))
    workspace = Workspace(str(project.root), files)
    try:
        copy = Path(workspace.root)
        assert (copy / "generated" / "table.h").read_text() == "int table[4];\n"
        assert not (copy / "generated" / "unmapped.h").exists()
        (copy / "generated" / "table.h").write_text("thread_local int table[4];\n")
        changes = workspace.changes()
    finally:
        workspace.remove()
    assert (changes.mapped, changes.unmapped) == ({2: "thread_local int table[4];\n"}, [])


def test_a_failed_copy_leaves_no_workspace_behind(
    project: Project, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("shutil.copy2", fail)
    with pytest.raises(OSError, match="disk full"):
        Workspace(str(project.root), project.files)
    assert list(scratch.iterdir()) == []

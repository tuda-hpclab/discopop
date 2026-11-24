# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import shutil
import time
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

from discopop_library.ProjectManager.configurations.copy_exclusions import CopyExclusions
from discopop_library.ProjectManager.configurations.tree_sync import (
    CLEAN,
    SYNCING,
    SyncResult,
    TreeState,
    clean_outputs,
    copy_set,
    read_tree_state,
    set_tree_state,
    sync_tree,
    tree_state_path_of,
    write_tree_state,
)

OLD = 1_000_000_000  # a modification time long before any compilation


def _write(path: Path, text: str, mtime: Optional[int] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _first_copy(project: Path, tree: Path) -> Tuple[Dict[str, str], SyncResult]:
    """The tree as a build copies it, then synced once (as the first build of a kept tree records it)."""
    files = copy_set(CopyExclusions(str(project)))
    result = sync_tree(str(tree), files, {})
    return files, result


def _sync(project: Path, tree: Path, previous: SyncResult, overrides: Optional[Dict[str, str]] = None) -> SyncResult:
    return sync_tree(str(tree), copy_set(CopyExclusions(str(project))), previous.synced, overrides)


def test_a_changed_file_is_written_with_a_new_modification_time(tmp_path: Path) -> None:
    project, tree = tmp_path / "p", tmp_path / "t"
    _write(project / "a.c", "int a;\n", OLD)
    _write(project / "b.c", "int b;\n", OLD)
    _, first = _first_copy(project, tree)
    assert first.written == ["a.c", "b.c"]
    _write(tree / "a.o", "object")  # output of the compilation
    b_written = os.stat(tree / "b.c").st_mtime_ns

    # the new content carries an OLD modification time (git checkout, cp -p): it must still look newer
    _write(project / "a.c", "int a = 1;\n", OLD)
    before = time.time() - 1
    second = _sync(project, tree, first)

    assert second.written == ["a.c"] and second.deleted == []
    assert (tree / "a.c").read_text() == "int a = 1;\n"
    assert os.path.getmtime(tree / "a.c") >= before
    assert os.stat(tree / "b.c").st_mtime_ns == b_written  # untouched
    assert (tree / "a.o").exists()


def test_a_touched_file_with_the_same_content_is_not_written(tmp_path: Path) -> None:
    project, tree = tmp_path / "p", tmp_path / "t"
    _write(project / "a.c", "int a;\n", OLD)
    _, first = _first_copy(project, tree)
    os.utime(project / "a.c", None)

    second = _sync(project, tree, first)

    assert not second.changed
    assert second.synced != first.synced  # the new signature is recorded, so the next sync does not compare again


def test_only_files_the_sync_wrote_are_deleted(tmp_path: Path) -> None:
    project, tree = tmp_path / "p", tmp_path / "t"
    _write(project / "a.c", "a")
    _write(project / "gone.c", "g")
    _, first = _first_copy(project, tree)
    _write(tree / "prog", "binary")
    (project / "gone.c").unlink()

    second = _sync(project, tree, first)

    assert second.deleted == ["gone.c"]
    assert not (tree / "gone.c").exists() and (tree / "prog").exists() and (tree / "a.c").exists()


def test_patched_files_replace_and_restore_the_originals(tmp_path: Path) -> None:
    project, tree, scratch = tmp_path / "p", tmp_path / "t", tmp_path / "s"
    _write(project / "a.c", "original a\n", OLD)
    _write(project / "b.c", "original b\n", OLD)
    _write(scratch / "a.c", "patched a\n")
    _write(scratch / "b.c", "patched b\n")
    _, first = _first_copy(project, tree)

    # A: suggestion in a.c
    with_a = _sync(project, tree, first, {"a.c": str(scratch / "a.c")})
    assert with_a.written == ["a.c"] and (tree / "a.c").read_text() == "patched a\n"
    # B: suggestion in b.c only: a.c gets its original content back although the project's a.c did not change
    with_b = _sync(project, tree, with_a, {"b.c": str(scratch / "b.c")})
    assert with_b.written == ["a.c", "b.c"]
    assert (tree / "a.c").read_text() == "original a\n" and (tree / "b.c").read_text() == "patched b\n"
    # A again
    again = _sync(project, tree, with_b, {"a.c": str(scratch / "a.c")})
    assert again.written == ["a.c", "b.c"]
    assert (tree / "a.c").read_text() == "patched a\n" and (tree / "b.c").read_text() == "original b\n"
    # the same set once more: nothing to do
    assert not _sync(project, tree, again, {"a.c": str(scratch / "a.c")}).changed


def test_a_file_that_became_a_directory_and_back(tmp_path: Path) -> None:
    project, tree = tmp_path / "p", tmp_path / "t"
    _write(project / "x", "file")
    _, first = _first_copy(project, tree)
    (project / "x").unlink()
    _write(project / "x" / "y.c", "y")

    second = _sync(project, tree, first)
    assert (tree / "x" / "y.c").read_text() == "y"

    shutil.rmtree(project / "x")
    _write(project / "x", "file again")
    third = _sync(project, tree, second)
    assert (tree / "x").read_text() == "file again" and third.written == ["x"]


def test_a_file_removed_from_the_tree_is_written_again(tmp_path: Path) -> None:
    project, tree = tmp_path / "p", tmp_path / "t"
    _write(project / "a.c", "a")
    _, first = _first_copy(project, tree)
    (tree / "a.c").unlink()  # a clean target of the build system

    assert _sync(project, tree, first).written == ["a.c"]


def test_the_copy_set_is_what_a_copy_holds(tmp_path: Path) -> None:
    project = tmp_path / "p"
    _write(project / "src" / "a.c", "a")
    _write(project / ".discopop" / "FileMapping.txt", "")
    _write(project / "build" / "CMakeCache.txt", "CMAKE_HOME_DIRECTORY:INTERNAL=" + str(project) + "\n")
    _write(project / "data" / "big.bin", "")
    os.symlink(tmp_path / "nowhere", project / "dangling")
    _write(tmp_path / "shared" / "s.h", "s")
    os.symlink(tmp_path / "shared", project / "linked")

    files = copy_set(CopyExclusions(str(project), listed=["data"]))

    assert set(files) == {"src/a.c", "linked/s.h"}
    shutil.copytree(
        project,
        tmp_path / "copy",
        ignore=CopyExclusions(str(project), listed=["data"]).ignore(),
        ignore_dangling_symlinks=True,
    )
    copied = {str(p.relative_to(tmp_path / "copy")) for p in (tmp_path / "copy").rglob("*") if p.is_file()}
    assert copied - {".discopop/FileMapping.txt"} == set(files)


def test_the_tree_state_is_kept_apart(tmp_path: Path) -> None:
    project_dir = str(tmp_path / "project")
    assert read_tree_state(project_dir, "cfg_par") is None
    write_tree_state(project_dir, "cfg_par", TreeState({"a.c": "1\x002"}, ["3"], SYNCING))
    set_tree_state(project_dir, "cfg_par", CLEAN)
    state = read_tree_state(project_dir, "cfg_par")
    assert state == TreeState({"a.c": "1\x002"}, ["3"], CLEAN)
    Path(tree_state_path_of(project_dir, "cfg_par")).write_text("{broken")
    assert read_tree_state(project_dir, "cfg_par") is None


def test_a_file_changed_in_the_tree_is_written_again(tmp_path: Path) -> None:
    project, tree = tmp_path / "p", tmp_path / "t"
    _write(project / "config.h", "original\n")
    _, first = _first_copy(project, tree)
    _write(tree / "config.h", "generated by a configure step\n")

    second = _sync(project, tree, first)

    assert second.written == ["config.h"] and (tree / "config.h").read_text() == "original\n"
    assert not _sync(project, tree, second).changed


def test_cleaning_leaves_the_files_of_the_project_and_dot_discopop(tmp_path: Path) -> None:
    project, tree = tmp_path / "p", tmp_path / "t"
    _write(project / "src" / "a.c", "a")
    (project / "empty").mkdir()
    _, first = _first_copy(project, tree)
    (tree / "empty").mkdir()
    _write(tree / "build" / "CMakeFiles" / "a.o", "o")
    _write(tree / "src" / "a.o", "o")
    _write(tree / "prog", "binary")
    _write(tree / ".discopop" / "FileMapping.txt", "1\ta.c\n")

    deleted = clean_outputs(str(tree), first.synced, str(project))

    assert sorted(deleted) == ["build/CMakeFiles/a.o", "prog", "src/a.o"]
    assert {str(p.relative_to(tree)) for p in tree.rglob("*")} == {
        "src",
        "src/a.c",
        "empty",
        ".discopop",
        ".discopop/FileMapping.txt",
    }


def test_empty_directories_permissions_and_times_of_a_fresh_fill(tmp_path: Path) -> None:
    project, tree = tmp_path / "p", tmp_path / "t"
    _write(project / "configure", "#!/bin/sh\n", OLD)
    os.chmod(project / "configure", 0o755)
    (project / "build").mkdir()  # an empty directory the scripts expect
    directories: Set[str] = set()
    files = copy_set(CopyExclusions(str(project)), directories)
    assert directories == {"build"}

    first = sync_tree(str(tree), files, {}, None, directories, preserve_times=True)

    assert (tree / "build").is_dir()
    assert os.stat(tree / "configure").st_mtime == OLD  # like a copy: generated files keep their order
    assert os.stat(tree / "configure").st_mode & 0o777 == 0o755
    assert clean_outputs(str(tree), first.synced, str(project), directories) == [] and (tree / "build").is_dir()

    os.chmod(project / "configure", 0o644)  # neither size nor modification time change
    second = sync_tree(str(tree), copy_set(CopyExclusions(str(project))), first.synced, None, directories)
    assert os.stat(tree / "configure").st_mode & 0o777 == 0o644
    assert second.written == []  # same content: not written, so not compiled again


def test_outputs_of_a_build_in_the_project_are_not_restored_before_an_incremental_build(tmp_path: Path) -> None:
    project, tree = tmp_path / "p", tmp_path / "t"
    _write(project / "main.c", "int main;\n", OLD)
    _write(project / "main.o", "object of an in-place build of the project\n", OLD)
    _, first = _first_copy(project, tree)
    _write(tree / "main.o", "object compiled in the tree\n")  # the build in the tree replaced it

    _write(project / "main.c", "int main = 1;\n", OLD)
    incremental = _sync_with(project, tree, first, keep_outputs=True)
    assert incremental.written == ["main.c"] and incremental.kept_outputs == ["main.o"]
    assert (tree / "main.o").read_text() == "object compiled in the tree\n"

    # before a full build the tree holds what a copy would
    full = _sync_with(project, tree, incremental)
    assert full.written == ["main.o"] and (tree / "main.o").read_text().startswith("object of an in-place")


def _sync_with(project: Path, tree: Path, previous: SyncResult, keep_outputs: bool = False) -> SyncResult:
    return sync_tree(str(tree), copy_set(CopyExclusions(str(project))), previous.synced, keep_outputs=keep_outputs)

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from pathlib import Path
from typing import List

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui.excluded_directories import ExcludedDirectoriesTree
from discopop_library.ProjectManager.services.excluded_directories import load_excluded_directories


@pytest.fixture
def project(tmp_path: Path) -> Path:
    for name in (
        "src/core",
        "build/_deps/fmt/include",
        "build/_deps/range-v3",
        "build/CMakeFiles",
        ".discopop/project",
    ):
        (tmp_path / name).mkdir(parents=True)
    return tmp_path


def _tree(qtbot: QtBot, project: Path) -> ExcludedDirectoriesTree:
    tree = ExcludedDirectoriesTree(str(project), str(project / ".discopop" / "project"))
    qtbot.addWidget(tree)
    return tree


def _stored(project: Path) -> List[str]:
    return load_excluded_directories(str(project / ".discopop" / "project"))


def _click_check_box(tree: ExcludedDirectoriesTree, path: str) -> None:
    item = tree.expand_path(path)
    assert item is not None
    item.setCheckState(
        0, Qt.CheckState.Unchecked if item.checkState(0) == Qt.CheckState.Checked else Qt.CheckState.Checked
    )


def test_top_level_without_discopop_and_children_read_when_expanded(qtbot: QtBot, project: Path) -> None:
    tree = _tree(qtbot, project)
    top_level = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    assert [item.text(0) for item in top_level if item is not None] == ["build", "src"]
    assert tree.item_of("build/_deps") is None
    # expand_path opens the directories above a path
    tree.expand_path("build/_deps/fmt")
    assert tree.item_of("build/_deps/fmt") is not None and tree.item_of("build/_deps/range-v3") is not None
    assert tree.item_of("build/_deps/fmt/include") is None
    tree.expand_path("build/_deps/fmt/include")
    assert tree.item_of("build/_deps/fmt/include") is not None


def test_checking_a_directory_excludes_it_and_everything_below(qtbot: QtBot, project: Path) -> None:
    tree = _tree(qtbot, project)
    tree.expand_path("build/_deps/fmt")
    with qtbot.waitSignal(tree.changed) as signal:
        _click_check_box(tree, "build/_deps")
    assert signal.args == [["build/_deps"]]
    assert _stored(project) == ["build/_deps"]
    fmt = tree.item_of("build/_deps/fmt")
    assert fmt is not None
    # shown as excluded, but locked: it goes with build/_deps
    assert fmt.checkState(0) == Qt.CheckState.Checked
    assert not fmt.flags() & Qt.ItemFlag.ItemIsUserCheckable
    assert "build/_deps" in fmt.toolTip(0)
    deps = tree.item_of("build/_deps")
    assert deps is not None and fmt.foreground(0).color() != deps.foreground(0).color()
    build = tree.item_of("build")
    assert build is not None and build.checkState(0) == Qt.CheckState.Unchecked
    # directories read later show it as well
    tree.expand_path("build/_deps/fmt/include")
    include = tree.item_of("build/_deps/fmt/include")
    assert include is not None and include.checkState(0) == Qt.CheckState.Checked


def test_a_locked_directory_cannot_be_included_on_its_own(qtbot: QtBot, project: Path) -> None:
    tree = _tree(qtbot, project)
    tree.set_excluded("build/_deps", True)
    _click_check_box(tree, "build/_deps/fmt")
    assert _stored(project) == ["build/_deps"]
    fmt = tree.item_of("build/_deps/fmt")
    assert fmt is not None and fmt.checkState(0) == Qt.CheckState.Checked


def test_unchecking_includes_it_again_and_a_parent_replaces_its_children(qtbot: QtBot, project: Path) -> None:
    tree = _tree(qtbot, project)
    tree.expand_path("build/_deps/fmt")
    tree.set_excluded("build/_deps/fmt", True)
    tree.set_excluded("build/_deps/range-v3", True)
    assert _stored(project) == ["build/_deps/fmt", "build/_deps/range-v3"]
    tree.set_excluded("build/_deps", True)
    assert _stored(project) == ["build/_deps"]
    _click_check_box(tree, "build/_deps")
    assert _stored(project) == []
    fmt = tree.item_of("build/_deps/fmt")
    assert fmt is not None and fmt.checkState(0) == Qt.CheckState.Unchecked
    assert fmt.flags() & Qt.ItemFlag.ItemIsUserCheckable


def test_reload_shows_changes_made_outside(qtbot: QtBot, project: Path) -> None:
    tree = _tree(qtbot, project)
    tree.expand_path("build/_deps")
    other = _tree(qtbot, project)
    other.set_excluded("build", True)
    (project / "new_directory").mkdir()
    tree.reload()
    deps = tree.item_of("build/_deps")  # expanded directories stay expanded
    assert deps is not None and deps.checkState(0) == Qt.CheckState.Checked
    assert tree.item_of("new_directory") is not None


def test_a_failed_save_shows_the_stored_state(qtbot: QtBot, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = _tree(qtbot, project)

    def fail(*_args: object) -> List[str]:
        raise OSError("read-only file system")

    monkeypatch.setattr("discopop_library.ProjectManager.qt_gui.excluded_directories.save_excluded_directories", fail)
    with qtbot.waitSignal(tree.failed) as signal:
        _click_check_box(tree, "src")
    assert "read-only file system" in signal.args[0]
    src = tree.item_of("src")
    assert src is not None and src.checkState(0) == Qt.CheckState.Unchecked
    assert _stored(project) == []

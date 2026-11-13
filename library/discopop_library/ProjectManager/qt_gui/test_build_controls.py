# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of the widgets for the builds and runs."""

import time
from pathlib import Path
from typing import List

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.configurations.builds import (
    BuildRecord,
    build_trees_dir_of,
    list_builds,
    write_build,
)
from discopop_library.ProjectManager.configurations.runs import RunRecord, list_all_runs, write_run
from discopop_library.ProjectManager.qt_gui.build_controls import BuildOptions, BuildsAndRuns
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.testing import make_arguments


def test_the_build_options_default_to_compiling_when_needed(qtbot: QtBot) -> None:
    options = BuildOptions()
    qtbot.addWidget(options)
    assert (options.build_policy(), options.build_only(), options.in_place()) == ("auto", False, False)
    options.policy_combo.setCurrentIndex(2)
    assert options.build_policy() == "reuse"
    options.in_place_check.setChecked(True)
    assert options.in_place() and not options.policy_combo.isEnabled()
    options.in_place_check.setChecked(False)
    assert options.policy_combo.isEnabled()


def test_options_without_the_in_place_choice(qtbot: QtBot) -> None:
    options = BuildOptions(offer_in_place=False)
    qtbot.addWidget(options)
    options.show()
    assert not options.in_place_check.isVisible()


@pytest.fixture
def widget(qtbot: QtBot, tmp_path: Path) -> BuildsAndRuns:
    arguments = make_arguments(tmp_path)
    trees = Path(build_trees_dir_of(arguments.project_root))
    for build_id, mode in (("tiny_dp", "dp"), ("tiny_seq", "seq")):
        tree = trees / build_id
        tree.mkdir(parents=True)
        (tree / "file").write_text("x" * 2048)
        write_build(
            arguments.project_dir,
            BuildRecord(build_id, "tiny", mode, [], "fp", str(tree), time.time(), 1.5, "compile.sh"),
        )
    runs_directory = trees / "tiny_dp.runs"
    for run_id, code in (("20260101-000000", 0), ("20260101-000001", 1)):
        dot = runs_directory / run_id
        dot.mkdir(parents=True)
        (dot / "data").write_text("y")
        write_run(
            RunRecord(
                run_id,
                "tiny_dp",
                "tiny",
                "dp",
                2,
                "",
                time.time(),
                str(dot),
                tree=str(trees / "tiny_dp"),
                return_code=code,
            )
        )
    created = BuildsAndRuns(arguments)
    qtbot.addWidget(created)
    return created


def test_the_builds_and_the_runs_are_listed(widget: BuildsAndRuns) -> None:
    assert [widget.build_table.item(row, 0).text() for row in range(2)] == ["tiny_dp", "tiny_seq"]  # type: ignore[union-attr]
    assert [widget.run_table.item(row, 5).text() for row in range(2)] == ["ok", "failed"]  # type: ignore[union-attr]
    # sizes read the trees: only on request
    assert widget.build_table.item(0, 5).text() == "?"  # type: ignore[union-attr]
    widget.sizes_button.click()
    assert widget.build_table.item(0, 5).text() == "2.0 KiB"  # type: ignore[union-attr]


def test_a_build_can_be_checked(widget: BuildsAndRuns) -> None:
    widget.build_table.selectRow(0)
    widget.check_button.click()
    # no project files, no configuration: whatever the state is, it is told
    assert widget.build_table.item(0, 6).text() != ""  # type: ignore[union-attr]


def test_deleting_builds_asks_and_deletes_only_the_selected(
    widget: BuildsAndRuns, dialog_answers: DialogRecorder
) -> None:
    changes: List[str] = []
    widget._changed = lambda: changes.append("changed")
    widget.build_table.selectRow(1)
    dialog_answers.answer("ask_yes_no", False)
    widget.delete_builds_button.click()
    assert len(list_builds(widget.arguments.project_dir)) == 2
    dialog_answers.answer("ask_yes_no", True)
    widget.delete_builds_button.click()
    assert [b.build_id for b in list_builds(widget.arguments.project_dir)] == ["tiny_dp"]
    assert widget.build_table.rowCount() == 1 and changes == ["changed"]
    # the runs stay
    assert len(list_all_runs(widget.arguments)) == 2


def test_deleting_runs(widget: BuildsAndRuns, dialog_answers: DialogRecorder) -> None:
    widget.run_table.selectRow(1)
    dialog_answers.answer("ask_yes_no", True)
    widget.delete_runs_button.click()
    assert [r.run_id for r in list_all_runs(widget.arguments)] == ["20260101-000000"]
    assert widget.run_table.rowCount() == 1


def test_nothing_selected_deletes_nothing(widget: BuildsAndRuns) -> None:
    widget.delete_builds_button.click()
    widget.delete_runs_button.click()
    assert len(list_builds(widget.arguments.project_dir)) == 2 and len(list_all_runs(widget.arguments)) == 2
    assert widget.note.text() == "Select the runs to delete."


def test_a_run_that_failed_cannot_be_used_for_pattern_detection(
    widget: BuildsAndRuns, dialog_answers: DialogRecorder
) -> None:
    widget.run_table.selectRow(1)
    dialog_answers.answer("ask_yes_no", True)
    widget.activate_button.click()
    assert "Cannot use the run" in dialog_answers.titles("show_error")
    assert not Path(widget.arguments.dot_dp, "active_run.json").exists()

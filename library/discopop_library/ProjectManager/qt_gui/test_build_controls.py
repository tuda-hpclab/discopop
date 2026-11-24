# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of the widgets for the builds and runs."""

import json
import time
from pathlib import Path
from typing import List

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.configurations.builds import (
    BuildFiles,
    BuildKey,
    BuildRecord,
    build_trees_dir_of,
    compute_fingerprint,
    list_builds,
    make_record,
    read_build_files,
    write_build,
)
from discopop_library.ProjectManager.configurations.runs import RunRecord, list_all_runs, write_run
from discopop_library.ProjectManager.qt_gui import dialogs
from discopop_library.ProjectManager.qt_gui.build_controls import BuildOptions, BuildsAndRuns
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services import build_overview
from discopop_library.ProjectManager.services.fingerprint_ignore import load_fingerprint_ignore


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


def test_a_build_can_be_checked(qtbot: QtBot, widget: BuildsAndRuns) -> None:
    widget.build_table.selectRow(0)
    widget.check_button.click()
    qtbot.waitUntil(lambda: not widget.is_busy(), timeout=20000)
    # no project files, no configuration: whatever the state is, it is told
    assert widget.build_table.item(0, 6).text() != ""  # type: ignore[union-attr]


def test_deleting_builds_asks_and_deletes_only_the_selected(
    qtbot: QtBot, widget: BuildsAndRuns, dialog_answers: DialogRecorder
) -> None:
    changes: List[str] = []
    widget._changed = lambda: changes.append("changed")
    widget.build_table.selectRow(1)
    dialog_answers.answer("ask_yes_no", False)
    widget.delete_builds_button.click()
    assert len(list_builds(widget.arguments.project_dir)) == 2
    dialog_answers.answer("ask_yes_no", True)
    widget.delete_builds_button.click()
    qtbot.waitUntil(lambda: not widget.is_busy(), timeout=20000)
    assert [b.build_id for b in list_builds(widget.arguments.project_dir)] == ["tiny_dp"]
    assert widget.build_table.rowCount() == 1 and changes == ["changed"]
    # the runs stay
    assert len(list_all_runs(widget.arguments)) == 2


def test_deleting_runs(qtbot: QtBot, widget: BuildsAndRuns, dialog_answers: DialogRecorder) -> None:
    widget.run_table.selectRow(1)
    dialog_answers.answer("ask_yes_no", True)
    widget.delete_runs_button.click()
    qtbot.waitUntil(lambda: not widget.is_busy(), timeout=20000)
    assert [r.run_id for r in list_all_runs(widget.arguments)] == ["20260101-000000"]
    assert widget.run_table.rowCount() == 1


def test_nothing_selected_deletes_nothing(widget: BuildsAndRuns) -> None:
    widget.delete_builds_button.click()
    widget.delete_runs_button.click()
    assert len(list_builds(widget.arguments.project_dir)) == 2 and len(list_all_runs(widget.arguments)) == 2
    assert widget.note.text() == "Select the runs to delete."


def test_a_run_that_failed_cannot_be_used_for_pattern_detection(
    qtbot: QtBot, widget: BuildsAndRuns, dialog_answers: DialogRecorder
) -> None:
    widget.run_table.selectRow(1)
    dialog_answers.answer("ask_yes_no", True)
    widget.activate_button.click()
    qtbot.waitUntil(lambda: not widget.is_busy(), timeout=20000)
    assert "Cannot use the run" in dialog_answers.titles("show_error")
    assert not Path(widget.arguments.dot_dp, "active_run.json").exists()


def test_nothing_is_changed_while_a_job_uses_the_builds(widget: BuildsAndRuns) -> None:
    widget.set_blocked(True)
    assert not any(
        button.isEnabled()
        for button in (
            widget.check_button,
            widget.delete_builds_button,
            widget.activate_button,
            widget.delete_runs_button,
            widget.refresh_button,
        )
    )
    widget.set_blocked(False)
    assert widget.delete_builds_button.isEnabled() and widget.delete_runs_button.isEnabled()


def test_the_runs_can_be_limited_to_modes(qtbot: QtBot, widget: BuildsAndRuns) -> None:
    trees = Path(build_trees_dir_of(widget.arguments.project_root))
    dot = trees / "tiny_hd.runs" / "20260101-000002"
    dot.mkdir(parents=True)
    write_run(RunRecord("20260101-000002", "tiny_hd", "tiny", "hd", 1, "", time.time(), str(dot), return_code=0))
    widget.refresh()
    assert widget.run_table.rowCount() == 3
    only_dp = BuildsAndRuns(widget.arguments, show_builds=False, run_modes=("dp",))
    qtbot.addWidget(only_dp)
    assert [only_dp.run_table.item(row, 2).text() for row in range(only_dp.run_table.rowCount())] == ["dp", "dp"]  # type: ignore[union-attr]


@pytest.fixture
def stale_build(qtbot: QtBot, tmp_path: Path) -> BuildsAndRuns:
    """A current seq build of ``cfg`` whose project then got a build directory ``dp_build`` (not ignored by git)."""
    arguments = make_arguments(tmp_path / "proj")
    configs = Path(arguments.project_config_dir)
    (configs / "cfg").mkdir()
    (configs / "compile.sh").write_text("#!/bin/bash\n")
    (configs / "seq_settings.json").write_text(json.dumps({"CC": "cc", "CXX": "c++"}))
    (tmp_path / "proj" / "main.c").write_text("int main() { return 0; }\n")
    key = BuildKey("cfg", "seq")
    tree = Path(build_trees_dir_of(arguments.project_root)) / key.build_id
    tree.mkdir(parents=True)
    compile_script = str(configs / "compile.sh")
    settings = str(configs / "seq_settings.json")
    parts, entries = compute_fingerprint(arguments, key, compile_script, settings)
    record = make_record(arguments, key, compile_script, settings, str(tree), 1.0, parts)
    write_build(arguments.project_dir, record, BuildFiles(sources=entries))
    (tmp_path / "proj" / "dp_build").mkdir()
    (tmp_path / "proj" / "dp_build" / "build.ninja").write_text("cache\n")
    created = BuildsAndRuns(arguments)
    qtbot.addWidget(created)
    created.build_table.selectRow(0)
    return created


def test_ignoring_the_changed_paths_makes_the_build_current(
    qtbot: QtBot, stale_build: BuildsAndRuns, dialog_answers: DialogRecorder
) -> None:
    dialog_answers.answer("review_build_changes", (dialogs.REVIEW_IGNORE, "dp_build/\n"))
    stale_build.review_button.click()
    qtbot.waitUntil(lambda: not stale_build.is_busy(), timeout=20000)
    assert dialog_answers.titles("review_build_changes") == ["Changes since the build cfg_seq"]
    assert "1 file changed (1 added): dp_build/ (1)." in dialog_answers.messages("review_build_changes")[0]
    assert load_fingerprint_ignore(stale_build.arguments.project_dir) == ["dp_build/"]
    assert stale_build.build_table.item(0, 6).text() == "current"  # type: ignore[union-attr]
    assert "is current" in stale_build.note.text()


def test_accepting_a_stale_build_asks_first(
    qtbot: QtBot, stale_build: BuildsAndRuns, dialog_answers: DialogRecorder
) -> None:
    dialog_answers.answer("review_build_changes", (dialogs.REVIEW_ACCEPT, ""), (dialogs.REVIEW_ACCEPT, ""))
    dialog_answers.answer("ask_yes_no", False, True)
    stale_build.review_button.click()
    qtbot.waitUntil(lambda: not stale_build.is_busy(), timeout=20000)
    # declined: nothing changed
    assert stale_build.build_table.item(0, 6).text().startswith("stale")  # type: ignore[union-attr]
    stale_build.review_button.click()
    qtbot.waitUntil(lambda: not stale_build.is_busy(), timeout=20000)
    assert stale_build.build_table.item(0, 6).text() == "current (changes accepted)"  # type: ignore[union-attr]
    files = read_build_files(stale_build.arguments.project_dir, BuildKey("cfg", "seq"))
    assert files is not None and files.accepted[0]["files"] == ["dp_build/build.ninja"]
    assert load_fingerprint_ignore(stale_build.arguments.project_dir) == []


def test_closing_the_review_changes_nothing(
    qtbot: QtBot, stale_build: BuildsAndRuns, dialog_answers: DialogRecorder
) -> None:
    dialog_answers.answer("review_build_changes", None)
    stale_build.review_button.click()
    qtbot.waitUntil(lambda: not stale_build.is_busy(), timeout=20000)
    files = read_build_files(stale_build.arguments.project_dir, BuildKey("cfg", "seq"))
    assert files is not None and files.accepted == []
    assert load_fingerprint_ignore(stale_build.arguments.project_dir) == []


def test_the_review_proposes_build_directories_only(stale_build: BuildsAndRuns) -> None:
    root = Path(stale_build.arguments.project_root)
    (root / "main.c").write_text("int main() { return 1; }\n")
    (root / "out").mkdir()
    (root / "out" / "a.o").write_text("o")
    review = build_overview.review_build(stale_build.arguments, "cfg_seq")
    # no git: a directory counts as a build directory by the marker of its build system
    assert review.suggested_patterns == ("dp_build/",)
    assert review.file_lines() == ["A  dp_build/build.ninja", "M  main.c", "A  out/a.o"]

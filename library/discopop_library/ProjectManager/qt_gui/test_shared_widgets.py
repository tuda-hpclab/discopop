# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from pathlib import Path
from typing import List

from pytestqt.qtbot import QtBot
from PySide6.QtCore import Qt

from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.detail_bar import DetailBar
from discopop_library.ProjectManager.qt_gui.suggestion_browser import SuggestionBrowserDialog
from discopop_library.ProjectManager.qt_gui.suggestion_selector import SuggestionSelector

DIFF = "--- a/main.c\t2026\n+++ b/main.c\n@@ -1 +1,2 @@\n+#pragma omp parallel for\n for (;;) {}\n"


def write_patches(dot_dp: Path, ids: List[str]) -> None:
    for sid in ids:
        directory = dot_dp / "patch_generator" / sid
        directory.mkdir(parents=True)
        (directory / "1.patch").write_text(DIFF)


def test_detail_bar_actions_follow_the_selection(qtbot: QtBot) -> None:
    bar = DetailBar()
    qtbot.addWidget(bar)
    button = bar.add_action("Open", lambda: None, enabled=lambda: bool(bar.fields))
    assert not button.isEnabled()
    bar.show_fields([("Configuration", "tiny"), ("Time", "1.2 s")])
    assert button.isEnabled() and bar.fields[1] == ("Time", "1.2 s")
    bar.show_placeholder()
    assert not button.isEnabled()


def test_selector_persists_the_deselection_and_selects_new_ids(qtbot: QtBot, tmp_path: Path) -> None:
    write_patches(tmp_path, ["10", "2", "1"])
    changes: List[bool] = []
    selector = SuggestionSelector(str(tmp_path), "execute", lambda: changes.append(True))
    qtbot.addWidget(selector)
    assert selector.get_available_ids() == ["1", "2", "10"]
    assert selector.get_selected_ids() == ["1", "2", "10"] and selector.toggle_button.text() == "Deselect all"

    selector.entry.setText("1,10")
    selector.apply_button.click()
    assert selector.get_selected_ids() == ["1", "10"] and selector.toggle_button.text() == "Select all"
    assert changes

    # a click on a checkbox counts as well
    selector.list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert selector.get_selected_ids() == ["10"]

    write_patches(tmp_path, ["3"])
    other = SuggestionSelector(str(tmp_path), "execute")
    qtbot.addWidget(other)
    assert other.get_selected_ids() == ["3", "10"]
    # another key keeps its own selection
    third = SuggestionSelector(str(tmp_path), "autotuning")
    qtbot.addWidget(third)
    assert third.get_selected_ids() == ["1", "2", "3", "10"]


def test_selector_toggle_and_empty_state(qtbot: QtBot, tmp_path: Path) -> None:
    selector = SuggestionSelector(str(tmp_path), "execute")
    qtbot.addWidget(selector)
    assert selector.get_available_ids() == [] and selector.toggle_button.text() == "Select all"
    write_patches(tmp_path, ["1", "2"])
    selector.refresh()
    selector.toggle_button.click()
    assert selector.get_selected_ids() == []
    selector.toggle_button.click()
    assert selector.get_selected_ids() == ["1", "2"]


def test_browser_lists_suggestions_numerically_and_saves_an_edited_patch(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder
) -> None:
    write_patches(tmp_path, ["10", "2"])
    browser = SuggestionBrowserDialog(None, str(tmp_path))
    qtbot.addWidget(browser)
    assert browser.suggestion_ids() == ["2", "10"]
    first = browser.tree.topLevelItem(0)
    patch_item = first.child(0) if first is not None else None
    assert patch_item is not None and patch_item.text(0) == "main.c"

    browser.show_suggestion("2")
    assert browser.editor.isReadOnly() and not browser.save_button.isEnabled()

    patch = tmp_path / "patch_generator" / "10" / "1.patch"
    browser.show_patch(str(patch))
    assert not browser.editor.isReadOnly() and browser.save_button.isEnabled()
    browser.editor.setPlainText(DIFF + "\n")
    assert browser.save_button.text() == "Save File *"

    # switching with unsaved changes asks; "yes" saves first
    dialog_answers.answer("ask_yes_no", True)
    browser.show_suggestion("2")
    assert patch.read_text() == DIFF + "\n"
    assert dialog_answers.titles("ask_yes_no") == ["Unsaved Changes"]

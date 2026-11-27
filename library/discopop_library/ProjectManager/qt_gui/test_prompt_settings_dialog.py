# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
from pathlib import Path

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui import dialogs
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.main_window import MainWindow
from discopop_library.ProjectManager.qt_gui.prompt_settings_dialog import PromptSettingsDialog
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.SuggestionCheck import prompt_store


def _dialog(qtbot: QtBot, tmp_path: Path) -> PromptSettingsDialog:
    dialog = PromptSettingsDialog(str(tmp_path / "prompts"))
    qtbot.addWidget(dialog)
    return dialog


def _stored(tmp_path: Path, name: str) -> bool:
    return os.path.isfile(tmp_path / "prompts" / (name + ".md"))


def test_settings_menu_opens_the_dialog_of_the_project(qtbot: QtBot, tmp_path: Path) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    assert [a.text() for a in window.settings_menu.actions()] == ["Suggestion check prompts…"]
    window.prompt_settings_action.trigger()
    dialog = window.prompt_settings_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.prompt_dir == prompt_store.custom_prompt_dir(window.arguments.dot_dp)
    dialog.close()


def test_shows_the_shipped_templates_when_nothing_is_customized(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = _dialog(qtbot, tmp_path)
    titles = [dialog.template_list.item(i).text() for i in range(dialog.template_list.count())]
    assert titles == [t.title for t in prompt_store.TEMPLATES]
    assert dialog.editor.toPlainText() == prompt_store.default_template("check")
    assert prompt_store.TEMPLATES[0].purpose in dialog.purpose_label.text()
    assert "{blockers}" in dialog.placeholder_label.text()
    assert not dialog.has_unsaved_changes()


def test_save_stores_the_custom_template_and_marks_it(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = _dialog(qtbot, tmp_path)
    text = dialog.editor.toPlainText() + "\nExtra line."
    dialog.editor.setPlainText(text)
    assert dialog.has_unsaved_changes()
    assert dialog.save()
    assert _stored(tmp_path, "check")
    assert prompt_store.effective_template("check", dialog.prompt_dir) == text
    assert dialog.template_list.item(0).text() == "Check (customized)"
    assert not dialog.has_unsaved_changes()


def test_restore_default_and_save_removes_the_custom_file(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = _dialog(qtbot, tmp_path)
    dialog.editor.setPlainText(dialog.editor.toPlainText() + "\nExtra line.")
    dialog.save()
    dialog.restore_default()
    assert dialog.editor.toPlainText() == prompt_store.default_template("check")
    assert _stored(tmp_path, "check")  # takes effect on save
    assert dialog.save()
    assert not _stored(tmp_path, "check")
    assert dialog.template_list.item(0).text() == "Check"


def test_removed_placeholder_is_confirmed_and_declining_skips_saving(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder
) -> None:
    dialog = _dialog(qtbot, tmp_path)
    dialog.editor.setPlainText(dialog.editor.toPlainText().replace("{blockers}", "") + " {bogus}")
    dialog_answers.answer("ask_yes_no", False, True)
    assert not dialog.save()
    assert not _stored(tmp_path, "check")
    message = dialog_answers.messages("ask_yes_no")[0]
    assert "{blockers}" in message and "{bogus}" in message
    assert dialog.save()
    assert _stored(tmp_path, "check")


def test_switching_with_unsaved_changes_asks(qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder) -> None:
    dialog = _dialog(qtbot, tmp_path)
    edited = dialog.editor.toPlainText() + "\nEdit."
    dialog.editor.setPlainText(edited)
    # cancel: stay on the entry, edits kept
    dialog_answers.answer("ask_save_discard", None)
    dialog.template_list.setCurrentRow(1)
    assert dialog.template_list.currentRow() == 0 and dialog.editor.toPlainText() == edited
    # discard: switch, nothing stored
    dialog_answers.answer("ask_save_discard", dialogs.DISCARD)
    dialog.template_list.setCurrentRow(1)
    assert dialog.current_name == "review"
    assert dialog.editor.toPlainText() == prompt_store.default_template("review")
    assert not _stored(tmp_path, "check")
    # save: switch, stored
    dialog.template_list.setCurrentRow(0)
    dialog.editor.setPlainText(edited)
    dialog_answers.answer("ask_save_discard", dialogs.SAVE)
    dialog.template_list.setCurrentRow(2)
    assert _stored(tmp_path, "check") and dialog.current_name == "retry"


def test_closing_with_unsaved_changes_can_be_cancelled(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder
) -> None:
    dialog = _dialog(qtbot, tmp_path)
    dialog.show()
    dialog.editor.setPlainText("changed")
    dialog_answers.answer("ask_save_discard", None, dialogs.DISCARD)
    dialog.close()
    assert dialog.isVisible()
    dialog.close()
    assert not dialog.isVisible()


def test_closing_the_window_asks_about_unsaved_prompt_edits(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder
) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window.show()
    dialog = window.open_prompt_settings()
    dialog.editor.setPlainText("edited {description} {blockers} {code}")
    dialog_answers.answer("ask_save_discard", None, dialogs.DISCARD)
    # Cancel: both stay open
    assert not window.close()
    assert window.isVisible() and dialog.isVisible()
    # Discard: the window closes, nothing is stored
    assert window.close()
    assert not os.path.isfile(os.path.join(prompt_store.custom_prompt_dir(window.arguments.dot_dp), "check.md"))


def _press_escape(qtbot: QtBot, dialog: PromptSettingsDialog) -> None:
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)


def test_escape_without_edits_closes_without_asking(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = _dialog(qtbot, tmp_path)
    dialog.show()
    with qtbot.waitSignal(dialog.finished, timeout=1000):
        _press_escape(qtbot, dialog)
    assert not dialog.isVisible()


def test_escape_with_unsaved_changes_asks(qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder) -> None:
    dialog = _dialog(qtbot, tmp_path)
    dialog.show()
    dialog.editor.setPlainText("changed")
    # Cancel: the dialog stays, with the edits
    dialog_answers.answer("ask_save_discard", None)
    with qtbot.assertNotEmitted(dialog.finished):
        _press_escape(qtbot, dialog)
    assert dialog.isVisible() and dialog.editor.toPlainText() == "changed"
    # Discard: the dialog closes and says so
    dialog_answers.answer("ask_save_discard", dialogs.DISCARD)
    with qtbot.waitSignal(dialog.finished, timeout=1000):
        _press_escape(qtbot, dialog)
    assert not dialog.isVisible()
    assert not _stored(tmp_path, "check")


def test_escape_and_close_let_the_window_forget_the_dialog(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder
) -> None:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    window.show()
    dialog = window.open_prompt_settings()
    _press_escape(qtbot, dialog)
    assert window.prompt_settings_dialog is None
    # closing the window (not the Close button or Esc) emits finished, too
    dialog = window.open_prompt_settings()
    dialog.editor.setPlainText("edited")
    dialog_answers.answer("ask_save_discard", dialogs.DISCARD)
    assert dialog.close()
    assert window.prompt_settings_dialog is None
    assert window.open_prompt_settings() is not dialog

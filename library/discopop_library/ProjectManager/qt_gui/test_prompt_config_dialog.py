# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.prompt_config_dialog import PromptConfigDialog
from discopop_library.ProjectManager.services import prompt_templates as pt


@pytest.fixture
def dot_dp(tmp_path: Path) -> str:
    return str(tmp_path / ".discopop")


@pytest.fixture
def dialog(qtbot: QtBot, dot_dp: str) -> PromptConfigDialog:
    widget = PromptConfigDialog(dot_dp)
    qtbot.addWidget(widget)
    return widget


def test_it_lists_every_template_and_starts_on_the_first(dialog: PromptConfigDialog) -> None:
    assert dialog.current_name() == pt.TEMPLATES[0].name
    assert dialog.editor.toPlainText() == pt.builtin_text(pt.TEMPLATES[0].name)
    titles = [dialog.template_list.item(i).text().strip() for i in range(dialog.template_list.count())]
    assert pt.GROUP_REPAIR in titles and pt.GROUP_COMPLETION in titles
    assert len(titles) == len(pt.TEMPLATES) + 2
    assert "{original_source}" in dialog.placeholder_label.text()


def test_editing_and_saving_writes_the_project_template(dialog: PromptConfigDialog, dot_dp: str) -> None:
    dialog.select("completion")
    text = "Choose the cutoff with care.\n{original_source}\n{placeholders}\n{output_contract}\n"
    dialog.editor.setPlainText(text)
    assert dialog.has_unsaved_changes()
    assert "*" in dialog._items["completion"].text()
    assert not pt.is_customized(dot_dp, "completion")
    assert dialog.save()
    assert not dialog.has_unsaved_changes()
    assert pt.current_text(dot_dp, "completion").startswith("Choose the cutoff")
    assert "●" in dialog._items["completion"].text()


def test_an_edit_survives_switching_the_entry(dialog: PromptConfigDialog) -> None:
    dialog.select("retry")
    dialog.editor.setPlainText("again {failure} {output_contract}")
    dialog.select("minimal")
    assert dialog.editor.toPlainText() == pt.builtin_text("minimal")
    dialog.select("retry")
    assert dialog.editor.toPlainText() == "again {failure} {output_contract}"


def test_typing_the_old_text_back_is_no_change(dialog: PromptConfigDialog) -> None:
    dialog.select("retry")
    dialog.editor.setPlainText("x")
    dialog.editor.setPlainText(pt.builtin_text("retry"))
    assert not dialog.has_unsaved_changes()


def test_a_missing_placeholder_is_shown_and_asked_about_on_save(
    dialog: PromptConfigDialog, dot_dp: str, dialog_answers: DialogRecorder
) -> None:
    dialog.select("completion")
    dialog.editor.setPlainText("Just do it.")
    assert "{original_source}" in dialog.warning_label.text()
    dialog_answers.answer("ask_yes_no", False, True)
    assert not dialog.save()
    assert not pt.is_customized(dot_dp, "completion")
    assert dialog.save()
    assert pt.is_customized(dot_dp, "completion")
    assert dialog_answers.titles("ask_yes_no") == ["Missing placeholders"] * 2


def test_reset_returns_to_the_built_in_text_when_saved(dialog: PromptConfigDialog, dot_dp: str) -> None:
    pt.save_template(dot_dp, "guided", "mine {original_source} {output_contract}")
    dialog.select("guided")
    assert dialog.editor.toPlainText().startswith("mine")
    assert dialog.reset_button.isEnabled()
    dialog.reset_current()
    assert dialog.editor.toPlainText() == pt.builtin_text("guided")
    assert pt.is_customized(dot_dp, "guided")  # not yet: reset is applied by Save, like every edit
    dialog.save()
    assert not pt.is_customized(dot_dp, "guided")


def test_closing_with_unsaved_changes_asks(dialog: PromptConfigDialog, dialog_answers: DialogRecorder) -> None:
    dialog.select("retry")
    dialog.editor.setPlainText("changed")
    dialog_answers.answer("ask_yes_no", False)
    dialog.reject()
    assert dialog.has_unsaved_changes()
    dialog_answers.answer("ask_yes_no", True)
    dialog.reject()
    assert dialog_answers.titles("ask_yes_no") == ["Unsaved changes"] * 2


def test_closing_without_changes_does_not_ask(dialog: PromptConfigDialog) -> None:
    dialog.reject()  # a question would fail the test: no answer is queued

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from pytestqt.qtbot import QtBot
from PySide6.QtWidgets import QComboBox, QLineEdit

from discopop_library.PatchRepair import llm_backends
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.llm_config_dialog import LlmConfigDialog

STORED: Dict[str, Any] = {
    "version": 1,
    "connections": {
        "fast": {"backend": "claude", "model": "haiku", "retries": 1, "backend_options": {"effort": "low"}},
        "slow": {"backend": "opencode", "model": "p/m", "env": {"A": "1"}, "extra_args": ["--x", "a b"]},
    },
    "backends": {"claude": {"binary": "/opt/claude", "options": {"effort": "high"}}},
}


@pytest.fixture(autouse=True)
def probes(monkeypatch: pytest.MonkeyPatch) -> None:
    """No agent is installed on a test machine: the probes answer from a table."""
    for name in llm_backends.available_backends():
        module = llm_backends.get(name)
        monkeypatch.setattr(module, "list_models", lambda config=None, n=name: [n + "-model-1", n + "-model-2"])
        monkeypatch.setattr(
            module, "version", lambda config=None: "1.2.3" if (config or {}).get("binary") != "/bad" else None
        )
        monkeypatch.setattr(module, "available", lambda config=None: True)


def make_dialog(qtbot: QtBot, tmp_path: Path, content: Optional[Dict[str, Any]] = STORED) -> LlmConfigDialog:
    path = tmp_path / "llm_config.json"
    if content is not None:
        path.write_text(json.dumps(content))
    dialog = LlmConfigDialog(str(path))
    qtbot.addWidget(dialog)
    return dialog


def saved(tmp_path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = json.loads((tmp_path / "llm_config.json").read_text())
    return result


def wait_for_models(qtbot: QtBot, dialog: LlmConfigDialog) -> None:
    qtbot.waitUntil(lambda: dialog.model_combo.count() > 0, timeout=5000)


def test_a_missing_file_starts_empty_without_an_error(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder
) -> None:
    dialog = make_dialog(qtbot, tmp_path, None)
    assert dialog.connection_names() == []
    assert not dialog.connection_editor.isEnabled()
    assert dialog_answers.calls == []
    assert dialog.save()
    assert saved(tmp_path) == {"version": 1, "connections": {}, "backends": {}}


def test_an_unreadable_file_is_reported(qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder) -> None:
    (tmp_path / "llm_config.json").write_text("{not json")
    dialog = LlmConfigDialog(str(tmp_path / "llm_config.json"))
    qtbot.addWidget(dialog)
    assert dialog_answers.titles("show_error")
    assert dialog.connection_names() == []


def test_an_existing_file_is_shown_and_models_arrive_in_the_background(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = make_dialog(qtbot, tmp_path)
    assert dialog.connection_names() == ["fast", "slow"]
    assert dialog.backend_combo.currentData() == "claude"
    assert dialog.model_combo.currentText() == "haiku"
    assert dialog.retries_edit.text() == "1"
    assert dialog.options.values()["effort"] == "low"
    wait_for_models(qtbot, dialog)
    assert dialog.model_combo.currentText() == "haiku"  # what is stored stays when the list arrives
    assert [dialog.model_combo.itemText(i) for i in range(2)] == ["claude-model-1", "claude-model-2"]


def test_editing_and_saving_a_connection(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = make_dialog(qtbot, tmp_path)
    dialog.select_connection("slow")
    assert dialog.env_edit.toPlainText() == "A=1\n"
    assert dialog.extra_args_edit.text() == "--x 'a b'"
    dialog.model_combo.setCurrentText("q/other")
    dialog.timeout_edit.setText("90")
    dialog.env_edit.setPlainText("A=2\nB=3")
    dialog.retries_edit.setText("")
    assert dialog.dirty
    assert dialog.save()
    assert not dialog.dirty
    slow = saved(tmp_path)["connections"]["slow"]
    assert slow == {
        "backend": "opencode",
        "model": "q/other",
        "timeout": 90,
        "env": {"A": "2", "B": "3"},
        "extra_args": ["--x", "a b"],
    }
    assert saved(tmp_path)["connections"]["fast"]["backend_options"] == {"effort": "low"}


def test_switching_the_backend_rebuilds_the_options_and_saves_them(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = make_dialog(qtbot, tmp_path)
    dialog.backend_combo.setCurrentIndex(dialog.backend_combo.findData("opencode"))
    assert set(dialog.options.editors) == {spec.key for spec in llm_backends.fields_of("opencode")}
    assert isinstance(dialog.options.editors["auto"], QComboBox)
    dialog.options.set_value("agent", "build")
    dialog.options.set_value("auto", "yes")
    assert dialog.save()
    fast = saved(tmp_path)["connections"]["fast"]
    assert fast["backend"] == "opencode"
    assert fast["backend_options"] == {"agent": "build", "auto": True}


def test_new_copy_and_delete_a_connection(qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder) -> None:
    dialog = make_dialog(qtbot, tmp_path)
    dialog_answers.answer("ask_string", "brand_new")
    dialog.new_button.click()
    assert dialog.connection_names() == ["brand_new", "fast", "slow"]
    assert dialog.model_combo.currentText() == ""

    dialog.select_connection("slow")
    dialog_answers.answer("ask_string", "slow2")
    dialog.copy_button.click()
    assert dialog._current_connection == "slow2"
    assert dialog.env_edit.toPlainText() == "A=1\n"

    dialog.select_connection("fast")
    dialog.delete_button.click()
    assert dialog.connection_names() == ["brand_new", "slow", "slow2"]
    assert dialog.save()
    stored = saved(tmp_path)["connections"]
    assert sorted(stored) == ["brand_new", "slow", "slow2"]
    assert stored["brand_new"] == {}
    assert stored["slow2"] == stored["slow"]


@pytest.mark.parametrize("name", ["", "slow", "backend"])
def test_invalid_connection_names_reach_show_error(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder, name: str
) -> None:
    dialog = make_dialog(qtbot, tmp_path)
    dialog_answers.answer("ask_string", name)
    dialog.new_button.click()
    assert len(dialog_answers.titles("show_error")) == 1
    assert dialog.connection_names() == ["fast", "slow"]


def test_cancelling_the_name_dialog_adds_nothing(qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder) -> None:
    dialog = make_dialog(qtbot, tmp_path)
    dialog_answers.answer("ask_string", None)
    dialog.new_button.click()
    assert dialog.connection_names() == ["fast", "slow"]
    assert dialog_answers.calls[-1][0] == "ask_string"


def test_invalid_values_are_reported_and_nothing_is_written(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder
) -> None:
    dialog = make_dialog(qtbot, tmp_path)
    before = (tmp_path / "llm_config.json").read_text()
    dialog.timeout_edit.setText("soon")
    assert not dialog.save()
    assert "Timeout" in dialog_answers.messages("show_error")[-1]
    # switching away from an invalid connection is refused as well
    dialog.select_connection("slow")
    assert dialog._current_connection == "fast"
    assert len(dialog_answers.titles("show_error")) == 2
    dialog.timeout_edit.setText("")
    dialog.env_edit.setPlainText("no equals sign")
    assert not dialog.save()
    assert (tmp_path / "llm_config.json").read_text() == before


def test_closing_with_unsaved_changes_asks(qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder) -> None:
    dialog = make_dialog(qtbot, tmp_path)
    dialog.show()
    dialog.close_button.click()  # nothing changed: no question
    assert not dialog.isVisible()

    dialog = make_dialog(qtbot, tmp_path)
    dialog.show()
    dialog.model_combo.setCurrentText("changed")
    dialog_answers.answer("ask_yes_no", False, True)
    dialog.close_button.click()
    assert dialog.isVisible()
    dialog.close_button.click()
    assert not dialog.isVisible()
    assert dialog_answers.titles("ask_yes_no") == ["LLM Configuration", "LLM Configuration"]
    assert saved(tmp_path)["connections"]["fast"]["model"] == "haiku"


def test_backend_section_round_trip_and_status(qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder) -> None:
    dialog = make_dialog(qtbot, tmp_path)
    dialog.tabs.setCurrentIndex(1)
    dialog.select_backend("claude")
    assert dialog.binary_edit.text() == "/opt/claude"
    assert dialog.backend_options.values()["effort"] == "high"
    qtbot.waitUntil(lambda: "can be run: 1.2.3" in dialog.status_label.text(), timeout=5000)

    dialog.binary_edit.setText("/bad")
    dialog.check_button.click()
    qtbot.waitUntil(lambda: "could not be run" in dialog.status_label.text(), timeout=5000)
    assert llm_backends.get("claude").INSTALL_HINT in dialog.status_label.text()

    dialog_answers.answer("ask_open_file", "/usr/bin/claude2")
    dialog.browse_button.click()
    assert dialog.binary_edit.text() == "/usr/bin/claude2"

    dialog.backend_args_edit.setText("-v")
    dialog.backend_env_edit.setPlainText("K=V")
    dialog.select_backend("opencode")
    assert dialog.binary_edit.text() == ""
    dialog.backend_options.set_value("agent", "build")
    assert dialog.save()
    backends = saved(tmp_path)["backends"]
    assert backends["claude"] == {
        "binary": "/usr/bin/claude2",
        "extra_args": ["-v"],
        "env": {"K": "V"},
        "options": {"effort": "high"},
    }
    assert backends["opencode"] == {"options": {"agent": "build"}}


def test_an_emptied_backend_section_is_removed(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = make_dialog(qtbot, tmp_path)
    dialog.select_backend("claude")
    dialog.binary_edit.setText("")
    dialog.backend_options.set_value("effort", "")
    assert dialog.save()
    assert saved(tmp_path)["backends"] == {}


def test_every_text_field_accepts_input_as_plain_line_edits(qtbot: QtBot, tmp_path: Path) -> None:
    dialog = make_dialog(qtbot, tmp_path)
    editors: List[Any] = [dialog.options.editors[k] for k in dialog.options.editors]
    assert any(isinstance(e, QComboBox) for e in editors)
    assert all(isinstance(e, (QComboBox, QLineEdit)) for e in editors)

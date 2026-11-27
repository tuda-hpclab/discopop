# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Widget tests of Settings > LLM connections / LLM backends, over fake backends (no agent is run)."""

import json
import threading
from pathlib import Path
from typing import Any, Dict, List

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QLineEdit
from pytestqt.qtbot import QtBot

from discopop_library.PatchRepair import llm_config
from discopop_library.ProjectManager.qt_gui import dialogs, llm_logic
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.llm_dialogs import (
    BackendsDialog,
    ConnectionsDialog,
    LlmDialog,
    open_llm_dialog,
)
from discopop_library.ProjectManager.qt_gui.main_window import MainWindow
from discopop_library.ProjectManager.qt_gui.testing import (
    ALPHA_FIELDS,
    BETA_FIELDS,
    fake_backend,
    install_fake_backends,
    make_arguments,
)


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    return install_fake_backends(monkeypatch)


@pytest.fixture
def path(tmp_path: Path) -> str:
    return str(tmp_path / ".discopop" / "patch_repair" / "llm_config.json")


def _write(path: str, config: Dict[str, Any]) -> None:
    llm_config.save_config(path, config)


def _read(path: str) -> Dict[str, Any]:
    with open(path) as f:
        result: Dict[str, Any] = json.load(f)
    return result


def _open(qtbot: QtBot, kind: str, path: str) -> Any:
    dialog = open_llm_dialog(None, kind, path)
    assert dialog is not None
    _register(qtbot, dialog)
    _settle(qtbot, dialog)
    return dialog


def _register(qtbot: QtBot, dialog: LlmDialog) -> None:
    # closed at the end of the test: unsaved edits are discarded there, not asked about
    qtbot.addWidget(dialog, before_close_func=lambda d: setattr(d, "_dirty", False))


def _settle(qtbot: QtBot, dialog: LlmDialog) -> None:
    qtbot.waitUntil(lambda: not dialog.probes_running(), timeout=5000)


def _names(dialog: LlmDialog) -> List[str]:
    return [dialog.listbox.item(i).text() for i in range(dialog.listbox.count())]


def _select(qtbot: QtBot, dialog: LlmDialog, name: str) -> None:
    dialog.listbox.setCurrentRow(_names(dialog).index(name))
    _settle(qtbot, dialog)


SAMPLE: Dict[str, Any] = {
    "version": 1,
    "connections": {
        "fast": {
            "description": "the cheap one",
            "backend": "alpha",
            "model": "alpha/m1",
            "timeout": 60,
            "extra_args": ["--x"],
            "env": {"A": "1"},
            "backend_options": {"effort": "low"},
        },
        "slow": {"backend": "beta", "model": "", "system": "flat value"},
    },
    "backends": {"alpha": {"binary": "/opt/alpha", "options": {"agent": "plan"}}},
}


# ---- connections ----------------------------------------------------------------------------------------------


def test_connections_dialog_shows_the_connection_as_written(qtbot: QtBot, path: str) -> None:
    _write(path, SAMPLE)
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    assert _names(dialog) == ["fast", "slow"]
    assert dialog.current == "fast"
    assert dialog.description_edit.text() == "the cheap one"
    assert dialog.backend_combo.currentText() == "alpha"
    assert dialog.model_combo.currentText() == "alpha/m1"
    assert dialog.timeout_edit.text() == "60"
    assert dialog.extra_args_edit.text() == "--x"
    assert dialog.env_text.toPlainText() == "A=1\n"
    texts = dialog.fields.texts()
    # blank fields stay blank (inherit); the hint names what applies then (the backend's option, else the field)
    assert texts == {"agent": "", "effort": "low", "auto": ""}
    assert "blank = plan" in dialog.fields.hints["agent"].text()
    assert "blank = no" in dialog.fields.hints["auto"].text()
    assert not dialog.dirty


def test_model_list_and_availability_come_from_a_probe_with_the_backend_section(
    qtbot: QtBot, path: str, fakes: Dict[str, Any]
) -> None:
    _write(path, SAMPLE)
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    assert [dialog.model_combo.itemText(i) for i in range(dialog.model_combo.count())] == ["alpha/m1", "alpha/m2"]
    assert dialog.backend_hint.text() == "/opt/alpha (v1.0)"
    assert "lists" in dialog.model_hint.text()
    # the probe gets the configured install, so a binary set under "LLM backends" is the one asked
    assert fakes["alpha"].probed == [{"binary": "/opt/alpha", "options": {"agent": "plan"}}]
    _select(qtbot, dialog, "slow")
    assert dialog.backend_combo.currentText() == "beta"
    assert "suggestions only" in dialog.model_hint.text()
    # probed once per backend and dialog
    _select(qtbot, dialog, "fast")
    assert len(fakes["alpha"].probed) == 1


def test_a_backend_that_cannot_be_run_says_so(qtbot: QtBot, path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_backends(monkeypatch, alpha=fake_backend("alpha", ALPHA_FIELDS, version=None))
    _write(path, {"connections": {"c": {"backend": "alpha", "model": "typed/model"}}})
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    assert dialog.backend_hint.text().startswith("NOT FOUND: alpha")
    assert dialog.model_combo.count() == 0
    assert dialog.model_combo.currentText() == "typed/model"


def test_the_ui_stays_responsive_while_a_backend_is_probed(
    qtbot: QtBot, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = threading.Event()
    install_fake_backends(monkeypatch, alpha=fake_backend("alpha", ALPHA_FIELDS, gate=gate))
    _write(path, {"connections": {"c": {"backend": "alpha", "model": "x"}}})
    dialog = open_llm_dialog(None, "connections", path)
    assert isinstance(dialog, ConnectionsDialog)
    _register(qtbot, dialog)
    assert dialog.probes_running()
    assert dialog.backend_hint.text() == "Querying alpha…"
    gate.set()
    _settle(qtbot, dialog)
    assert dialog.backend_hint.text() == "alpha (v1.0)"


def test_a_late_probe_result_of_another_backend_is_not_shown(
    qtbot: QtBot, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = threading.Event()
    install_fake_backends(
        monkeypatch,
        alpha=fake_backend("alpha", ALPHA_FIELDS, gate=gate),
        beta=fake_backend("beta", BETA_FIELDS, models=["b1"]),
    )
    _write(path, {"connections": {"c": {"backend": "alpha"}}})
    dialog = open_llm_dialog(None, "connections", path)
    assert isinstance(dialog, ConnectionsDialog)
    _register(qtbot, dialog)
    dialog.backend_combo.setCurrentText("beta")
    qtbot.waitUntil(lambda: dialog.backend_hint.text() == "beta (v1.0)", timeout=5000)
    gate.set()
    _settle(qtbot, dialog)
    assert dialog.backend_hint.text() == "beta (v1.0)"
    assert [dialog.model_combo.itemText(i) for i in range(dialog.model_combo.count())] == ["b1"]


def test_switching_the_backend_rebuilds_the_fields_and_remembers_what_was_typed(qtbot: QtBot, path: str) -> None:
    _write(path, SAMPLE)
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    agent = dialog.fields.widgets["agent"]
    assert isinstance(agent, QLineEdit)
    agent.setText("build")
    dialog.backend_combo.setCurrentText("beta")
    _settle(qtbot, dialog)
    assert dialog.dirty
    assert list(dialog.fields.widgets) == ["system"]
    assert "beta" in dialog.options_label.text()
    dialog.backend_combo.setCurrentText("alpha")
    assert dialog.fields.texts()["agent"] == "build"
    assert dialog.fields.texts()["effort"] == "low"


def test_save_writes_the_edited_connection_and_only_the_chosen_backends_settings(
    qtbot: QtBot, path: str, dialog_answers: DialogRecorder
) -> None:
    _write(path, SAMPLE)
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    saved = []
    dialog.saved.connect(lambda: saved.append(True))
    _select(qtbot, dialog, "slow")
    dialog.model_combo.setEditText("beta/new")
    dialog.timeout_edit.setText("")
    system = dialog.fields.widgets["system"]
    assert isinstance(system, QLineEdit)
    system.setText("terse")
    dialog.env_text.setPlainText("K=V\n")
    assert dialog.save()
    assert saved == [True] and not dialog.dirty
    assert dialog.status.text() == "Saved to " + path
    written = _read(path)
    assert written["connections"]["slow"] == {
        "description": "",
        "backend": "beta",
        "model": "beta/new",
        "extra_args": [],
        "env": {"K": "V"},
        "backend_options": {"system": "terse"},
    }
    assert written["connections"]["fast"] == SAMPLE["connections"]["fast"]  # untouched
    assert written["backends"] == SAMPLE["backends"]
    assert dialog_answers.calls == []


def test_a_cleared_timeout_is_removed_and_inherits_the_run_timeout(qtbot: QtBot, path: str) -> None:
    _write(path, SAMPLE)
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    dialog.timeout_edit.setText("")
    assert dialog.save()
    assert "timeout" not in _read(path)["connections"]["fast"]


@pytest.mark.parametrize(
    "edit, fragment",
    [
        (lambda d: d.timeout_edit.setText("soon"), "timeout must be a number"),
        (lambda d: d.env_text.setPlainText("NOEQUALS"), "not KEY=VALUE"),
    ],
)
def test_invalid_input_is_refused_and_the_file_unchanged(
    qtbot: QtBot, path: str, dialog_answers: DialogRecorder, edit: Any, fragment: str
) -> None:
    _write(path, SAMPLE)
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    edit(dialog)
    dialog.mark_dirty()
    assert not dialog.save()
    assert fragment in dialog_answers.messages("show_error")[-1]
    assert _read(path) == SAMPLE


def test_an_unknown_choice_is_kept_in_the_field_and_named_on_save(
    qtbot: QtBot, path: str, dialog_answers: DialogRecorder
) -> None:
    config = json.loads(json.dumps(SAMPLE))
    config["connections"]["fast"]["backend_options"]["effort"] = "extreme"
    _write(path, config)
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    effort = dialog.fields.widgets["effort"]
    assert isinstance(effort, QComboBox) and effort.currentText() == "extreme"
    assert not dialog.save()
    assert "does not accept" in dialog_answers.messages("show_error")[-1]


def test_an_invalid_editor_keeps_its_item_selected(qtbot: QtBot, path: str, dialog_answers: DialogRecorder) -> None:
    _write(path, SAMPLE)
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    dialog.timeout_edit.setText("-5")
    dialog.listbox.setCurrentRow(1)
    assert dialog.current == "fast"
    assert dialog.listbox.currentRow() == 0
    assert "negative" in dialog_answers.messages("show_error")[-1]


def test_edits_survive_switching_items_until_save(qtbot: QtBot, path: str) -> None:
    _write(path, SAMPLE)
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    dialog.description_edit.setText("renamed")
    dialog.mark_dirty()
    _select(qtbot, dialog, "slow")
    _select(qtbot, dialog, "fast")
    assert dialog.description_edit.text() == "renamed"
    assert _read(path) == SAMPLE  # not saved yet
    assert dialog.save()
    assert _read(path)["connections"]["fast"]["description"] == "renamed"


def test_add_copy_and_remove(qtbot: QtBot, path: str, dialog_answers: DialogRecorder) -> None:
    _write(path, SAMPLE)
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    dialog_answers.answer("ask_string", "fast", "new")  # a taken name is refused and asked again
    assert dialog.add_button is not None
    dialog.add_button.click()
    _settle(qtbot, dialog)
    assert "'fast' already exists." in dialog_answers.messages("show_error")
    assert _names(dialog) == ["fast", "new", "slow"] and dialog.current == "new"
    assert dialog.backend_combo.currentText() == "alpha"  # the first installed backend
    dialog_answers.answer("ask_string", "fast_copy")
    _select(qtbot, dialog, "fast")
    assert dialog.copy_button is not None
    dialog.copy_button.click()
    _settle(qtbot, dialog)
    assert dialog.current == "fast_copy" and dialog.description_edit.text() == "the cheap one"
    dialog_answers.answer("ask_yes_no", False, True)
    assert dialog.remove_button is not None
    dialog.remove_button.click()
    assert "fast_copy" in _names(dialog)
    dialog.remove_button.click()
    _settle(qtbot, dialog)
    assert _names(dialog) == ["fast", "new", "slow"]
    assert dialog.save()
    assert sorted(_read(path)["connections"]) == ["fast", "new", "slow"]
    assert _read(path)["connections"]["new"]["backend"] == "alpha"


def test_cancelled_name_adds_nothing(qtbot: QtBot, path: str, dialog_answers: DialogRecorder) -> None:
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    assert _names(dialog) == [] and not dialog.editor.isEnabled()
    assert dialog.copy_button is not None and not dialog.copy_button.isEnabled()
    dialog_answers.answer("ask_string", None)
    assert dialog.add_button is not None
    dialog.add_button.click()
    assert _names(dialog) == [] and not dialog.dirty


def test_saving_keeps_what_the_backends_dialog_saved_meanwhile(qtbot: QtBot, path: str) -> None:
    _write(path, SAMPLE)
    connections: ConnectionsDialog = _open(qtbot, "connections", path)
    backends: BackendsDialog = _open(qtbot, "backends", path)
    backends.binary_edit.setText("/usr/local/alpha")
    backends.mark_dirty()
    assert backends.save()
    connections.description_edit.setText("edited")
    connections.mark_dirty()
    assert connections.save()
    written = _read(path)
    assert written["backends"]["alpha"]["binary"] == "/usr/local/alpha"
    assert written["connections"]["fast"]["description"] == "edited"


def test_an_unreadable_file_is_reported_instead_of_opening(path: str, dialog_answers: DialogRecorder) -> None:
    Path(path).parent.mkdir(parents=True)
    Path(path).write_text("{not json")
    assert open_llm_dialog(None, "connections", path) is None
    assert "Could not read" in dialog_answers.messages("show_error")[0]


def test_save_refuses_when_the_file_became_unreadable(qtbot: QtBot, path: str, dialog_answers: DialogRecorder) -> None:
    _write(path, SAMPLE)
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    Path(path).write_text("[]")
    assert not dialog.save()
    assert "must contain a JSON object" in dialog_answers.messages("show_error")[-1]


def test_a_connection_without_backend_keeps_it_unset_unless_one_is_chosen(qtbot: QtBot, path: str) -> None:
    _write(path, {"connections": {"auto": {"model": "m"}, "other": {"backend": "beta"}}})
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    assert dialog.current == "auto" and dialog.backend_combo.currentText() == "alpha"
    assert dialog.backend_hint.text().startswith("Not set in this connection")
    _select(qtbot, dialog, "other")
    _select(qtbot, dialog, "auto")
    dialog.mark_dirty()
    assert dialog.save()
    assert _read(path)["connections"]["auto"] == {
        "description": "",
        "model": "m",
        "extra_args": [],
        "env": {},
        "backend_options": {},
    }
    dialog.backend_combo.setCurrentText("beta")
    dialog.backend_combo.setCurrentText("alpha")
    _settle(qtbot, dialog)
    assert not dialog.backend_hint.text().startswith("Not set")
    assert dialog.save()
    assert _read(path)["connections"]["auto"]["backend"] == "alpha"


# ---- leaving with unsaved edits -------------------------------------------------------------------------------


def _edited(qtbot: QtBot, path: str) -> ConnectionsDialog:
    _write(path, SAMPLE)
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    dialog.description_edit.setText("edited")
    dialog.mark_dirty()
    return dialog


def test_close_without_edits_asks_nothing(qtbot: QtBot, path: str, dialog_answers: DialogRecorder) -> None:
    dialog: ConnectionsDialog = _open(qtbot, "connections", path)
    finished = []
    dialog.finished.connect(lambda result: finished.append(result))
    dialog.close_button.click()
    assert not dialog.isVisible() and finished == [0]
    assert dialog_answers.calls == []


@pytest.mark.parametrize("how", ["button", "escape", "close"])
def test_cancel_keeps_the_dialog_open_however_it_is_closed(
    qtbot: QtBot, path: str, dialog_answers: DialogRecorder, how: str
) -> None:
    dialog = _edited(qtbot, path)
    dialog_answers.answer("ask_save_discard", None)
    if how == "button":
        dialog.close_button.click()
    elif how == "escape":
        qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    else:
        assert not dialog.close()
    assert dialog.isVisible() and dialog.dirty
    assert dialog_answers.titles("ask_save_discard") == ["Unsaved changes"]


def test_escape_with_discard_closes_without_saving(qtbot: QtBot, path: str, dialog_answers: DialogRecorder) -> None:
    dialog = _edited(qtbot, path)
    dialog_answers.answer("ask_save_discard", dialogs.DISCARD)
    qtbot.keyClick(dialog, Qt.Key.Key_Escape)
    assert not dialog.isVisible()
    assert _read(path) == SAMPLE
    assert len(dialog_answers.calls) == 1  # asked once, not again by the close that follows


def test_close_with_save_writes_then_closes(qtbot: QtBot, path: str, dialog_answers: DialogRecorder) -> None:
    dialog = _edited(qtbot, path)
    dialog_answers.answer("ask_save_discard", dialogs.SAVE)
    assert dialog.close()
    assert not dialog.isVisible()
    assert _read(path)["connections"]["fast"]["description"] == "edited"


def test_close_with_a_refused_save_stays_open(qtbot: QtBot, path: str, dialog_answers: DialogRecorder) -> None:
    dialog = _edited(qtbot, path)
    dialog.timeout_edit.setText("never")
    dialog_answers.answer("ask_save_discard", dialogs.SAVE)
    assert not dialog.close()
    assert dialog.isVisible()


def test_enter_in_a_field_does_not_press_save_or_close(qtbot: QtBot, path: str, dialog_answers: DialogRecorder) -> None:
    dialog = _edited(qtbot, path)
    qtbot.keyClick(dialog.description_edit, Qt.Key.Key_Return)
    assert dialog.isVisible() and dialog.dirty
    assert dialog_answers.calls == []


# ---- backends -------------------------------------------------------------------------------------------------


def test_backends_dialog_lists_the_registry_and_shows_the_section(qtbot: QtBot, path: str) -> None:
    _write(path, {"backends": {"alpha": {"binary": "/opt/alpha", "extra_args": ["-q"], "env": {"A": "1"}}}})
    dialog: BackendsDialog = _open(qtbot, "backends", path)
    assert _names(dialog) == ["alpha", "beta"]
    assert dialog.add_button is None and dialog.remove_button is None
    assert dialog.binary_edit.text() == "/opt/alpha"
    assert dialog.args_edit.text() == "-q"
    assert dialog.env_text.toPlainText() == "A=1\n"
    assert "The alpha agent." in dialog.about.text() and "$FAKE_ALPHA" in dialog.about.text()
    assert dialog.binary_status.text() == "found: /opt/alpha (v1.0)"
    assert dialog.fields.texts() == {"agent": "", "effort": "", "auto": ""}


def test_binary_status_is_probed_after_editing_not_per_key(
    qtbot: QtBot, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    alpha = fake_backend("alpha", ALPHA_FIELDS)
    install_fake_backends(monkeypatch, alpha=alpha)
    dialog: BackendsDialog = _open(qtbot, "backends", path)
    probes = len(alpha.probed)
    qtbot.keyClicks(dialog.binary_edit, "/bin/x")
    assert len(alpha.probed) == probes
    dialog.binary_edit.editingFinished.emit()
    _settle(qtbot, dialog)
    assert alpha.probed[-1] == {"binary": "/bin/x"}
    assert dialog.binary_status.text() == "found: /bin/x (v1.0)"
    assert dialog.dirty


def test_binary_not_found_and_env_override(qtbot: QtBot, path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    install_fake_backends(monkeypatch, alpha=fake_backend("alpha", ALPHA_FIELDS, version=None))
    dialog: BackendsDialog = _open(qtbot, "backends", path)
    assert dialog.binary_status.text() == "not found: alpha could not be run"
    monkeypatch.setenv("FAKE_ALPHA", "/env/alpha")
    dialog.refresh_status()
    _settle(qtbot, dialog)
    assert dialog.binary_status.text().startswith("$FAKE_ALPHA overrides this: ")


def test_browse_sets_the_executable(qtbot: QtBot, path: str, dialog_answers: DialogRecorder) -> None:
    dialog: BackendsDialog = _open(qtbot, "backends", path)
    dialog_answers.answer("ask_open_file", "/picked/alpha")
    dialog.browse_button.click()
    _settle(qtbot, dialog)
    assert dialog.binary_edit.text() == "/picked/alpha" and dialog.dirty
    assert dialog.binary_status.text() == "found: /picked/alpha (v1.0)"


def test_backend_defaults_are_saved_as_options_and_reach_resolved_connections(qtbot: QtBot, path: str) -> None:
    _write(path, {"connections": {"c": {"backend": "alpha"}}})
    dialog: BackendsDialog = _open(qtbot, "backends", path)
    effort = dialog.fields.widgets["effort"]
    assert isinstance(effort, QComboBox)
    effort.setCurrentText("high")
    dialog.args_edit.setText("--quiet")
    dialog.mark_dirty()
    assert dialog.save()
    written = _read(path)
    assert written["backends"] == {"alpha": {"extra_args": ["--quiet"], "options": {"effort": "high"}}}
    assert written["connections"] == {"c": {"backend": "alpha"}}
    profile = llm_config.resolve_connection(llm_config.load_config(path), "c")
    assert profile["backend_options"]["effort"] == "high" and profile["extra_args"] == ["--quiet"]


def test_clearing_a_backend_removes_its_section(qtbot: QtBot, path: str) -> None:
    _write(path, {"backends": {"alpha": {"binary": "/opt/alpha"}}})
    dialog: BackendsDialog = _open(qtbot, "backends", path)
    dialog.binary_edit.setText("")
    dialog.mark_dirty()
    assert dialog.save()
    assert _read(path)["backends"] == {}


def test_backend_edits_are_kept_while_switching(qtbot: QtBot, path: str) -> None:
    dialog: BackendsDialog = _open(qtbot, "backends", path)
    dialog.binary_edit.setText("/a")
    dialog.mark_dirty()
    _select(qtbot, dialog, "beta")
    assert dialog.binary_edit.text() == "" and list(dialog.fields.widgets) == ["system"]
    _select(qtbot, dialog, "alpha")
    assert dialog.binary_edit.text() == "/a"


def test_closing_cancels_running_probes(qtbot: QtBot, path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    gate = threading.Event()
    install_fake_backends(monkeypatch, alpha=fake_backend("alpha", ALPHA_FIELDS, gate=gate))
    dialog = open_llm_dialog(None, "backends", path)
    assert isinstance(dialog, BackendsDialog)
    _register(qtbot, dialog)
    assert dialog.probes_running()
    dialog.close()
    assert not dialog.probes_running()
    gate.set()
    qtbot.wait(200)
    assert dialog.binary_status.text() == "Checking…"  # the late result is dropped


# ---- the Settings menu of the main window ------------------------------------------------------------------------


def _window(qtbot: QtBot, tmp_path: Path) -> MainWindow:
    window = MainWindow(make_arguments(tmp_path))
    qtbot.addWidget(window)
    return window


def _connection_choices(window: MainWindow) -> List[str]:
    combo = window.suggestion_check_panel.connection_combo
    choices = [combo.itemText(i) for i in range(combo.count())]
    # both panels that drive an agent offer the same connections
    repair = window.patch_repair_panel.connection_combo
    assert [repair.itemText(i) for i in range(repair.count())] == choices
    return choices


def test_settings_menu_entries(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    assert [a.text() for a in window.settings_menu.actions() if not a.isSeparator()] == [
        "LLM connections…",
        "LLM backends…",
        "Reload LLM configuration from disk",
        "Suggestion check prompts…",
    ]


@pytest.mark.parametrize("kind, cls", [("connections", ConnectionsDialog), ("backends", BackendsDialog)])
def test_menu_opens_one_dialog_over_the_projects_file(qtbot: QtBot, tmp_path: Path, kind: str, cls: type) -> None:
    window = _window(qtbot, tmp_path)
    action = window.llm_connections_action if kind == "connections" else window.llm_backends_action
    action.trigger()
    dialog = window.llm_dialogs[kind]
    assert isinstance(dialog, cls) and dialog.isVisible()
    assert dialog.path == str(tmp_path / ".discopop" / "patch_repair" / "llm_config.json")
    _settle(qtbot, dialog)
    action.trigger()
    assert window.llm_dialogs[kind] is dialog  # raised, not opened twice
    dialog.close()
    assert kind not in window.llm_dialogs


def test_saved_connections_reach_the_suggestion_check_panel(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder
) -> None:
    window = _window(qtbot, tmp_path)
    before = _connection_choices(window)
    dialog = window.open_llm_dialog("connections")
    assert isinstance(dialog, ConnectionsDialog)
    _settle(qtbot, dialog)
    dialog_answers.answer("ask_string", "mine")
    assert dialog.add_button is not None
    dialog.add_button.click()
    _settle(qtbot, dialog)
    assert _connection_choices(window) == before  # not before it is saved
    assert dialog.save()
    assert _connection_choices(window) == before + ["mine"]
    dialog.close()


def test_reload_reads_a_file_edited_outside_the_gui(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    before = _connection_choices(window)
    _write(llm_logic.config_path(window.arguments.dot_dp), {"connections": {"a": {}, "b": {}}})
    window.reload_llm_action.trigger()
    assert _connection_choices(window) == before + ["a", "b"]
    assert window.status.text() == "Reloaded the LLM configuration: 2 connection(s)"


def test_reload_names_an_unreadable_file(qtbot: QtBot, tmp_path: Path) -> None:
    window = _window(qtbot, tmp_path)
    path = Path(llm_logic.config_path(window.arguments.dot_dp))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{")
    window.reload_llm_configuration()
    assert "Could not read the LLM configuration" in window.status.text()


def test_an_unreadable_file_opens_no_dialog(qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder) -> None:
    window = _window(qtbot, tmp_path)
    path = Path(llm_logic.config_path(window.arguments.dot_dp))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{")
    assert window.open_llm_dialog("backends") is None
    assert window.llm_dialogs == {}
    assert dialog_answers.titles("show_error") == ["LLM backends"]


def test_closing_the_window_asks_about_unsaved_llm_settings(
    qtbot: QtBot, tmp_path: Path, dialog_answers: DialogRecorder
) -> None:
    window = _window(qtbot, tmp_path)
    window.show()
    dialog = window.open_llm_dialog("backends")
    assert isinstance(dialog, BackendsDialog)
    _settle(qtbot, dialog)
    dialog.binary_edit.setText("/x")
    dialog.mark_dirty()
    dialog_answers.answer("ask_save_discard", None, dialogs.DISCARD)
    assert not window.close()
    assert window.isVisible() and dialog.isVisible()
    assert window.close()
    assert not dialog.isVisible()

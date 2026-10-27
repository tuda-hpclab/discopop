# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.configurations.execution_time import (
    DEFAULT_EXECUTION_TIME_REGEX,
    read_execution_time_settings,
)
from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.help_dialogs import HelpDialog
from discopop_library.ProjectManager.qt_gui.panels.editor_panel import EditorPanel
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services.project_state import (
    ConfigChanged,
    ConfigurationsChanged,
    ProjectState,
    ResultsChanged,
)

CONFIG = "tiny"


class FakeTabs:
    """The part of the main window the editor uses."""

    def __init__(self) -> None:
        self.titles: Dict[str, str] = {}
        self.current = "Editor"

    def show_tab(self, name: str) -> None:
        self.current = name

    def current_tab(self) -> str:
        return self.current

    def set_tab_enabled(self, name: str, enabled: bool, tooltip: str = "") -> None:
        pass

    def set_tab_title(self, name: str, title: str) -> None:
        self.titles[name] = title


@pytest.fixture
def panel(qtbot: QtBot, tmp_path: Path) -> EditorPanel:
    arguments = make_arguments(tmp_path)
    status = StatusLine()
    qtbot.addWidget(status)
    created = EditorPanel(arguments, ProjectState(), status, FakeTabs())
    qtbot.addWidget(created)
    config_dir = Path(arguments.project_config_dir, CONFIG)
    config_dir.mkdir(parents=True)
    (config_dir / "execute.sh").write_text("#!/bin/bash\n./prog\n")
    return created


def tabs(panel: EditorPanel) -> FakeTabs:
    assert isinstance(panel.tabs, FakeTabs)
    return panel.tabs


def config_dir(panel: EditorPanel) -> Path:
    return Path(panel.arguments.project_config_dir, CONFIG)


def select(panel: EditorPanel, config: Any = CONFIG) -> None:
    panel.project_state.current_config = config
    panel.project_state.publish(ConfigChanged(config))


def record(panel: EditorPanel, event_type: type) -> List[object]:
    events: List[object] = []
    panel.project_state.subscribe(event_type, events.append)
    return events


def type_into(panel: EditorPanel, name: str, text: str) -> None:
    """Replace the text as a user does (``setPlainText`` would reset the modified flag)."""
    editor = panel.editors[name]
    editor.selectAll()
    editor.insertPlainText(text)


def test_selecting_a_configuration_shows_its_files(panel: EditorPanel) -> None:
    results = record(panel, ResultsChanged)
    select(panel)
    assert panel.editors["execute.sh"].text() == "#!/bin/bash\n./prog\n"
    assert not panel.editors["execute.sh"].isReadOnly()
    # the optional files are absent: a read-only placeholder and an "Add" button
    for name in ("compile.sh", "validate.sh", "compile_validate.sh"):
        assert panel.editors[name].isReadOnly() and panel.editors[name].text().startswith("# This configuration has no")
    assert panel.compile_override_button.text() == "Add Override"
    assert panel.validate_script_button.text() == "Add validate.sh"
    assert [panel.notebook.tabText(i) for i in range(4)] == [
        "execute.sh",
        "compile.sh (override)",
        "validate.sh",
        "compile_validate.sh (override)",
    ]
    assert not panel.has_unsaved_changes() and tabs(panel).titles["Editor"] == "Editor"
    assert results == [ResultsChanged()]


def test_a_missing_execute_script_is_reported_in_the_editor(panel: EditorPanel) -> None:
    (config_dir(panel) / "execute.sh").unlink()
    select(panel)
    assert panel.editors["execute.sh"].text().startswith("File not found: ")


def test_deselecting_clears_the_editors(panel: EditorPanel) -> None:
    select(panel)
    select(panel, None)
    assert all(editor.text() == "" and editor.isReadOnly() for editor in panel.editors.values())
    assert not panel.has_unsaved_changes()


def test_editing_marks_the_tabs_and_saving_clears_them(panel: EditorPanel) -> None:
    select(panel)
    changed = record(panel, ConfigurationsChanged)
    type_into(panel, "execute.sh", "#!/bin/bash\n./prog 100\n\n")
    assert panel.notebook.tabText(0) == "execute.sh *" and tabs(panel).titles["Editor"] == "Editor *"
    assert panel.has_unsaved_changes()
    panel.save_button.click()
    assert (config_dir(panel) / "execute.sh").read_text() == "#!/bin/bash\n./prog 100"
    assert panel.notebook.tabText(0) == "execute.sh" and tabs(panel).titles["Editor"] == "Editor"
    assert panel.status.text() == "Saved execute.sh" and panel.status.color == widgets.STATUS_OK
    assert changed == [ConfigurationsChanged()]


def test_saving_without_changes_or_configuration(panel: EditorPanel) -> None:
    panel.save()
    assert panel.status.text() == "No configuration selected" and panel.status.color == widgets.STATUS_FAIL
    select(panel)
    changed = record(panel, ConfigurationsChanged)
    panel.save()
    assert panel.status.text() == "No changes to save" and changed == []


def test_a_write_error_keeps_the_changes(panel: EditorPanel) -> None:
    select(panel)
    type_into(panel, "execute.sh", "x")
    os.chmod(config_dir(panel) / "execute.sh", 0o400)
    if os.access(config_dir(panel) / "execute.sh", os.W_OK):
        pytest.skip("running with privileges that ignore file permissions")
    assert not panel.save()
    assert panel.status.text().startswith("Error saving file execute.sh") and panel.has_unsaved_changes()


def test_saving_a_compile_script_without_compiler_variables_warns(
    panel: EditorPanel, dialog_answers: DialogRecorder
) -> None:
    select(panel)
    panel.compile_override_button.click()
    type_into(panel, "compile.sh", "gcc -o prog main.c")
    panel.save()
    assert dialog_answers.titles("show_warning") == ["Compilation Script Warning"]
    type_into(panel, "compile.sh", "$CC -o prog main.c")
    panel.save()
    assert dialog_answers.titles("show_warning") == ["Compilation Script Warning"]


def test_the_compile_override_is_seeded_from_the_shared_script_and_removed_on_request(
    panel: EditorPanel, dialog_answers: DialogRecorder
) -> None:
    shared = Path(panel.arguments.project_config_dir, "compile.sh")
    shared.write_text("#!/bin/bash\n$CXX main.cpp\n")
    select(panel)
    changed = record(panel, ConfigurationsChanged)
    panel.compile_override_button.click()
    override = config_dir(panel) / "compile.sh"
    assert override.exists() and "$CXX main.cpp" in override.read_text()
    assert panel.editors["compile.sh"].text() == override.read_text() and not panel.editors["compile.sh"].isReadOnly()
    assert panel.compile_override_button.text() == "Remove Override"
    assert panel.status.text() == "Added compile.sh override for this configuration"
    assert changed == [ConfigurationsChanged()]

    dialog_answers.answer("ask_yes_no", False, True)
    panel.compile_override_button.click()
    assert override.exists()
    panel.compile_override_button.click()
    assert not override.exists() and panel.compile_override_button.text() == "Add Override"
    assert panel.editors["compile.sh"].isReadOnly()
    assert panel.status.text() == "Removed compile.sh override for this configuration"
    assert dialog_answers.titles("ask_yes_no") == ["Remove Override", "Remove Override"]


def test_validate_script_is_seeded_from_execute_sh(panel: EditorPanel, dialog_answers: DialogRecorder) -> None:
    select(panel)
    panel.validate_script_button.click()
    validate = config_dir(panel) / "validate.sh"
    assert validate.read_text() == "#!/bin/bash\n./prog\n"
    assert panel.validate_script_button.text() == "Remove validate.sh"
    dialog_answers.answer("ask_yes_no", True)
    panel.validate_script_button.click()
    assert not validate.exists() and panel.validate_script_button.text() == "Add validate.sh"
    assert panel.status.text() == "Removed validate.sh for this configuration"


def test_a_validation_build_override_without_validate_sh_is_marked_ignored(
    panel: EditorPanel, dialog_answers: DialogRecorder
) -> None:
    Path(panel.arguments.project_config_dir, "compile.sh").write_text("$CC x.c\n")
    select(panel)
    panel.validation_compile_override_button.click()
    # warned that nothing uses it yet, seeded from the compile script of execute.sh
    assert dialog_answers.titles("show_warning") == ["No validate.sh"]
    assert "$CC x.c" in (config_dir(panel) / "compile_validate.sh").read_text()
    assert panel.notebook.tabText(3) == "compile_validate.sh (ignored)"
    panel.validate_script_button.click()
    assert panel.notebook.tabText(3) == "compile_validate.sh (override)"
    assert panel.validation_compile_override_button.text() == "Remove Override"
    dialog_answers.answer("ask_yes_no", True)
    panel.validation_compile_override_button.click()
    assert not (config_dir(panel) / "compile_validate.sh").exists()


def test_a_refresh_of_the_selection_keeps_the_edits_but_another_configuration_replaces_them(
    panel: EditorPanel,
) -> None:
    other = Path(panel.arguments.project_config_dir, "other")
    other.mkdir()
    (other / "execute.sh").write_text("other\n")
    select(panel)
    type_into(panel, "execute.sh", "edited")
    select(panel)
    assert panel.editors["execute.sh"].text() == "edited"
    select(panel, "other")
    assert panel.editors["execute.sh"].text() == "other\n" and not panel.has_unsaved_changes()
    assert tabs(panel).titles["Editor"] == "Editor"


def test_the_execution_time_setting_is_loaded_without_counting_as_an_edit(panel: EditorPanel) -> None:
    select(panel)
    assert not panel.execution_time_enabled.isChecked()
    assert panel.execution_time_regex.text() == DEFAULT_EXECUTION_TIME_REGEX
    assert not panel.execution_time_regex.isEnabled() and not panel.execution_time_test_button.isEnabled()
    (config_dir(panel) / "execution_time.json").write_text(json.dumps({"enabled": True, "regex": "T: (\\d+)"}))
    select(panel)
    assert panel.execution_time_enabled.isChecked() and panel.execution_time_regex.text() == "T: (\\d+)"
    assert panel.execution_time_regex.isEnabled() and not panel.has_unsaved_changes()


def test_the_execution_time_setting_is_saved_with_the_scripts(panel: EditorPanel) -> None:
    select(panel)
    changed = record(panel, ConfigurationsChanged)
    panel.execution_time_enabled.setChecked(True)
    assert panel.execution_time_modified and panel.notebook.tabText(0) == "execute.sh *"
    assert tabs(panel).titles["Editor"] == "Editor *"
    panel.execution_time_regex.setText("Total:\\s*([0-9.]+)")
    panel.save()
    assert read_execution_time_settings(str(config_dir(panel))) == (True, "Total:\\s*([0-9.]+)")
    assert panel.status.text() == "Saved execution time setting"
    assert panel.notebook.tabText(0) == "execute.sh" and tabs(panel).titles["Editor"] == "Editor"
    assert changed == [ConfigurationsChanged()]


def test_an_invalid_pattern_is_rejected_and_nothing_is_written(
    panel: EditorPanel, dialog_answers: DialogRecorder
) -> None:
    select(panel)
    type_into(panel, "execute.sh", "changed")
    panel.execution_time_enabled.setChecked(True)
    panel.execution_time_regex.setText("(unclosed")
    assert not panel.save()
    assert dialog_answers.titles("show_error") == ["Invalid execution time pattern"]
    assert not (config_dir(panel) / "execution_time.json").exists()
    assert (config_dir(panel) / "execute.sh").read_text() == "#!/bin/bash\n./prog\n"
    assert panel.has_unsaved_changes()


def test_the_pattern_is_tested_against_the_last_recorded_run(panel: EditorPanel) -> None:
    select(panel)
    panel.execution_time_enabled.setChecked(True)
    panel.execution_time_test_button.click()
    assert panel.execution_time_test_label.text().startswith("No recorded output")
    panel.execution_time_regex.setText("(unclosed")
    panel.execution_time_test_button.click()
    assert panel.execution_time_test_label.text().startswith("✗ The pattern is ")
    Path(panel.arguments.project_dir, "execution_results.json").write_text(
        json.dumps({CONFIG: {"execute.sh": {"seq_settings.json": [{"stdout": "Total: 1.25 s\n", "stderr": ""}]}}})
    )
    panel.execution_time_regex.setText("Total:\\s*([0-9.]+)")
    panel.execution_time_test_button.click()
    assert panel.execution_time_test_label.text() == "✓ Matched in the last recorded run: 1.25 s"
    panel.execution_time_regex.setText("Nothing: ([0-9]+)")
    panel.execution_time_test_button.click()
    assert panel.execution_time_test_label.text() == "✗ No match in the output of the last recorded run."


def test_confirm_leave_asks_only_with_unsaved_changes(panel: EditorPanel, dialog_answers: DialogRecorder) -> None:
    select(panel)
    assert panel.confirm_leave() and dialog_answers.calls == []
    type_into(panel, "execute.sh", "saved on request")
    dialog_answers.answer("ask_yes_no", True, False)
    assert panel.confirm_leave()
    assert (config_dir(panel) / "execute.sh").read_text() == "saved on request"
    type_into(panel, "execute.sh", "discarded")
    assert panel.confirm_leave()
    assert (config_dir(panel) / "execute.sh").read_text() == "saved on request"
    assert dialog_answers.titles("ask_yes_no") == ["Unsaved Changes", "Unsaved Changes"]


def test_confirm_leave_keeps_the_configuration_when_saving_fails(
    panel: EditorPanel, dialog_answers: DialogRecorder
) -> None:
    select(panel)
    panel.execution_time_enabled.setChecked(True)
    panel.execution_time_regex.setText("(unclosed")
    dialog_answers.answer("ask_yes_no", True)
    assert not panel.confirm_leave()


def test_the_save_shortcut_depends_on_the_tab_in_front(panel: EditorPanel) -> None:
    select(panel)
    type_into(panel, "execute.sh", "ctrl s")
    tabs(panel).current = "Report"
    panel.save_shortcut()
    assert (config_dir(panel) / "execute.sh").read_text() == "#!/bin/bash\n./prog\n"
    tabs(panel).current = "Editor"
    panel.save_shortcut()
    assert (config_dir(panel) / "execute.sh").read_text() == "ctrl s"


def test_the_help_buttons_open_the_help_of_their_file(qtbot: QtBot, panel: EditorPanel) -> None:
    panel.show()
    for index, title in enumerate(
        ("execute.sh Help", "compile.sh Help", "validate.sh Help", "compile_validate.sh Help")
    ):
        panel.notebook.setCurrentIndex(index)
        page = panel.notebook.widget(index)
        assert page is not None
        buttons = [b for b in page.findChildren(widgets.QPushButton) if b.text() == "Help"]  # type: ignore[attr-defined]
        buttons[0].click()
        dialogs_open = [d for d in panel.findChildren(HelpDialog) if d.windowTitle() == title]
        assert len(dialogs_open) == 1 and dialogs_open[0].isVisible()
        assert dialogs_open[0].text.toPlainText()
        dialogs_open[0].ok_button.click()


def test_the_compilation_editor_opens_once_and_is_reused(panel: EditorPanel) -> None:
    panel.open_compilation_editor()
    window = panel._compilation_editor
    assert window is not None and window.isVisible()
    panel.open_compilation_editor()
    assert panel._compilation_editor is window
    window.close()
    panel.open_compilation_editor()
    assert window.isVisible()
    panel.cancel_jobs()


def test_the_save_shortcut_saves_the_compilation_editor_when_it_is_in_front(
    panel: EditorPanel, monkeypatch: pytest.MonkeyPatch
) -> None:
    select(panel)
    panel.open_compilation_editor()
    window = panel._compilation_editor
    assert window is not None
    saved: List[str] = []

    def fake_save() -> bool:
        saved.append("compilation")
        return True

    monkeypatch.setattr(window, "save", fake_save)
    monkeypatch.setattr(window, "isActiveWindow", lambda: True)
    panel.save_shortcut()
    assert saved == ["compilation"]


def test_a_refresh_of_the_selection_keeps_the_cursor_and_reloads_what_changed_on_disk(panel: EditorPanel) -> None:
    select(panel)
    type_into(panel, "execute.sh", "#!/bin/bash\n./prog --big\n")
    assert panel.save()
    editor = panel.editors["execute.sh"]
    cursor = editor.textCursor()
    cursor.setPosition(12)
    editor.setTextCursor(cursor)
    # the configuration list republishes the selection after the save
    select(panel)
    assert editor.textCursor().position() == 12 and editor.document().isUndoAvailable()
    # a file changed by someone else is shown
    (config_dir(panel) / "execute.sh").write_text("#!/bin/bash\n./other\n")
    select(panel)
    assert editor.text() == "#!/bin/bash\n./other\n"

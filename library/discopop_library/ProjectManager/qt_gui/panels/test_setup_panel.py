# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""The Setup stage; the test compilation runs ``compile.sh`` for real but records no result."""

import json
import os
import stat
from pathlib import Path
from typing import Any, Callable, Dict, List
from unittest import mock

import pytest
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.qt_gui import widgets
from discopop_library.ProjectManager.qt_gui.panels import setup_panel
from discopop_library.ProjectManager.qt_gui.panels.setup_panel import SetupPanel
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.services.jobs import WorkEvent, WorkFinished
from discopop_library.ProjectManager.services.project_state import ConfigurationsChanged, ProjectState

SETTINGS = {"CC": "clang", "CXX": "clang++", "CFLAGS": "-O2", "CXXFLAGS": "-O2"}


class FakeTabs:
    def __init__(self) -> None:
        self.titles: Dict[str, str] = {}

    def show_tab(self, name: str) -> None:
        pass

    def current_tab(self) -> str:
        return "Setup"

    def set_tab_enabled(self, name: str, enabled: bool, tooltip: str = "") -> None:
        pass

    def set_tab_title(self, name: str, title: str) -> None:
        self.titles[name] = title


@pytest.fixture
def editor(qtbot: QtBot, tmp_path: Path) -> SetupPanel:
    arguments = make_arguments(tmp_path)
    status = StatusLine()
    qtbot.addWidget(status)
    created = SetupPanel(arguments, ProjectState(), status, FakeTabs())
    qtbot.addWidget(created)
    return created


def comp_dir(editor: SetupPanel) -> Path:
    return Path(editor.arguments.project_config_dir)


def write_files(editor: SetupPanel, script: str = "#!/bin/bash\necho compiled\n") -> None:
    (comp_dir(editor) / "compile.sh").write_text(script)
    os.chmod(comp_dir(editor) / "compile.sh", 0o755)
    (comp_dir(editor) / "seq_settings.json").write_text(json.dumps(SETTINGS))
    editor.load_files()


def type_into(editor: SetupPanel, name: str, text: str) -> None:
    ed = editor.editors[name]
    ed.selectAll()
    ed.insertPlainText(text)


def tab_titles(editor: SetupPanel) -> List[str]:
    return [editor.notebook.tabText(i) for i in range(editor.notebook.count())]


def recorded_changes(editor: SetupPanel) -> List[object]:
    events: List[object] = []
    editor.project_state.subscribe(ConfigurationsChanged, events.append)
    return events


def test_the_files_are_shown_with_placeholders_and_disabled_derived_tabs(editor: SetupPanel) -> None:
    write_files(editor)
    assert tab_titles(editor) == [
        "compile.sh",
        "compile_validate.sh",
        "seq_settings.json",
        "dp_settings.json",
        "hd_settings.json",
        "par_settings.json",
    ]
    # settings are shown as formatted JSON
    assert editor.editors["seq_settings.json"].text() == json.dumps(SETTINGS, indent=2)
    assert editor.editors["compile_validate.sh"].isReadOnly()
    assert editor.editors["compile_validate.sh"].text().startswith("# This project has no shared compile_validate.sh")
    assert editor.shared_validation_compile_button.text() == "Add"
    for index in (3, 4, 5):
        assert not editor.notebook.isTabEnabled(index)
        assert "Use 'Derive Settings'" in editor.notebook.tabToolTip(index)
    assert editor.notebook.tabToolTip(0) == "Compilation instructions"


def test_a_missing_file_is_reported_in_its_editor(editor: SetupPanel) -> None:
    assert editor.editors["compile.sh"].text() == f"File not found: {comp_dir(editor) / 'compile.sh'}"


def test_the_buttons_follow_the_tab_in_front(editor: SetupPanel) -> None:
    editor.show()
    assert editor.test_compilation_button.isVisible() and not editor.derive_button.isVisible()
    # no compile.sh and seq_settings.json yet
    assert not editor.test_compilation_button.isEnabled()
    write_files(editor)
    assert editor.test_compilation_button.isEnabled()
    editor.notebook.setCurrentIndex(2)
    assert editor.derive_button.isVisible() and not editor.test_compilation_button.isVisible()
    editor.notebook.setCurrentIndex(1)
    assert not editor.derive_button.isVisible() and not editor.test_compilation_button.isVisible()


def test_unsaved_changes_mark_the_tab_and_block_deriving(editor: SetupPanel) -> None:
    write_files(editor)
    assert editor.derive_button.isEnabled() and editor.derive_button.toolTip() == ""
    type_into(editor, "compile.sh", "$CC x.c")
    assert tab_titles(editor)[0] == "compile.sh *" and editor.has_unsaved_changes()
    assert isinstance(editor.tabs, FakeTabs) and editor.tabs.titles["Setup"] == "Setup *"
    assert editor.header.chip.text() == "Unsaved changes"
    assert not editor.derive_button.isEnabled()
    assert editor.derive_button.toolTip() == "Save all changes before deriving settings"


def test_saving_writes_scripts_executable_and_settings_formatted(editor: SetupPanel) -> None:
    write_files(editor)
    changed = recorded_changes(editor)
    type_into(editor, "compile.sh", "$CC x.c\n\n")
    type_into(editor, "seq_settings.json", '{"CC":"gcc"}')
    editor.save_button.click()
    assert (comp_dir(editor) / "compile.sh").read_text() == "$CC x.c"
    assert os.stat(comp_dir(editor) / "compile.sh").st_mode & stat.S_IXUSR
    assert (comp_dir(editor) / "seq_settings.json").read_text() == json.dumps({"CC": "gcc"}, indent=2)
    assert tab_titles(editor)[0] == "compile.sh" and not editor.has_unsaved_changes()
    assert editor.status.text() == "Saved compile.sh, seq_settings.json" and editor.status.color == widgets.STATUS_OK
    assert changed == [ConfigurationsChanged()]
    editor.save()
    assert editor.status.text() == "No changes to save" and len(changed) == 1


def test_the_shared_validation_build_script_is_added_and_removed(
    editor: SetupPanel, dialog_answers: DialogRecorder
) -> None:
    write_files(editor, "#!/bin/bash\n$CXX main.cpp\n")
    type_into(editor, "seq_settings.json", '{"CC": "gcc"}')
    changed = recorded_changes(editor)
    editor.shared_validation_compile_button.click()
    script = comp_dir(editor) / "compile_validate.sh"
    assert "$CXX main.cpp" in script.read_text() and editor.shared_validation_compile_button.text() == "Remove"
    assert not editor.editors["compile_validate.sh"].isReadOnly()
    assert editor.status.text() == "Added shared compile_validate.sh"
    # the unsaved edit of another tab survives
    assert editor.editors["seq_settings.json"].document().isModified()

    dialog_answers.answer("ask_yes_no", False, True)
    editor.shared_validation_compile_button.click()
    assert script.exists()
    editor.shared_validation_compile_button.click()
    assert not script.exists() and editor.shared_validation_compile_button.text() == "Add"
    assert editor.editors["compile_validate.sh"].isReadOnly()
    assert editor.status.text() == "Removed shared compile_validate.sh"
    assert changed == [ConfigurationsChanged(), ConfigurationsChanged()]


def test_derive_creates_the_derived_settings_and_enables_their_tabs(editor: SetupPanel) -> None:
    write_files(editor)
    changed = recorded_changes(editor)
    editor.derive_button.click()
    for name in ("dp_settings.json", "hd_settings.json", "par_settings.json"):
        assert (comp_dir(editor) / name).exists()
        assert editor.notebook.isTabEnabled(editor.tab_index[name])
        assert json.loads(editor.editors[name].text())
    assert json.loads(editor.editors["dp_settings.json"].text())["CC"] == "discopop_cc"
    assert editor.status.text() == "Derived settings created successfully"
    assert changed == [ConfigurationsChanged()]


def test_a_failing_derive_is_reported(editor: SetupPanel) -> None:
    editor.derive_settings()
    assert editor.status.text().startswith("Error deriving settings:") and editor.status.color == widgets.STATUS_FAIL


def test_the_test_compilation_records_no_result(qtbot: QtBot, editor: SetupPanel) -> None:
    write_files(editor)
    editor.test_compilation_button.click()
    assert editor.test_compilation_button.text() == "⟳ Testing..." and not editor.test_compilation_button.isEnabled()
    assert editor.status.text() == "Running compilation test..." and editor.status.color == widgets.STATUS_BUSY
    qtbot.waitUntil(lambda: editor.test_compilation_button.text() == "Test Compilation", timeout=10000)
    assert "Compilation successful" in editor.status.text() and editor.status.color == widgets.STATUS_OK
    assert editor.test_compilation_button.isEnabled()
    assert "Success" in editor.console.text() and "compiled" in editor.console.text()
    assert editor.header.chip.text().startswith("Compiles (")
    results_path = Path(editor.arguments.project_dir, "execution_results.json")
    if results_path.exists():
        assert json.loads(results_path.read_text()) == {}


def test_a_failing_test_compilation_shows_the_output(qtbot: QtBot, editor: SetupPanel) -> None:
    write_files(editor, "#!/bin/bash\necho broken >&2\nexit 3\n")
    editor.test_compilation_button.click()
    qtbot.waitUntil(lambda: editor.test_compilation_button.text() == "Test Compilation", timeout=10000)
    assert (
        editor.status.text().startswith("✗ Compilation failed (exit code: 3")
        and editor.status.color == widgets.STATUS_FAIL
    )
    assert "Failed with exit code 3" in editor.console.text() and "broken" in editor.console.text()
    assert editor.header.chip.text() == "Compilation failed (exit code 3)"


def test_the_test_compilation_saves_unsaved_scripts_first(qtbot: QtBot, editor: SetupPanel) -> None:
    write_files(editor)
    type_into(editor, "compile.sh", "#!/bin/bash\necho edited\n")
    editor.test_compilation_button.click()
    qtbot.waitUntil(lambda: editor.test_compilation_button.text() == "Test Compilation", timeout=10000)
    assert "edited" in (comp_dir(editor) / "compile.sh").read_text() and not editor.has_unsaved_changes()
    assert "edited" in editor.console.text()


def run_inline(result: Any, error: Any = None) -> Callable[..., None]:
    def start(_parent: Any, work: Callable[[Any], Any], handler: Callable[[WorkEvent], None]) -> None:
        handler(WorkFinished(result=result, error=error))

    return start


def test_a_test_compilation_that_cannot_run_is_reported(editor: SetupPanel) -> None:
    write_files(editor)
    with mock.patch.object(setup_panel, "start_work", run_inline(None)):
        editor.test_compilation()
    assert editor.status.text() == "✗ Compilation test failed: settings not found"
    with mock.patch.object(setup_panel, "start_work", run_inline(None, RuntimeError("boom"))):
        editor.test_compilation()
    assert editor.status.text() == "✗ Compilation test failed: boom"
    assert editor.test_compilation_button.text() == "Test Compilation" and editor.test_compilation_button.isEnabled()
    assert editor.console.text() == "Compilation test failed: boom\n"
    assert editor.header.chip.text() == "Test compilation failed"


def test_a_test_compilation_without_the_files_is_refused(editor: SetupPanel, dialog_answers: DialogRecorder) -> None:
    (comp_dir(editor) / "seq_settings.json").unlink(missing_ok=True)
    with mock.patch.object(setup_panel, "start_work") as start:
        editor.test_compilation()
    start.assert_not_called()
    assert dialog_answers.titles("show_error") == ["Missing File"]
    assert dialog_answers.messages("show_error") == ["compile.sh not found"]


def test_files_without_unsaved_changes_are_reloaded(qtbot: QtBot, editor: SetupPanel) -> None:
    write_files(editor)
    type_into(editor, "compile.sh", "unsaved")
    # the wizard writes the files and publishes the change
    (comp_dir(editor) / "compile.sh").write_text("#!/bin/bash\necho wizard\n")
    (comp_dir(editor) / "seq_settings.json").write_text('{"CC": "x"}')
    editor.project_state.publish(ConfigurationsChanged())
    assert editor.editors["compile.sh"].text() == "unsaved" and editor.has_unsaved_changes()
    assert '"x"' in editor.editors["seq_settings.json"].text()
    # an unchanged file keeps its cursor
    settings = editor.editors["seq_settings.json"]
    cursor = settings.textCursor()
    cursor.setPosition(3)
    settings.setTextCursor(cursor)
    editor.reload_unmodified()
    assert settings.textCursor().position() == 3


def test_showing_the_stage_reads_changed_files(qtbot: QtBot, editor: SetupPanel) -> None:
    write_files(editor)
    (comp_dir(editor) / "compile.sh").write_text("#!/bin/bash\necho outside\n")
    editor.show()
    assert "outside" in editor.editors["compile.sh"].text()


def test_a_test_compilation_opens_the_output_pane(qtbot: QtBot, editor: SetupPanel) -> None:
    write_files(editor)
    with qtbot.waitSignal(editor.output_requested, timeout=1000):
        with mock.patch.object(setup_panel, "start_work"):
            editor.test_compilation()
    assert editor.output_console() is editor.console

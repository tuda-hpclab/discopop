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
from typing import Callable, Iterator, List

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.qt_gui.wizard import ConfigurationWizard, PlaceholderScriptEditor
from discopop_library.ProjectManager.services.configurations import has_real_configuration


@pytest.fixture
def make_wizard() -> Iterator[Callable[[ProjectManagerArguments], ConfigurationWizard]]:
    """Shows wizards; they are not registered with qtbot, which would close a shown wizard before the test ends (that
    asks whether to cancel). The autouse fixture of conftest.py deletes them afterwards."""
    created: List[ConfigurationWizard] = []

    def make(arguments: ProjectManagerArguments) -> ConfigurationWizard:
        wizard = ConfigurationWizard(arguments)
        wizard.show()
        created.append(wizard)
        return wizard

    yield make
    for wizard in created:
        wizard.done(0)


@pytest.fixture
def wizard(
    make_wizard: Callable[[ProjectManagerArguments], ConfigurationWizard], tmp_path: Path
) -> ConfigurationWizard:
    return make_wizard(make_arguments(tmp_path / "project"))


def go_to(wizard: ConfigurationWizard, step: int) -> None:
    for _ in range(step):
        if wizard.currentId() >= step:
            break
        wizard.next()
    assert wizard.currentId() == step


def test_the_steps_are_titled_like_the_tk_wizard(wizard: ConfigurationWizard) -> None:
    assert wizard.currentId() == 0
    assert wizard.windowTitle() == "Configuration Assistant - Step 1 of 9: Welcome"
    assert wizard.currentPage().title() == "Step 1 of 9: Welcome"
    assert wizard.button(wizard.WizardButton.BackButton).text() == "< Back"
    assert wizard.button(wizard.WizardButton.NextButton).text() == "Next >"
    wizard.next()
    assert wizard.windowTitle() == "Configuration Assistant - Step 2 of 9: Write Permissions Check"
    wizard.back()
    assert wizard.currentId() == 0
    go_to(wizard, 8)
    assert wizard.button(wizard.WizardButton.FinishButton).text() == "Finish"


def test_the_compile_script_starts_with_a_placeholder_that_goes_at_the_first_key(
    qtbot: QtBot, wizard: ConfigurationWizard
) -> None:
    go_to(wizard, 3)
    editor = wizard.compile_sh_text
    assert isinstance(editor, PlaceholderScriptEditor)
    assert editor.text() == "#!/bin/bash\n$CXX your_code.cpp -o a.out"
    qtbot.keyClick(editor, Qt.Key.Key_X)
    assert not editor.has_placeholder
    assert editor.text() == "#!/bin/bash\nx"


def test_leaving_the_compile_script_without_compiler_variables_asks(
    wizard: ConfigurationWizard, dialog_answers: DialogRecorder
) -> None:
    go_to(wizard, 3)
    wizard.compile_sh_text.setPlainText("#!/bin/bash\ngcc a.c\n")
    dialog_answers.answer("ask_yes_no", False, True)
    wizard.next()
    assert wizard.currentId() == 3
    assert dialog_answers.titles("ask_yes_no") == ["Missing Compiler Variables"]
    wizard.next()
    assert wizard.currentId() == 4
    compile_sh = Path(wizard.arguments.project_config_dir, "compile.sh")
    assert compile_sh.read_text() == "#!/bin/bash\ngcc a.c\n" and os.access(compile_sh, os.X_OK)


def test_an_edited_compile_script_of_an_earlier_run_is_offered_again(
    make_wizard: Callable[[ProjectManagerArguments], ConfigurationWizard], tmp_path: Path
) -> None:
    arguments = make_arguments(tmp_path / "project")
    Path(arguments.project_config_dir, "compile.sh").write_text("#!/bin/bash\n$CC mine.c\n")
    Path(arguments.project_config_dir, "seq_settings.json").write_text(json.dumps({"CC": "gcc", "CXXFLAGS": "-O2"}))
    created = make_wizard(arguments)
    go_to(created, 3)
    assert not isinstance(created.compile_sh_text, PlaceholderScriptEditor)
    assert created.compile_sh_text.text() == "#!/bin/bash\n$CC mine.c\n"
    created.next()
    assert [e.text() for e in (created.cc_entry, created.cxx_entry, created.cflags_entry, created.cxxflags_entry)] == [
        "gcc",
        "clang++",
        "",
        "-O2",
    ]


def test_the_write_access_step_reports_the_parent_folder(wizard: ConfigurationWizard) -> None:
    assert "Write Access" in wizard.write_access_label.text()


def test_the_compilation_settings_are_written_and_derived(wizard: ConfigurationWizard) -> None:
    go_to(wizard, 3)
    wizard.compile_sh_text.setPlainText("#!/bin/bash\n$CXX a.cpp\n")
    wizard.next()
    wizard.cc_entry.setText("gcc")
    wizard.cxx_entry.setText("g++")
    wizard.cflags_entry.setText("-O1")
    wizard.next()
    settings = json.loads(Path(wizard.arguments.project_config_dir, "seq_settings.json").read_text())
    assert settings == {"CC": "gcc", "CXX": "g++", "CFLAGS": "-O1", "CXXFLAGS": ""}
    wizard.next()  # test compilation -> derived settings
    assert json.loads(wizard.dp_settings_text.text())["CXX"] == "discopop_cxx"
    assert json.loads(wizard.par_settings_text.text())["CXX"] == "g++"
    assert [wizard.notebook.tabText(i) for i in range(3)] == [
        "dp_settings.json",
        "hd_settings.json",
        "par_settings.json",
    ]


def test_invalid_derived_settings_keep_the_wizard_on_the_step(
    wizard: ConfigurationWizard, dialog_answers: DialogRecorder
) -> None:
    go_to(wizard, 6)
    wizard.hd_settings_text.setPlainText("{not json")
    wizard.next()
    assert wizard.currentId() == 6
    assert dialog_answers.titles("show_error") == ["Invalid JSON"]
    assert not Path(wizard.arguments.project_config_dir, "dp_settings.json").exists()
    wizard.hd_settings_text.setPlainText("{}")
    wizard.next()
    assert wizard.currentId() == 7
    assert json.loads(Path(wizard.arguments.project_config_dir, "hd_settings.json").read_text()) == {}


def test_test_compilation_runs_the_compile_script_and_shows_the_outcome(
    qtbot: QtBot, wizard: ConfigurationWizard
) -> None:
    go_to(wizard, 3)
    wizard.compile_sh_text.setPlainText("#!/bin/bash\necho compiling $CXX\n")
    wizard.next()
    wizard.next()
    assert wizard.currentId() == 5
    next_button = wizard.button(wizard.WizardButton.NextButton)
    wizard.run_test_button.click()
    assert wizard.test_status_label.text() == "Running..."
    assert not wizard.run_test_button.isEnabled() and not next_button.isEnabled()
    qtbot.waitUntil(lambda: wizard.test_status_label.text() != "Running...", timeout=20000)
    assert wizard.test_status_label.text() == "✓ Success"
    assert "Compilation succeeded" in wizard.test_output.text() and "compiling" in wizard.test_output.text()
    assert wizard.run_test_button.isEnabled() and next_button.isEnabled()
    # a test compilation is no run of a configuration
    assert not Path(wizard.arguments.project_dir, "execution_results.json").exists() or not json.loads(
        Path(wizard.arguments.project_dir, "execution_results.json").read_text()
    )


def test_a_failing_test_compilation_shows_the_exit_code(qtbot: QtBot, wizard: ConfigurationWizard) -> None:
    go_to(wizard, 3)
    wizard.compile_sh_text.setPlainText("#!/bin/bash\n# $CXX\necho broken >&2\nexit 3\n")
    wizard.next()
    wizard.next()
    wizard.run_test_button.click()
    qtbot.waitUntil(lambda: wizard.test_status_label.text() != "Running...", timeout=20000)
    assert wizard.test_status_label.text() == "✗ Failed (exit code: 3)"
    assert "stderr:\nbroken" in wizard.test_output.text()


def test_the_configuration_needs_a_name(wizard: ConfigurationWizard, dialog_answers: DialogRecorder) -> None:
    go_to(wizard, 7)
    wizard.config_name_entry.setText("  ")
    wizard.next()
    assert wizard.currentId() == 7
    assert dialog_answers.titles("show_error") == ["Invalid Configuration Name"]


def test_finishing_writes_the_configuration(qtbot: QtBot, wizard: ConfigurationWizard) -> None:
    go_to(wizard, 3)
    wizard.compile_sh_text.setPlainText("#!/bin/bash\n$CXX a.cpp\n")
    go_to(wizard, 7)
    wizard.config_name_entry.setText(" mine ")
    qtbot.keyClick(wizard.execute_sh_text, Qt.Key.Key_A)
    wizard.execute_sh_text.setPlainText("#!/bin/bash\n./a.out 5\n")
    wizard.next()
    wizard.validate_sh_text.setPlainText("#!/bin/bash\ndiff a b\n")
    with qtbot.waitSignal(wizard.finished):
        wizard.button(wizard.WizardButton.FinishButton).click()
    assert wizard.result_name == "mine"
    config = Path(wizard.arguments.project_config_dir, "mine")
    assert (config / "execute.sh").read_text() == "#!/bin/bash\n./a.out 5\n"
    assert (config / "validate.sh").read_text() == "#!/bin/bash\ndiff a b\n"
    assert has_real_configuration(wizard.arguments.project_config_dir)


def test_finishing_without_a_changed_execute_script_keeps_the_placeholder_line(
    qtbot: QtBot, wizard: ConfigurationWizard
) -> None:
    go_to(wizard, 8)
    with qtbot.waitSignal(wizard.finished):
        wizard.accept()
    assert wizard.result_name == "default"
    execute_sh = Path(wizard.arguments.project_config_dir, "default", "execute.sh").read_text()
    assert execute_sh == "#!/bin/bash\n./a.out <args>\n"
    # no validate.sh without a meaningful script
    assert not Path(wizard.arguments.project_config_dir, "default", "validate.sh").exists()


def test_a_failure_while_writing_is_reported_and_keeps_the_wizard_open(
    wizard: ConfigurationWizard, dialog_answers: DialogRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    from discopop_library.ProjectManager.qt_gui import wizard as wizard_module

    def broken(*_args: object) -> str:
        raise OSError("disk full")

    monkeypatch.setattr(wizard_module, "write_wizard_configuration", broken)
    go_to(wizard, 8)
    wizard.accept()
    assert wizard.result_name is None and wizard.isVisible()
    assert dialog_answers.messages("show_error") == ["Failed to create configuration: disk full"]


def test_cancel_asks_for_confirmation(
    qtbot: QtBot, wizard: ConfigurationWizard, dialog_answers: DialogRecorder
) -> None:
    dialog_answers.answer("ask_yes_no", False, True)
    wizard.reject()
    assert wizard.isVisible() and wizard.result_name is None
    with qtbot.waitSignal(wizard.finished):
        wizard.reject()
    assert wizard.result_name is None and not wizard.isVisible()


def test_the_instrumentation_scope_step_saves_the_scope_when_left(wizard: ConfigurationWizard) -> None:
    assert wizard.windowTitle() == "Configuration Assistant - Step 1 of 9: Welcome"
    go_to(wizard, 2)
    assert wizard.currentPage().title() == "Step 3 of 9: Instrumentation scope"
    Path(wizard.arguments.project_root, "src").mkdir()
    editor = wizard.project_environment_widget
    assert editor.scope_edit.text() == "."
    editor.scope_edit.setText("src/")
    assert editor.resolved_edit.text() == os.path.join(wizard.arguments.project_root, "src") + os.sep
    environment_file = Path(wizard.arguments.project_config_dir, "project_environment.json")
    assert not environment_file.exists()
    wizard.next()
    assert wizard.currentId() == 3
    assert json.loads(environment_file.read_text()) == {"DP_PROJECT_ROOT_DIR": "src"}


def test_leaving_the_scope_step_unchanged_writes_nothing(wizard: ConfigurationWizard) -> None:
    go_to(wizard, 3)
    assert not Path(wizard.arguments.project_config_dir, "project_environment.json").exists()


def test_rewriting_the_scripts_in_the_scope_step_updates_the_compile_script_editor(
    make_wizard: Callable[[ProjectManagerArguments], ConfigurationWizard], tmp_path: Path
) -> None:
    arguments = make_arguments(tmp_path / "project")
    os.makedirs(arguments.project_config_dir, exist_ok=True)
    Path(arguments.project_root, "src").mkdir()
    compile_sh = Path(arguments.project_config_dir, "compile.sh")
    compile_sh.write_text('#!/bin/bash\ncmake -S "$DP_PROJECT_ROOT_DIR" -B build\n')
    wizard = make_wizard(arguments)
    go_to(wizard, 2)
    editor = wizard.project_environment_widget
    editor.scope_edit.setText("src")
    assert editor.rewrite_button.isVisibleTo(editor)
    editor.rewrite_button.click()
    assert "DP_RUN_ROOT_DIR" in compile_sh.read_text()
    # finishing the wizard writes the editor's text: it must not bring the old variable back
    assert "DP_RUN_ROOT_DIR" in wizard.compile_sh_text.toPlainText()
    assert "DP_PROJECT_ROOT_DIR" not in wizard.compile_sh_text.toPlainText()

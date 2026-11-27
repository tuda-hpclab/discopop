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
from discopop_library.ProjectManager.configurations.compile_script import resolve_incremental_compile_script_path
from discopop_library.ProjectManager.qt_gui.conftest import DialogRecorder
from discopop_library.ProjectManager.qt_gui.testing import make_arguments
from discopop_library.ProjectManager.qt_gui.wizard import ConfigurationWizard, PlaceholderScriptEditor
from discopop_library.ProjectManager.services.configurations import has_real_configuration
from discopop_library.ProjectManager.services.excluded_directories import load_excluded_directories
from discopop_library.ProjectManager.services.included_directories import load_included_directories


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
    assert wizard.windowTitle() == "Configuration Assistant - Step 1 of 10: Welcome"
    assert wizard.currentPage().title() == "Step 1 of 10: Welcome"
    assert wizard.button(wizard.WizardButton.BackButton).text() == "< Back"
    assert wizard.button(wizard.WizardButton.NextButton).text() == "Next >"
    wizard.next()
    assert wizard.windowTitle() == "Configuration Assistant - Step 2 of 10: Write Permissions Check"
    wizard.back()
    assert wizard.currentId() == 0
    go_to(wizard, 9)
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
    wizard.next()  # incremental build script (skipped)
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
    go_to(wizard, 7)
    wizard.hd_settings_text.setPlainText("{not json")
    wizard.next()
    assert wizard.currentId() == 7
    assert dialog_answers.titles("show_error") == ["Invalid JSON"]
    assert not Path(wizard.arguments.project_config_dir, "dp_settings.json").exists()
    wizard.hd_settings_text.setPlainText("{}")
    wizard.next()
    assert wizard.currentId() == 8
    assert json.loads(Path(wizard.arguments.project_config_dir, "hd_settings.json").read_text()) == {}


def test_test_compilation_runs_the_compile_script_and_shows_the_outcome(
    qtbot: QtBot, wizard: ConfigurationWizard
) -> None:
    go_to(wizard, 3)
    wizard.compile_sh_text.setPlainText("#!/bin/bash\necho compiling $CXX\n")
    wizard.next()
    wizard.next()
    wizard.next()
    assert wizard.currentId() == 6
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
    wizard.next()
    wizard.run_test_button.click()
    qtbot.waitUntil(lambda: wizard.test_status_label.text() != "Running...", timeout=20000)
    assert wizard.test_status_label.text() == "✗ Failed (exit code: 3)"
    assert "stderr:\nbroken" in wizard.test_output.text()


def test_the_configuration_needs_a_name(wizard: ConfigurationWizard, dialog_answers: DialogRecorder) -> None:
    go_to(wizard, 8)
    wizard.config_name_entry.setText("  ")
    wizard.next()
    assert wizard.currentId() == 8
    assert dialog_answers.titles("show_error") == ["Invalid Configuration Name"]


def test_finishing_writes_the_configuration(qtbot: QtBot, wizard: ConfigurationWizard) -> None:
    go_to(wizard, 3)
    wizard.compile_sh_text.setPlainText("#!/bin/bash\n$CXX a.cpp\n")
    go_to(wizard, 8)
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
    go_to(wizard, 9)
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
    go_to(wizard, 9)
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


def test_the_project_directories_step_saves_at_once(
    wizard: ConfigurationWizard, dialog_answers: DialogRecorder, tmp_path: Path
) -> None:
    assert wizard.windowTitle() == "Configuration Assistant - Step 1 of 10: Welcome"
    Path(wizard.arguments.project_root, "third_party").mkdir()
    wizard.excluded_directories.reload()
    go_to(wizard, 2)
    assert wizard.currentPage().title() == "Step 3 of 10: Project Directories"
    item = wizard.excluded_directories.topLevelItem(0)
    assert item is not None and item.text(0) == "third_party"
    item.setCheckState(0, Qt.CheckState.Checked)
    assert load_excluded_directories(wizard.arguments.project_dir) == ["third_party"]
    shared = tmp_path / "shared"
    shared.mkdir()
    dialog_answers.answer("ask_directory", str(shared))
    wizard.included_directories.add_button.click()
    assert load_included_directories(wizard.arguments.project_dir) == [str(shared)]
    wizard.next()
    assert wizard.currentId() == 3


CMAKE_COMPILE = "#!/bin/bash\n# $CXX\ncmake -S . -B build && cmake --build build -j\n"


def shared_incremental(wizard: ConfigurationWizard) -> Path:
    return Path(wizard.arguments.project_config_dir, "compile_incremental.sh")


def enter_compile_sh(wizard: ConfigurationWizard, text: str) -> None:
    go_to(wizard, 3)
    wizard.compile_sh_text.setPlainText(text)
    wizard.next()
    assert wizard.currentId() == 4


def test_the_incremental_step_follows_the_compile_script(wizard: ConfigurationWizard) -> None:
    go_to(wizard, 4)
    assert wizard.currentPage().title() == "Step 5 of 10: Incremental Build Script"
    assert "Compilation Settings" in wizard.steps[5].title()
    assert not wizard.incremental_check.isChecked() and not wizard.incremental_sh_text.isEnabled()


def test_the_incremental_step_can_be_skipped(wizard: ConfigurationWizard) -> None:
    enter_compile_sh(wizard, CMAKE_COMPILE)
    wizard.next()
    assert wizard.currentId() == 5
    assert not shared_incremental(wizard).exists()


def test_checking_proposes_the_rebuild_from_the_compile_script(wizard: ConfigurationWizard) -> None:
    enter_compile_sh(wizard, CMAKE_COMPILE)
    wizard.incremental_check.setChecked(True)
    assert wizard.incremental_sh_text.isEnabled()
    text = wizard.incremental_sh_text.text()
    assert "cmake --build build -j" in text and "-S" not in text
    assert wizard.incremental_status.text() == "Proposed from compile.sh — check it"


def test_without_a_build_line_the_template_is_shown(wizard: ConfigurationWizard) -> None:
    enter_compile_sh(wizard, "#!/bin/bash\n# $CXX\necho nothing\n")
    wizard.incremental_check.setChecked(True)
    assert wizard.incremental_status.text() == "No build line found in compile.sh — write the rebuild command"
    assert wizard.incremental_sh_text.text().strip()


def test_edits_of_the_incremental_script_survive_going_back_and_forth(wizard: ConfigurationWizard) -> None:
    enter_compile_sh(wizard, CMAKE_COMPILE)
    wizard.incremental_check.setChecked(True)
    wizard.incremental_sh_text.setPlainText("#!/bin/bash\nmake -C build\n")
    wizard.back()
    wizard.compile_sh_text.setPlainText("#!/bin/bash\n# $CXX\nmake -j\n")
    wizard.next()
    assert wizard.currentId() == 4
    assert wizard.incremental_sh_text.text() == "#!/bin/bash\nmake -C build\n"


def test_an_unedited_proposal_is_refreshed_after_the_compile_script_changed(wizard: ConfigurationWizard) -> None:
    enter_compile_sh(wizard, CMAKE_COMPILE)
    wizard.incremental_check.setChecked(True)
    wizard.back()
    wizard.compile_sh_text.setPlainText("#!/bin/bash\n# $CXX\nmake -C other -j\n")
    wizard.next()
    assert "make -C other -j" in wizard.incremental_sh_text.text()


def test_next_writes_the_executable_shared_incremental_script(wizard: ConfigurationWizard) -> None:
    enter_compile_sh(wizard, CMAKE_COMPILE)
    wizard.incremental_check.setChecked(True)
    wizard.next()
    assert wizard.currentId() == 5
    path = shared_incremental(wizard)
    assert "cmake --build build -j" in path.read_text() and os.access(path, os.X_OK)
    assert resolve_incremental_compile_script_path(wizard.arguments.project_config_dir, "default") == str(path)


def test_an_empty_incremental_script_is_refused(wizard: ConfigurationWizard, dialog_answers: DialogRecorder) -> None:
    enter_compile_sh(wizard, CMAKE_COMPILE)
    wizard.incremental_check.setChecked(True)
    wizard.incremental_sh_text.setPlainText("  \n")
    wizard.next()
    assert wizard.currentId() == 4
    assert dialog_answers.titles("show_error") == ["Empty Incremental Build Script"]
    assert not shared_incremental(wizard).exists()


def make_existing(
    make_wizard: Callable[[ProjectManagerArguments], ConfigurationWizard], tmp_path: Path
) -> ConfigurationWizard:
    arguments = make_arguments(tmp_path / "project")
    Path(arguments.project_config_dir, "compile_incremental.sh").write_text("#!/bin/bash\nmake\n")
    return make_wizard(arguments)


def test_an_existing_incremental_script_starts_checked_and_is_not_overwritten(
    make_wizard: Callable[[ProjectManagerArguments], ConfigurationWizard], tmp_path: Path
) -> None:
    created = make_existing(make_wizard, tmp_path)
    enter_compile_sh(created, CMAKE_COMPILE)
    assert created.incremental_check.isChecked() and created.incremental_sh_text.isEnabled()
    assert created.incremental_sh_text.text() == "#!/bin/bash\nmake\n"


def test_unchecking_an_existing_incremental_script_asks_before_removing_it(
    make_wizard: Callable[[ProjectManagerArguments], ConfigurationWizard],
    tmp_path: Path,
    dialog_answers: DialogRecorder,
) -> None:
    created = make_existing(make_wizard, tmp_path)
    enter_compile_sh(created, CMAKE_COMPILE)
    created.incremental_check.setChecked(False)
    dialog_answers.answer("ask_yes_no", False, True)
    created.next()
    assert created.currentId() == 5 and shared_incremental(created).exists()
    created.back()
    created.next()
    assert created.currentId() == 5 and not shared_incremental(created).exists()
    assert dialog_answers.titles("ask_yes_no") == ["Remove compile_incremental.sh"] * 2

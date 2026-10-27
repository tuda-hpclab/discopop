# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The configuration assistant: a non-blocking wizard that creates the first configuration of a project.

Ported from ``gui/ConfigurationWizard.py`` and ``gui/wizard_steps.py``; what the steps compute and write lives in
``services/wizard.py`` and ``services/configurations.py``. Open it with ``wizard.open()`` and listen to
``finished``; ``result_name`` is the name of the configuration it wrote (None if it was cancelled).
"""

import json
import os
from typing import Callable, Optional

from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.services.configurations import (
    WizardData,
    write_seq_settings,
    write_shared_compile_script,
    write_wizard_configuration,
)
from discopop_library.ProjectManager.services.jobs import WorkEvent, WorkFinished
from discopop_library.ProjectManager.services.wizard import (
    COMPILE_PLACEHOLDER,
    EXECUTE_PLACEHOLDER,
    TEST_OK,
    compilation_work,
    compute_derived_settings,
    describe_test_compilation,
    existing_compile_script,
    initial_seq_settings,
    save_derived_settings,
)

STEP_TITLES = [
    "Welcome",
    "Write Permissions Check",
    "Compilation Script",
    "Compilation Settings",
    "Test Compilation",
    "Derived Settings",
    "Execution Script",
    "Validation Script",
]

WELCOME_TEXT = """Welcome to the Configuration Assistant

This wizard will guide you through the steps necessary to create a valid and complete configuration for DiscoPoP profiling.

The wizard will help you with:

1. Specifying the compilation script (compile.sh)
2. Configuring compilation settings (compilers and flags)
3. Testing the compilation configuration
4. Reviewing and accepting derived settings files
5. Specifying the execution script and naming your configuration
6. Optionally specifying an output validation script (validate.sh), plus a separate
   compilation script for it if validation needs a different build

After completing this wizard, your project will be ready to use with DiscoPoP.

Click "Next >" to begin."""  # noqa: E501

WRITE_ACCESS_TEXT = """Write access to the parent folder has been detected.

This allows DiscoPoP to automatically create and delete temporary project copies
during execution, which enables non-inplace mode for testing and validation.

You can proceed with the wizard configuration."""

NO_WRITE_ACCESS_TEXT = """Write access to the parent folder is not available.

Executions will be limited to "inplace" mode, where the project directory is
modified directly. Temporary project copies cannot be created.

You can still proceed with the configuration, but keep this limitation in mind."""

COMPILE_HINT = (
    "Specify the compilation script. It is executed from the project root directory.\n\n"
    "Requirements:\n"
    "  • Use $CC / $CXX and $CFLAGS / $CXXFLAGS for all compile commands.\n"
    "  • The script must return exit code 0 on success.\n\n"
    "You can use relative paths as if you are already in the project root.\n"
    "See the wiki for examples: https://tuda-hpclab.github.io/discopop/"
)

EXECUTE_HINT = (
    "Specify a minimal execution script to validate the instrumentation.\n"
    "More detailed configurations can be added afterwards.\n\n"
    "Requirements:\n"
    "  • The script must execute the program created by the previously defined compilation.\n"
    "  • The script must return exit code 0 on success.\n\n"
    "You can use relative paths as if you are already in the project root.\n"
    "See the wiki for examples: https://tuda-hpclab.github.io/discopop/"
)

VALIDATE_HINT = (
    "Optionally specify a validation script (validate.sh).\n\n"
    "Leave empty to skip. If provided, validate.sh re-runs the program and validates its\n"
    "output separately from the timed execute.sh run (e.g. a diff against a reference).\n"
    "A run then counts as correct only if BOTH execute.sh and validate.sh exit 0.\n\n"
    "You can use relative paths as if you are already in the project root."
)

VALIDATE_COMPILE_HINT = (
    "Leave empty to build validate.sh's code with compile.sh, as usual. If filled in, this\n"
    "script is compiled after the timed execute.sh run and before validate.sh, so the extra\n"
    "build never affects the measured runtime. Use $CC / $CXX and $CFLAGS / $CXXFLAGS."
)


def script_text(editor: widgets.ScriptEditor) -> str:
    """The content of a script editor as a file content: it ends with a newline (as the Tk editor's did)."""
    text = editor.text()
    return text if text.endswith("\n") else text + "\n"


class PlaceholderScriptEditor(widgets.ScriptEditor):
    """A script editor that starts with a shebang and a grey example line, which disappears at the first key or click.

    Until then the example line is real content, as in the Tk wizard.
    """

    def __init__(self, placeholder: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._placeholder = placeholder
        self.has_placeholder = True
        self.setPlainText("#!/bin/bash\n")
        grey = QTextCharFormat()
        grey.setForeground(QColor(widgets.PLACEHOLDER_FG))
        cursor = QTextCursor(self.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(placeholder, grey)
        self.document().setModified(False)

    def remove_placeholder(self) -> None:
        if not self.has_placeholder:
            return
        self.has_placeholder = False
        lines = self.toPlainText().split("\n")
        if len(lines) > 1 and lines[1] == self._placeholder:
            self.setPlainText("#!/bin/bash\n")
            self.moveCursor(QTextCursor.MoveOperation.End)
            self.document().setModified(False)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 (Qt's name)
        self.remove_placeholder()
        super().keyPressEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 (Qt's name)
        self.remove_placeholder()
        super().mousePressEvent(event)


class _Step(QWizardPage):
    """One step; ``on_next`` runs when the user leaves it forwards and may keep the wizard on it by returning False."""

    def __init__(self, index: int, on_next: Optional[Callable[[], bool]] = None) -> None:
        super().__init__()
        self.setTitle(f"Step {index + 1} of {len(STEP_TITLES)}: {STEP_TITLES[index]}")
        self._on_next = on_next
        self._complete = True

    def validatePage(self) -> bool:  # noqa: N802 (Qt's name)
        return self._on_next() if self._on_next is not None else True

    def isComplete(self) -> bool:  # noqa: N802 (Qt's name)
        return self._complete

    def set_complete(self, complete: bool) -> None:
        self._complete = complete
        self.completeChanged.emit()


def _label(text: str, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(wrap)
    return label


class ConfigurationWizard(QWizard):
    def __init__(self, arguments: ProjectManagerArguments, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.arguments = arguments
        self.result_name: Optional[str] = None
        self.step_data = WizardData()
        self.setWindowTitle("Configuration Assistant")
        self.resize(1100, 900)
        self.setMinimumSize(900, 700)
        self.setWizardStyle(QWizard.WizardStyle.ClassicStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, False)
        self.setButtonText(QWizard.WizardButton.NextButton, "Next >")
        self.setButtonText(QWizard.WizardButton.BackButton, "< Back")
        self.setButtonText(QWizard.WizardButton.FinishButton, "Finish")

        self.steps = [
            self._welcome_step(),
            self._write_access_step(),
            self._compile_sh_step(),
            self._seq_settings_step(),
            self._test_compilation_step(),
            self._derived_settings_step(),
            self._execute_sh_step(),
            self._validate_sh_step(),
        ]
        for step in self.steps:
            self.addPage(step)
        self.currentIdChanged.connect(self._update_title)
        self._update_title(0)

    def _update_title(self, step_index: int) -> None:
        if 0 <= step_index < len(STEP_TITLES):
            self.setWindowTitle(
                f"Configuration Assistant - Step {step_index + 1} of {len(STEP_TITLES)}: {STEP_TITLES[step_index]}"
            )

    def _step(self, index: int, *items: QWidget, on_next: Optional[Callable[[], bool]] = None) -> _Step:
        step = _Step(index, on_next)
        layout = QVBoxLayout()
        for item in items:
            layout.addWidget(item)
        step.setLayout(layout)
        return step

    # --- the steps ---

    def _welcome_step(self) -> _Step:
        return self._step(0, _label(WELCOME_TEXT, wrap=True))

    def _write_access_step(self) -> _Step:
        parent_folder = os.path.dirname(self.arguments.project_root)
        if os.access(parent_folder, os.W_OK):
            status_text, status_color, description = "✓ Write Access Available", widgets.STATUS_OK, WRITE_ACCESS_TEXT
        else:
            status_text, status_color, description = "⚠ No Write Access", widgets.STATUS_STOP, NO_WRITE_ACCESS_TEXT
        self.write_access_label = widgets.heading_label(status_text)
        widgets.set_label_color(self.write_access_label, status_color)
        layout_widgets = [self.write_access_label, _label(description, wrap=True)]
        step = self._step(1, *layout_widgets)
        step.layout().addStretch(1)  # type: ignore[union-attr]
        return step

    def _compile_sh_step(self) -> _Step:
        existing = existing_compile_script(self.arguments.project_config_dir)
        self.compile_sh_text: widgets.ScriptEditor
        if existing is not None:
            self.compile_sh_text = widgets.ScriptEditor()
            self.compile_sh_text.set_text(existing)
        else:
            self.compile_sh_text = PlaceholderScriptEditor(COMPILE_PLACEHOLDER)
        return self._step(2, _label(COMPILE_HINT), self.compile_sh_text, on_next=self._leave_compile_sh)

    def _leave_compile_sh(self) -> bool:
        self.step_data.compile_sh = script_text(self.compile_sh_text)
        content = self.step_data.compile_sh
        if "$CC" not in content and "$CXX" not in content:
            if not dialogs.ask_yes_no(
                self,
                "Missing Compiler Variables",
                "The compile script does not contain $CC or $CXX variables.\n\n"
                "This may cause the sequential compilation settings to be ignored.\n\n"
                "Do you want to continue anyway?",
            ):
                return False
        write_shared_compile_script(self.arguments.project_config_dir, self.step_data)
        return True

    def _seq_settings_step(self) -> _Step:
        settings = initial_seq_settings(self.arguments.project_config_dir)
        self.cc_entry = QLineEdit(settings["CC"])
        self.cxx_entry = QLineEdit(settings["CXX"])
        self.cflags_entry = QLineEdit(settings["CFLAGS"])
        self.cxxflags_entry = QLineEdit(settings["CXXFLAGS"])
        form = QWidget()
        form_layout = QFormLayout(form)
        form_layout.addRow("C Compiler (CC):", self.cc_entry)
        form_layout.addRow("C++ Compiler (CXX):", self.cxx_entry)
        form_layout.addRow("C Flags (CFLAGS):", self.cflags_entry)
        form_layout.addRow("C++ Flags (CXXFLAGS):", self.cxxflags_entry)
        step = self._step(
            3,
            _label("Configure your compilation settings. These will be used to compile your project."),
            form,
            on_next=self._leave_seq_settings,
        )
        step.layout().addStretch(1)  # type: ignore[union-attr]
        return step

    def _leave_seq_settings(self) -> bool:
        self.step_data.cc = self.cc_entry.text()
        self.step_data.cxx = self.cxx_entry.text()
        self.step_data.cflags = self.cflags_entry.text()
        self.step_data.cxxflags = self.cxxflags_entry.text()
        write_seq_settings(self.arguments.project_config_dir, self.step_data)
        return True

    def _test_compilation_step(self) -> _Step:
        self.run_test_button = widgets.primary_button("Run Test Compilation", self.run_test_compilation)
        self.test_status_label = QLabel("")
        self.test_output = widgets.OutputConsole()
        step = self._step(
            4,
            _label("Click 'Run Test Compilation' to verify your compilation script works."),
            self.run_test_button,
            self.test_status_label,
            self.test_output,
            on_next=self._leave_test_compilation,
        )
        layout = step.layout()
        assert isinstance(layout, QVBoxLayout)
        layout.removeWidget(self.run_test_button)
        layout.removeWidget(self.test_status_label)
        layout.insertLayout(1, widgets.hbox(self.run_test_button, self.test_status_label, None, spacing=10))
        return step

    def run_test_compilation(self) -> None:
        self.test_output.clear()
        self.test_status_label.setText("Running...")
        widgets.set_label_color(self.test_status_label, widgets.STATUS_BUSY)
        self.run_test_button.setEnabled(False)
        self.steps[4].set_complete(False)

        def handle(event: WorkEvent) -> None:
            if not isinstance(event, WorkFinished):
                return
            outcome = describe_test_compilation(event)
            self.test_status_label.setText(outcome.status)
            widgets.set_label_color(
                self.test_status_label, widgets.STATUS_OK if outcome.kind == TEST_OK else widgets.STATUS_FAIL
            )
            for line in outcome.output:
                self.test_output.append_text(line)
            self.run_test_button.setEnabled(True)
            self.steps[4].set_complete(True)

        start_work(self, compilation_work(self.arguments), handle)

    def _leave_test_compilation(self) -> bool:
        derived = compute_derived_settings(self.step_data)
        for editor, key in (
            (self.dp_settings_text, "dp_settings"),
            (self.hd_settings_text, "hd_settings"),
            (self.par_settings_text, "par_settings"),
        ):
            editor.set_text(json.dumps(derived[key], indent=2))
        return True

    def _derived_settings_step(self) -> _Step:
        self.dp_settings_text = widgets.ScriptEditor()
        self.hd_settings_text = widgets.ScriptEditor()
        self.par_settings_text = widgets.ScriptEditor()
        self.notebook = QTabWidget()
        self.notebook.addTab(self.dp_settings_text, "dp_settings.json")
        self.notebook.addTab(self.hd_settings_text, "hd_settings.json")
        self.notebook.addTab(self.par_settings_text, "par_settings.json")
        return self._step(
            5,
            _label("Review and accept the derived settings. You can edit them before continuing."),
            self.notebook,
            on_next=self._leave_derived_settings,
        )

    def _leave_derived_settings(self) -> bool:
        try:
            save_derived_settings(
                self.arguments.project_config_dir,
                self.dp_settings_text.text(),
                self.hd_settings_text.text(),
                self.par_settings_text.text(),
            )
        except json.JSONDecodeError as e:
            dialogs.show_error(self, "Invalid JSON", f"One of the derived settings contains invalid JSON: {e}")
            return False
        return True

    def _execute_sh_step(self) -> _Step:
        self.config_name_entry = QLineEdit("default")
        self.execute_sh_text = PlaceholderScriptEditor(EXECUTE_PLACEHOLDER)
        name_row = QWidget()
        name_layout = QVBoxLayout(name_row)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.addWidget(_label("Configuration Name:"))
        name_layout.addWidget(self.config_name_entry)
        return self._step(6, name_row, _label(EXECUTE_HINT), self.execute_sh_text, on_next=self._leave_execute_sh)

    def _leave_execute_sh(self) -> bool:
        config_name = self.config_name_entry.text().strip()
        if not config_name:
            dialogs.show_error(self, "Invalid Configuration Name", "Configuration name cannot be empty.")
            return False
        self.step_data.config_name = config_name
        self.step_data.execute_sh = script_text(self.execute_sh_text)
        return True

    def _validate_sh_step(self) -> _Step:
        self.validate_sh_text = widgets.ScriptEditor()
        self.validate_compile_sh_text = widgets.ScriptEditor()
        validate_box = widgets.group_box("validate.sh", widgets.vbox(self.validate_sh_text, margins=5))
        validate_compile_box = widgets.group_box(
            "compile_validate.sh — only if validation needs a different build",
            widgets.vbox(_label(VALIDATE_COMPILE_HINT), self.validate_compile_sh_text, margins=5),
        )
        return self._step(7, _label(VALIDATE_HINT), validate_box, validate_compile_box)

    # --- finishing ---

    def accept(self) -> None:
        self.step_data.validate_sh = script_text(self.validate_sh_text)
        self.step_data.validate_compile_sh = script_text(self.validate_compile_sh_text)
        try:
            self.result_name = write_wizard_configuration(self.arguments, self.step_data)
        except Exception as e:
            dialogs.show_error(self, "Error", f"Failed to create configuration: {e}")
            return
        super().accept()

    def reject(self) -> None:
        if not self.isVisible():
            super().reject()
        elif dialogs.ask_yes_no(self, "Cancel", "Are you sure you want to cancel the wizard?"):
            super().reject()

    def cancel_jobs(self) -> None:
        """Nothing to stop: the test compilation ends on its own and its events die with the wizard."""

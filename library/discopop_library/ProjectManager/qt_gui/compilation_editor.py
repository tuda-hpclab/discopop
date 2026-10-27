# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The compilation editor window ("Edit Compilation"): the shared compile.sh, the shared validation build script and
the settings files, with Test Compilation and Derive.

Ported from ``gui/mixins/compilation_editor.py``. A window of its own next to the main window, shown with ``show()``.
"""

import os
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import QDialog, QTabWidget, QVBoxLayout, QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.compile_script import (
    VALIDATION_COMPILE_SCRIPT_NAME,
    get_shared_compile_script_path,
    get_shared_validation_compile_script_path,
)
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.help_dialogs import help_button
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.services.editor_files import (
    COMPILATION_FILES,
    DERIVE_TOOLTIP_SUFFIX,
    DERIVED_FILES,
    OPTIONAL_FILE_PLACEHOLDERS,
    OPTIONAL_FILES,
    TAB_TOOLTIPS,
    describe_compilation_test,
    format_json_content,
    run_test_compilation,
)
from discopop_library.ProjectManager.services.jobs import WorkContext, WorkEvent, WorkFinished
from discopop_library.ProjectManager.services.project_state import ConfigurationsChanged, ProjectState
from discopop_library.ProjectManager.utilities.scriptFiles import write_script_file

DERIVE_DISABLED_TOOLTIP = "Save all changes before deriving settings"
TEST_BUTTON_TEXT = "Test Compilation"


class CompilationTestResult(QDialog):
    """The output of a test compilation (non-modal; the window owning it deletes it)."""

    def __init__(self, output: str, return_code: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compilation Test Result")
        self.resize(700, 500)
        self.setMinimumSize(400, 300)
        self.status_label = widgets.heading_label("✓ Success" if return_code == 0 else "✗ Failed")
        widgets.set_label_color(self.status_label, widgets.STATUS_OK if return_code == 0 else widgets.STATUS_FAIL)
        self.console = widgets.OutputConsole()
        self.console.set_text(output)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.console, 1)
        layout.addLayout(widgets.hbox(None, widgets.create_button("Close", self._close), None))

    def _close(self) -> None:
        self.close()


class CompilationEditor(QWidget):
    """The compilation editor window.

    It edits the files of the project's configuration directory shared by all configurations. Saving, deriving
    settings and changing the shared validation build script publish ``ConfigurationsChanged``: they change what
    the configurations can execute. Closing the window drops unsaved changes (as the Tk window does).
    """

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.arguments = arguments
        self.project_state = project_state
        self.status = status
        self.setWindowFlag(Qt.WindowType.Window)
        self.setWindowTitle("Compilation Editor")
        self.resize(1050, 700)
        self.setMinimumSize(800, 500)
        self.editors: Dict[str, widgets.ScriptEditor] = {}
        self.tab_index: Dict[str, int] = {}
        self._results: List[CompilationTestResult] = []
        self._testing = False

        self.notebook = QTabWidget()
        self.shared_validation_compile_button = widgets.create_button("Add", self._toggle_shared_validation_compile)
        for name in COMPILATION_FILES:
            editor = widgets.ScriptEditor()
            editor.document().modificationChanged.connect(lambda _modified: self._on_modification_changed())
            self.editors[name] = editor
            page = QWidget()
            page_layout = QVBoxLayout(page)
            page_layout.addLayout(
                widgets.hbox(
                    widgets.heading_label(name),
                    None,
                    self.shared_validation_compile_button if name == VALIDATION_COMPILE_SCRIPT_NAME else None,
                    help_button(self, name),
                    margins=5,
                )
            )
            page_layout.addWidget(editor, 1)
            self.tab_index[name] = self.notebook.addTab(page, name)
        self.notebook.currentChanged.connect(lambda _index: self._update_buttons())

        self.save_button = widgets.primary_button("Save (Ctrl+S)", self._save_clicked)
        self.test_compilation_button = widgets.create_button(TEST_BUTTON_TEXT, self.test_compilation)
        self.derive_button = widgets.create_button("Derive", self.derive_settings)
        layout = QVBoxLayout(self)
        layout.addWidget(self.notebook, 1)
        layout.addLayout(widgets.hbox(self.save_button, self.test_compilation_button, self.derive_button, None))
        QShortcut(QKeySequence.StandardKey.Save, self, self._save_clicked)

        self.load_files()

    # ── showing ─────────────────────────────────────────────────────────────

    def open(self) -> None:
        """Show the window (reloading the files when it was closed), or bring it to the front if it is open."""
        if not self.isVisible():
            self.load_files()
            parent = self.parentWidget()
            top = parent.window() if parent is not None else None
            if top is not None and top.isVisible():
                self.move(top.geometry().center() - self.rect().center())
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt's name)
        for result in self._results:
            result.close()
        super().closeEvent(event)

    def cancel_jobs(self) -> None:
        """Nothing runs that outlives the window: the test compilation's thread only reports back to it."""

    # ── loading ─────────────────────────────────────────────────────────────

    def _path(self, name: str) -> str:
        return os.path.join(self.arguments.project_config_dir, name)

    def load_files(self) -> None:
        """Show the files from disk, dropping unsaved changes; derived settings that do not exist stay disabled."""
        for name in self.editors:
            self._load_file(name)
        self._update_shared_validation_button()
        self._update_tabs()

    def _load_file(self, name: str) -> None:
        editor = self.editors[name]
        editor.setReadOnly(False)
        path = self._path(name)
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    content = f.read()
                editor.set_text(format_json_content(content) if name.endswith(".json") else content)
            except Exception as e:
                editor.set_text(f"Error loading file: {e}")
        elif name in OPTIONAL_FILES:
            # Absent by default: keep the editor read-only so saving cannot create the file from placeholder text.
            editor.set_text(OPTIONAL_FILE_PLACEHOLDERS[name])
            editor.setReadOnly(True)
        else:
            editor.set_text(f"File not found: {path}")

    def _update_shared_validation_button(self) -> None:
        exists = os.path.exists(get_shared_validation_compile_script_path(self.arguments.project_config_dir))
        self.shared_validation_compile_button.setText("Remove" if exists else "Add")

    def _update_tabs(self) -> None:
        """Tab titles ("*" for unsaved changes), tooltips and the enabled state of the derived settings."""
        for name, index in self.tab_index.items():
            modified = self.editors[name].document().isModified()
            self.notebook.setTabText(index, f"{name} *" if modified else name)
            tooltip = TAB_TOOLTIPS.get(name, "")
            if name in DERIVED_FILES:
                exists = os.path.exists(self._path(name))
                self.notebook.setTabEnabled(index, exists)
                if not exists:
                    tooltip += DERIVE_TOOLTIP_SUFFIX
            self.notebook.setTabToolTip(index, tooltip)
        self._update_buttons()

    def has_unsaved_changes(self) -> bool:
        return any(editor.document().isModified() for editor in self.editors.values())

    def _on_modification_changed(self) -> None:
        self._update_tabs()

    def _current_name(self) -> str:
        return COMPILATION_FILES[self.notebook.currentIndex()]

    def _update_buttons(self) -> None:
        """Test Compilation shows on the compile.sh tab, Derive on the seq_settings.json tab."""
        name = self._current_name()
        self.test_compilation_button.setVisible(name == "compile.sh")
        can_test = os.path.exists(self._path("compile.sh")) and os.path.exists(self._path("seq_settings.json"))
        self.test_compilation_button.setEnabled(can_test and not self._testing)
        self.derive_button.setVisible(name == "seq_settings.json")
        unsaved = self.has_unsaved_changes()
        self.derive_button.setEnabled(not unsaved)
        self.derive_button.setToolTip(DERIVE_DISABLED_TOOLTIP if unsaved else "")

    # ── the shared validation build script ──────────────────────────────────

    def _toggle_shared_validation_compile(self) -> None:
        comp_dir = self.arguments.project_config_dir
        script_path = get_shared_validation_compile_script_path(comp_dir)
        if os.path.exists(script_path):
            if not dialogs.ask_yes_no(
                self,
                "Remove compile_validate.sh",
                "Remove the shared compile_validate.sh?\n\n"
                "validate.sh will then run against the same build as execute.sh, unless a\n"
                "configuration defines its own compile_validate.sh override.",
            ):
                return
            os.remove(script_path)
            message = "Removed shared compile_validate.sh"
        else:
            seed_content = ""
            shared_compile_path = get_shared_compile_script_path(comp_dir)
            if os.path.exists(shared_compile_path):
                with open(shared_compile_path, "r") as f:
                    seed_content = f.read()
            os.makedirs(comp_dir, exist_ok=True)
            write_script_file(script_path, seed_content)
            message = "Added shared compile_validate.sh"
        # only this file is reloaded: the other tabs may hold unsaved changes
        self._load_file(VALIDATION_COMPILE_SCRIPT_NAME)
        self._update_shared_validation_button()
        self._update_tabs()
        self.project_state.publish(ConfigurationsChanged())
        self.status.set(message, widgets.STATUS_OK, reset_ms=2000)

    # ── saving ──────────────────────────────────────────────────────────────

    def _save_clicked(self) -> None:
        self.save()

    def save(self) -> bool:
        """Write the changed files (settings as formatted JSON, scripts executable); False on a write error."""
        comp_dir = self.arguments.project_config_dir
        os.makedirs(comp_dir, exist_ok=True)
        saved_files: List[str] = []
        for name, editor in self.editors.items():
            if not editor.document().isModified():
                continue
            path = os.path.join(comp_dir, name)
            content = editor.text().rstrip()
            if name.endswith(".json"):
                content = format_json_content(content)
            try:
                with open(path, "w") as f:
                    f.write(content)
                if name.endswith(".sh"):
                    os.chmod(path, os.stat(path).st_mode | 0o111)
            except Exception as e:
                self.status.set(f"Error saving file {name}: {e}", widgets.STATUS_FAIL)
                self._update_tabs()
                return False
            editor.document().setModified(False)
            saved_files.append(name)
        self._update_tabs()
        if not saved_files:
            self.status.set("No changes to save")
            return True
        self.status.set(f"Saved {', '.join(saved_files)}", widgets.STATUS_OK, reset_ms=2000)
        self.project_state.publish(ConfigurationsChanged())
        return True

    # ── test compilation ────────────────────────────────────────────────────

    def test_compilation(self) -> None:
        """Compile once with the shown compile.sh and seq_settings.json (saved first); no result is recorded."""
        if (
            self.editors["compile.sh"].document().isModified()
            or self.editors["seq_settings.json"].document().isModified()
        ):
            if not self.save():
                return
        for name in ("compile.sh", "seq_settings.json"):
            if not os.path.exists(self._path(name)):
                dialogs.show_error(self, "Missing File", f"{name} not found")
                return

        self._testing = True
        self.test_compilation_button.setEnabled(False)
        self.test_compilation_button.setText("⟳ Testing...")
        self.status.set("Running compilation test...", widgets.STATUS_BUSY)
        arguments = self.arguments

        def compile_once(_ctx: WorkContext) -> Optional[Tuple[int, float, str, str]]:
            return run_test_compilation(arguments)

        def handle(event: WorkEvent) -> None:
            if not isinstance(event, WorkFinished):
                return
            result = event.result if event.error is None else None
            if event.error is not None:
                self.status.set(f"✗ Compilation test failed: {event.error}", widgets.STATUS_FAIL)
            elif result is None:
                self.status.set("✗ Compilation test failed: settings not found", widgets.STATUS_FAIL)
            else:
                return_code, elapsed, stdout, stderr = result
                if return_code == 0:
                    self.status.set(f"✓ Compilation successful ({elapsed:.2f}s)", widgets.STATUS_OK)
                else:
                    self.status.set(
                        f"✗ Compilation failed (exit code: {return_code}, {elapsed:.2f}s)", widgets.STATUS_FAIL
                    )
                self._show_result(describe_compilation_test(return_code, elapsed, stdout, stderr), return_code)
            self._testing = False
            self.test_compilation_button.setText(TEST_BUTTON_TEXT)
            self._update_buttons()

        start_work(self, compile_once, handle)

    def _show_result(self, output: str, return_code: int) -> None:
        # the result windows closed meanwhile are deleted, the open ones stay until this window closes
        for closed in [result for result in self._results if not result.isVisible()]:
            self._results.remove(closed)
            closed.deleteLater()
        result = CompilationTestResult(output, return_code, self)
        self._results.append(result)
        result.show()

    # ── derive ──────────────────────────────────────────────────────────────

    def derive_settings(self) -> None:
        """Derive dp, hd and par settings from seq_settings.json."""
        try:
            from discopop_library.ProjectManager.utilities.deriveSettingsFiles import derive_settings_files

            derive_settings_files(self.arguments.project_config_dir)
            self.status.set("Derived settings created successfully", widgets.STATUS_OK, reset_ms=2000)
            self.load_files()
            self.project_state.publish(ConfigurationsChanged())
        except Exception as e:
            self.status.set(f"Error deriving settings: {e}", widgets.STATUS_FAIL, reset_ms=3000)

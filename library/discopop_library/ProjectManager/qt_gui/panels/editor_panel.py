# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Editor tab: execute.sh, the compile.sh override, validate.sh and the compile_validate.sh override of the
selected configuration, and the execution time setting stored next to execute.sh.

Ported from ``gui/mixins/file_editor.py`` and the Editor part of ``gui/ConfigManagerApp.py``.
"""

import os
from typing import Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QCheckBox,
    QLabel,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.compile_script import (
    get_per_config_compile_script_path,
    get_per_config_validation_compile_script_path,
    get_shared_compile_script_path,
    resolve_compile_script_path,
)
from discopop_library.ProjectManager.configurations.execution_time import (
    DEFAULT_EXECUTION_TIME_REGEX,
    EXECUTION_TIME_SETTINGS_FILE,
    extract_execution_time,
    read_execution_time_settings,
    validate_execution_time_regex,
    write_execution_time_settings,
)
from discopop_library.ProjectManager.configurations.validation import has_validate_script
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.compilation_editor import CompilationEditor
from discopop_library.ProjectManager.qt_gui.help_dialogs import help_button
from discopop_library.ProjectManager.qt_gui.tabs import TAB_EDITOR
from discopop_library.ProjectManager.qt_gui.panel import Panel, TabHost
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.services.editor_files import (
    COMPILE_OVERRIDE_PLACEHOLDER,
    COMPILE_SCRIPT_WARNING,
    COMPILE_SCRIPT_WARNING_TITLE,
    VALIDATE_SCRIPT_PLACEHOLDER,
    VALIDATION_COMPILE_OVERRIDE_PLACEHOLDER,
    last_recorded_execution_output,
    uses_compiler_variables,
)
from discopop_library.ProjectManager.services.project_state import (
    ConfigChanged,
    ConfigurationsChanged,
    ProjectState,
    ResultsChanged,
)
from discopop_library.ProjectManager.utilities.scriptFiles import write_script_file

FILES = ("execute.sh", "compile.sh", "validate.sh", "compile_validate.sh")
# the per-configuration files other than execute.sh may be absent; the editor then shows a read-only placeholder
PLACEHOLDERS = {
    "compile.sh": COMPILE_OVERRIDE_PLACEHOLDER,
    "validate.sh": VALIDATE_SCRIPT_PLACEHOLDER,
    "compile_validate.sh": VALIDATION_COMPILE_OVERRIDE_PLACEHOLDER,
}
BASE_LABELS = {
    "execute.sh": "execute.sh",
    "compile.sh": "compile.sh (override)",
    "validate.sh": "validate.sh",
    "compile_validate.sh": "compile_validate.sh (override)",
}
HEADINGS = {
    "execute.sh": "Execution script",
    "compile.sh": "Compilation script override",
    "validate.sh": "Output validation script",
    "compile_validate.sh": "Validation build script override",
}
EXECUTION_TIME_TOOLTIP = (
    "Off: the wall clock time of execute.sh is measured, including setup,\n"
    "teardown and any file I/O it performs.\n"
    "On: the time the program prints itself is used instead. If the pattern\n"
    "finds nothing, the wall clock time is reported and the run is marked\n"
    "as having fallen back to it."
)
EXECUTION_TIME_HINT = (
    "The first capture group holds the value, e.g. Total time:\\s*([0-9.]+) "
    "for a program printing 'Total time: 1.234 seconds'."
)


class EditorPanel(Panel):
    """The Editor tab.

    ``tabs`` is the main window: the panel shows unsaved changes on the title of its tab ("Editor *") and the save
    shortcut depends on the tab in front. After saving files that change what can be executed (and after adding or
    removing an override) ``ConfigurationsChanged`` is published, so the Execute tab refreshes its modes and its
    "Execution time" summary.
    """

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        tabs: TabHost,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(arguments, project_state, status, parent)
        self.tabs = tabs
        self.execution_time_modified = False
        self._loading = False
        self._loaded_config: Optional[str] = None
        # the files of the loaded configuration as they were on disk when loaded or saved
        self._loaded_state: Tuple[Tuple[str, Optional[str]], ...] = ()
        self._compilation_editor: Optional[CompilationEditor] = None

        self.editors: Dict[str, widgets.ScriptEditor] = {name: widgets.ScriptEditor() for name in FILES}
        for editor in self.editors.values():
            editor.document().modificationChanged.connect(lambda _modified: self._refresh_marks())

        self.compile_override_button = widgets.create_button("Add Override", self._toggle_compile_override)
        self.validate_script_button = widgets.create_button("Add validate.sh", self._toggle_validate_script)
        self.validation_compile_override_button = widgets.create_button(
            "Add Override", self._toggle_validation_compile_override
        )
        toggles = {
            "compile.sh": self.compile_override_button,
            "validate.sh": self.validate_script_button,
            "compile_validate.sh": self.validation_compile_override_button,
        }

        self.notebook = QTabWidget()
        self.sub_tab_labels: Dict[str, str] = dict(BASE_LABELS)
        self._sub_tab_widgets: Dict[str, QWidget] = {}
        for name in FILES:
            page = QWidget()
            header = widgets.hbox(
                widgets.heading_label(HEADINGS[name]), None, toggles.get(name), help_button(self, name), margins=5
            )
            page_layout = QVBoxLayout(page)
            page_layout.addLayout(header)
            page_layout.addWidget(self.editors[name], 1)
            if name == "execute.sh":
                page_layout.addWidget(self._build_execution_time_settings())
            self._sub_tab_widgets[name] = page
            self.notebook.addTab(page, BASE_LABELS[name])

        self.save_button = widgets.primary_button("Save (Ctrl+S)", self._save_clicked)
        layout = QVBoxLayout(self)
        layout.addWidget(self.notebook, 1)
        layout.addLayout(widgets.hbox(self.save_button, None, margins=5))

        project_state.subscribe(ConfigChanged, lambda _event: self._on_config_changed())

    # ── the execution time setting ──────────────────────────────────────────

    def _build_execution_time_settings(self) -> QWidget:
        """The "read the execution time from the console output" setting of execute.sh.

        It lives in this tab because it is a property of the script it belongs to -- it describes how that program
        reports its own timing -- and is stored per configuration in ``execution_time.json``, saved with the script.
        """
        self.execution_time_enabled = QCheckBox("Read the execution time from the program's console output")
        self.execution_time_enabled.setToolTip(EXECUTION_TIME_TOOLTIP)
        self.execution_time_regex = QLineEdit(DEFAULT_EXECUTION_TIME_REGEX)
        self.execution_time_test_button = widgets.create_button("Test", self._test_execution_time_regex)
        self.execution_time_hint_label = widgets.caption_label(EXECUTION_TIME_HINT)
        self.execution_time_test_label = QLabel("")
        self.execution_time_test_label.setWordWrap(True)
        self.execution_time_enabled.toggled.connect(self._on_execution_time_edited)
        self.execution_time_regex.textChanged.connect(self._on_execution_time_edited)
        self._update_execution_time_state()
        return widgets.group_box(
            "Execution time",
            widgets.vbox(
                self.execution_time_enabled,
                widgets.hbox(QLabel("Pattern:"), self.execution_time_regex, self.execution_time_test_button),
                self.execution_time_hint_label,
                self.execution_time_test_label,
                margins=5,
            ),
        )

    def _on_execution_time_edited(self, *_args: object) -> None:
        self._update_execution_time_state()
        if self._loading or self.execution_time_modified:
            return
        self.execution_time_modified = True
        self._refresh_marks()

    def _update_execution_time_state(self) -> None:
        """Grey out the pattern while the search is switched off."""
        enabled = self.execution_time_enabled.isChecked()
        self.execution_time_regex.setEnabled(enabled)
        self.execution_time_test_button.setEnabled(enabled)

    def _show_execution_time_result(self, text: str, color: str) -> None:
        self.execution_time_test_label.setText(text)
        widgets.set_label_color(self.execution_time_test_label, color)

    def _test_execution_time_regex(self) -> None:
        """Apply the pattern to the output of this configuration's last run, without executing anything."""
        regex = self.execution_time_regex.text()
        error = validate_execution_time_regex(regex)
        if error is not None:
            self._show_execution_time_result("✗ The pattern is " + error, widgets.STATUS_FAIL)
            return
        output = last_recorded_execution_output(self.arguments.project_dir, self.project_state.current_config)
        if output is None:
            self._show_execution_time_result(
                "No recorded output to test against yet — execute this configuration first.", widgets.STATUS_IDLE
            )
            return
        stdout, stderr = output
        value = extract_execution_time(stdout, stderr, regex)
        if value is None:
            self._show_execution_time_result("✗ No match in the output of the last recorded run.", widgets.STATUS_FAIL)
        else:
            self._show_execution_time_result(f"✓ Matched in the last recorded run: {value} s", widgets.STATUS_OK)

    def _save_execution_time_settings(self, config_path: str) -> bool:
        """Persist the execution time setting; False if it was rejected."""
        if not self.execution_time_modified:
            return True
        regex = self.execution_time_regex.text()
        enabled = self.execution_time_enabled.isChecked()
        if enabled:
            error = validate_execution_time_regex(regex)
            if error is not None:
                dialogs.show_error(self, "Invalid execution time pattern", "The pattern is " + error)
                return False
        try:
            write_execution_time_settings(config_path, enabled, regex)
        except OSError as e:
            self.status.set(f"Error saving execution time setting: {e}", widgets.STATUS_FAIL)
            return False
        self.execution_time_modified = False
        return True

    # ── paths ───────────────────────────────────────────────────────────────

    def _config_path(self) -> str:
        config = self.project_state.current_config
        assert config is not None
        return os.path.join(self.arguments.project_config_dir, config)

    def _file_path(self, name: str) -> str:
        config = self.project_state.current_config
        assert config is not None
        if name == "compile.sh":
            return get_per_config_compile_script_path(self.arguments.project_config_dir, config)
        if name == "compile_validate.sh":
            return get_per_config_validation_compile_script_path(self.arguments.project_config_dir, config)
        return os.path.join(self._config_path(), name)

    # ── loading ─────────────────────────────────────────────────────────────

    def has_unsaved_changes(self) -> bool:
        """Whether anything in the Editor tab is waiting to be saved."""
        return any(editor.document().isModified() for editor in self.editors.values()) or self.execution_time_modified

    def _on_config_changed(self) -> None:
        config = self.project_state.current_config
        if config is None:
            self._clear()
        elif config == self._loaded_config and (self.has_unsaved_changes() or self._disk_state() == self._loaded_state):
            # the selection was only refreshed (after a save, a run, an override added): keep what is being edited,
            # and do not reload what is shown anyway (a reload moves the cursor to the start and clears the undo)
            return
        else:
            self.load()

    def _clear(self) -> None:
        self._loaded_config = None
        for editor in self.editors.values():
            editor.setReadOnly(True)
            editor.set_text("")
        self._loading = True
        try:
            self.execution_time_enabled.setChecked(False)
            self.execution_time_regex.setText(DEFAULT_EXECUTION_TIME_REGEX)
        finally:
            self._loading = False
        self.execution_time_modified = False
        self.execution_time_test_label.setText("")
        self._update_execution_time_state()
        self.compile_override_button.setText("Add Override")
        self.validate_script_button.setText("Add validate.sh")
        self.validation_compile_override_button.setText("Add Override")
        self.sub_tab_labels["compile_validate.sh"] = BASE_LABELS["compile_validate.sh"]
        self._refresh_marks()

    def load(self) -> None:
        """Show the files of the selected configuration, dropping unsaved changes."""
        config = self.project_state.current_config
        if config is None:
            self._clear()
            return
        self._loaded_config = config
        self._load_file("execute.sh")
        self._load_compile_override()
        self._load_validate_script()
        self._load_validation_compile_override()
        self._load_execution_time_settings()
        self._refresh_marks()
        self._loaded_state = self._disk_state()
        self.project_state.publish(ResultsChanged())

    def _disk_state(self) -> Tuple[Tuple[str, Optional[str]], ...]:
        """The content of every file the tab shows (None: does not exist), to tell whether a reload would change it."""
        paths = [self._file_path(name) for name in self.editors]
        config_path = os.path.join(self.arguments.project_config_dir, self.project_state.current_config or "")
        paths.append(os.path.join(config_path, EXECUTION_TIME_SETTINGS_FILE))
        state: List[Tuple[str, Optional[str]]] = []
        for path in paths:
            try:
                with open(path, "r") as f:
                    state.append((path, f.read()))
            except OSError:
                state.append((path, None))
        return tuple(state)

    def _load_file(self, name: str) -> bool:
        """Fill the editor of ``name`` from its file; False (and a read-only placeholder) if it does not exist."""
        path = self._file_path(name)
        editor = self.editors[name]
        editor.setReadOnly(False)
        exists = os.path.exists(path)
        if exists:
            try:
                with open(path, "r") as f:
                    editor.set_text(f.read())
            except Exception as e:
                editor.set_text(f"Error loading file: {e}")
        elif name in PLACEHOLDERS:
            editor.set_text(PLACEHOLDERS[name])
            editor.setReadOnly(True)
        else:
            editor.set_text(f"File not found: {path}")
        return exists

    def _load_compile_override(self) -> None:
        exists = self._load_file("compile.sh")
        self.compile_override_button.setText("Remove Override" if exists else "Add Override")

    def _load_validate_script(self) -> None:
        exists = self._load_file("validate.sh")
        self.validate_script_button.setText("Remove validate.sh" if exists else "Add validate.sh")

    def _load_validation_compile_override(self) -> None:
        exists = self._load_file("compile_validate.sh")
        # An override without a validate.sh has no effect; say so in the tab label rather than in the editor, so
        # the note can never end up in the file.
        ignored = exists and not has_validate_script(self._config_path())
        self.sub_tab_labels["compile_validate.sh"] = (
            "compile_validate.sh (ignored)" if ignored else "compile_validate.sh (override)"
        )
        self.validation_compile_override_button.setText("Remove Override" if exists else "Add Override")
        self._refresh_marks()

    def _load_execution_time_settings(self) -> None:
        """Show the execution time setting stored for the selected configuration."""
        enabled, regex = read_execution_time_settings(self._config_path())
        # loading writes both widgets, which must not look like an edit
        self._loading = True
        try:
            self.execution_time_enabled.setChecked(enabled)
            self.execution_time_regex.setText(regex)
        finally:
            self._loading = False
        self.execution_time_modified = False
        self.execution_time_test_label.setText("")
        self._update_execution_time_state()

    def _refresh_marks(self) -> None:
        """Mark the sub tabs and the Editor tab that have unsaved changes with a "*"."""
        for index, name in enumerate(FILES):
            modified = self.editors[name].document().isModified()
            if name == "execute.sh":
                # the execution time setting is edited in this tab but is no text area
                modified = modified or self.execution_time_modified
            label = self.sub_tab_labels[name]
            self.notebook.setTabText(index, f"{label} *" if modified else label)
        # imported here: the main window imports the panels, so a module level import would be circular
        self.tabs.set_tab_title(TAB_EDITOR, "Editor *" if self.has_unsaved_changes() else "Editor")

    # ── add / remove the optional files ─────────────────────────────────────

    def _read(self, path: str) -> str:
        if not os.path.exists(path):
            return ""
        with open(path, "r") as f:
            return f.read()

    def _toggle_compile_override(self) -> None:
        config = self.project_state.current_config
        if not config:
            return
        path = self._file_path("compile.sh")
        if os.path.exists(path):
            if not dialogs.ask_yes_no(
                self,
                "Remove Override",
                "Remove the compile.sh override for this configuration?\n\n"
                "The configuration will use the shared compile.sh instead.",
            ):
                return
            os.remove(path)
            message = "Removed compile.sh override for this configuration"
        else:
            write_script_file(path, self._read(get_shared_compile_script_path(self.arguments.project_config_dir)))
            message = "Added compile.sh override for this configuration"
        self._load_compile_override()
        self.project_state.publish(ConfigurationsChanged())
        self.status.set(message, widgets.STATUS_OK, reset_ms=2000)

    def _toggle_validate_script(self) -> None:
        if not self.project_state.current_config:
            return
        path = self._file_path("validate.sh")
        if os.path.exists(path):
            if not dialogs.ask_yes_no(
                self,
                "Remove validate.sh",
                "Remove validate.sh for this configuration?\n\n"
                "Correctness will then be determined by execute.sh alone.",
            ):
                return
            os.remove(path)
            message = "Removed validate.sh for this configuration"
        else:
            write_script_file(path, self._read(self._file_path("execute.sh")))
            message = "Added validate.sh for this configuration"
        self._load_validate_script()
        self._load_validation_compile_override()
        self.project_state.publish(ConfigurationsChanged())
        self.status.set(message, widgets.STATUS_OK, reset_ms=2000)

    def _toggle_validation_compile_override(self) -> None:
        config = self.project_state.current_config
        if not config:
            return
        path = self._file_path("compile_validate.sh")
        if os.path.exists(path):
            if not dialogs.ask_yes_no(
                self,
                "Remove Override",
                "Remove the compile_validate.sh override for this configuration?\n\n"
                "validate.sh will then run against the same build as execute.sh.",
            ):
                return
            os.remove(path)
            message = "Removed compile_validate.sh override for this configuration"
        else:
            if not has_validate_script(self._config_path()):
                dialogs.show_warning(
                    self,
                    "No validate.sh",
                    "This configuration has no validate.sh, so a compile_validate.sh is ignored.\n\n"
                    "Add a validate.sh first to make the separate validation build take effect.",
                )
            source = resolve_compile_script_path(self.arguments.project_config_dir, config)
            write_script_file(path, self._read(source))
            message = "Added compile_validate.sh override for this configuration"
        self._load_validation_compile_override()
        self.project_state.publish(ConfigurationsChanged())
        self.status.set(message, widgets.STATUS_OK, reset_ms=2000)

    # ── saving ──────────────────────────────────────────────────────────────

    def _save_clicked(self) -> None:
        self.save()

    def save(self) -> bool:
        """Write the changed files; False if something was rejected or could not be written."""
        if not self.project_state.current_config:
            self.status.set("No configuration selected", widgets.STATUS_FAIL)
            return False
        config_path = self._config_path()
        saved_files: List[str] = []

        if self.execution_time_modified:
            if not self._save_execution_time_settings(config_path):
                return False
            saved_files.append("execution time setting")
            self._refresh_marks()

        for name in FILES:
            editor = self.editors[name]
            if not editor.document().isModified():
                continue
            try:
                with open(os.path.join(config_path, name), "w") as f:
                    f.write(editor.text().rstrip())
            except Exception as e:
                self.status.set(f"Error saving file {name}: {e}", widgets.STATUS_FAIL)
                self._refresh_marks()
                return False
            editor.document().setModified(False)
            saved_files.append(name)

        self._refresh_marks()
        if not saved_files:
            self.status.set("No changes to save")
            return True
        self.status.set(f"Saved {', '.join(saved_files)}", widgets.STATUS_OK, reset_ms=2000)
        for script_name in ("compile.sh", "compile_validate.sh"):
            if script_name in saved_files:
                self._validate_compile_script(os.path.join(config_path, script_name))
        self._loaded_state = self._disk_state()
        self.project_state.publish(ConfigurationsChanged())
        return True

    def _validate_compile_script(self, path: str) -> None:
        try:
            with open(path, "r") as f:
                content = f.read()
        except Exception as e:
            self.status.set(f"Error validating compile.sh: {e}", widgets.STATUS_FAIL)
            return
        if not uses_compiler_variables(content):
            dialogs.show_warning(self, COMPILE_SCRIPT_WARNING_TITLE, COMPILE_SCRIPT_WARNING)

    # ── what the main window calls ──────────────────────────────────────────

    def confirm_leave(self) -> bool:
        """Ask what to do with unsaved changes before another configuration is selected.

        True if the selection may change (nothing to save, saved, or discarded on request); False to keep the
        current configuration (the changes could not be saved).
        """
        if not self.has_unsaved_changes():
            return True
        if dialogs.ask_yes_no(self, "Unsaved Changes", "You have unsaved changes. Save before switching?"):
            return self.save()
        return True

    def save_shortcut(self) -> None:
        """Ctrl+S: saves what the window in front shows (the compilation editor, or the Editor tab)."""
        editor = self._compilation_editor
        if editor is not None and editor.isVisible() and editor.isActiveWindow():
            editor.save()
        elif self.tabs.current_tab() == TAB_EDITOR:
            self.save()

    def open_compilation_editor(self) -> None:
        """Open the compilation editor window (shared compile.sh and settings), or bring it to the front."""
        if self._compilation_editor is None:
            self._compilation_editor = CompilationEditor(self.arguments, self.project_state, self.status, self)
        self._compilation_editor.open()

    def cancel_jobs(self) -> None:
        if self._compilation_editor is not None:
            self._compilation_editor.cancel_jobs()

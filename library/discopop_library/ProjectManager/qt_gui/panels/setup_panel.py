# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Setup stage: how the project is built. The shared compile.sh, the shared validation build script and the
settings files, with Test Compilation and Derive; what is project code: the instrumentation scope and the excluded
directories.

Ported from the compilation editor window (``gui/mixins/compilation_editor.py`` in the Tk GUI); here it is a stage of
the sidebar, above Configure, and the output of a test compilation goes to the output pane.
"""

import copy
import os
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.compile_script import (
    VALIDATION_COMPILE_SCRIPT_NAME,
    get_shared_compile_script_path,
    get_shared_validation_compile_script_path,
)
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.excluded_directories import ExcludedDirectoriesTree
from discopop_library.ProjectManager.qt_gui.help_dialogs import help_button
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.qt_gui.panel import Panel, TabHost
from discopop_library.ProjectManager.qt_gui.project_environment_widget import ProjectEnvironmentWidget
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.tabs import TAB_SETUP
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
from discopop_library.ProjectManager.services.project_state import (
    AutotuningChanged,
    ConfigurationsChanged,
    HotspotsChanged,
    PatternsChanged,
    ProjectEnvironmentChanged,
    ProjectState,
    ResultsChanged,
)
from discopop_library.ProjectManager.utilities.reset import reset_project
from discopop_library.ProjectManager.utilities.scriptFiles import write_script_file

DERIVE_DISABLED_TOOLTIP = "Save all changes before deriving settings"
TEST_BUTTON_TEXT = "Test Compilation"


EXCLUDED_DIRECTORIES_TITLE = "Excluded directories"
EXCLUDED_DIRECTORIES_HINT = (
    "Checked directories are no project code, e.g. dependencies fetched into the build directory (build/_deps):"
    " they are neither instrumented nor part of the file mapping and the AST. Saved at once; takes effect with the"
    " next build."
)

RESET_RESULTS_TEXT = "Reset Execution Results…"
RESET_PROJECT_TEXT = "Reset Project…"
RESET_RESULTS_HINT = (
    "<b>Reset execution results</b> deletes the measured runs of all configurations and the reports."
    " Everything else stays."
)
RESET_PROJECT_HINT = (
    "<b>Reset project</b> deletes everything in .discopop except the configurations, compile.sh and the settings:"
    " profiling data, suggestions, hotspot measurements, autotuning results, measured runs and reports."
)


class SetupPanel(Panel):
    """The files of the project's configuration directory shared by all configurations.

    Saving, deriving settings and changing the shared validation build script publish ``ConfigurationsChanged``: they
    change what the configurations can execute. Files without unsaved changes are read again when the stage is shown
    and on ``ConfigurationsChanged`` (the wizard writes them, too). ``tabs`` is the main window: unsaved changes show as
    "Setup *" in the sidebar.

    The instrumentation scope is saved with the files and publishes ``ProjectEnvironmentChanged``. Its one-click fix
    rewrites scripts of the configurations, too: ``may_rewrite_scripts`` may veto it (the Configuration Setup stage
    holds unsaved changes), ``scripts_rewritten`` is called afterwards (it reloads them).
    """

    output_title = "Setup"

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        tabs: TabHost,
        parent: Optional[QWidget] = None,
        *,
        may_rewrite_scripts: Optional[Callable[[], bool]] = None,
        scripts_rewritten: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(arguments, project_state, status, parent)
        self.tabs = tabs
        self._may_rewrite_configuration_scripts = may_rewrite_scripts
        self._configuration_scripts_rewritten = scripts_rewritten
        self.editors: Dict[str, widgets.ScriptEditor] = {}
        self.tab_index: Dict[str, int] = {}
        self._testing = False
        # the chip of the last test compilation, shown while nothing is unsaved
        self._test_chip: Tuple[str, str, str] = (widgets.CHIP_IDLE, "", "")
        self.console = self.make_console()

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
        self.header = widgets.PanelHeader(
            "Project Setup",
            "Shared by all configurations: how the project is built and what is project code.",
            [self.derive_button, self.test_compilation_button, self.save_button],
        )
        self.excluded_directories = ExcludedDirectoriesTree(arguments.project_root, arguments.project_dir)
        self.excluded_directories.setMinimumHeight(140)
        self.excluded_directories.changed.connect(self._on_excluded_directories_changed)
        self.excluded_directories.failed.connect(lambda message: self.status.set(message, widgets.STATUS_FAIL))
        excluded_section = widgets.FormSection(EXCLUDED_DIRECTORIES_TITLE)
        excluded_section.add_widget(self.excluded_directories, EXCLUDED_DIRECTORIES_HINT)
        # what is project code: the scope says what is in, the excluded directories what is out of it
        self.environment_widget = ProjectEnvironmentWidget(
            arguments.project_root, arguments.project_config_dir, self._may_rewrite_scripts, self
        )
        self.environment_widget.edited.connect(self._update_tabs)
        self.environment_widget.scripts_rewritten.connect(self._on_scripts_rewritten)
        self.environment_widget.load()
        project_code = QHBoxLayout()
        project_code.setContentsMargins(0, 0, 0, 0)
        project_code.addWidget(self.environment_widget, 1)
        project_code.addWidget(excluded_section, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.header)
        layout.addWidget(self.notebook, 1)
        layout.addLayout(project_code)
        layout.addWidget(self._danger_zone())

        self.load_files()
        project_state.subscribe(ConfigurationsChanged, lambda _event: self.reload_unmodified())

    def _danger_zone(self) -> QFrame:
        """The card of the resets: framed in red, each with what it deletes and what it keeps."""
        self.reset_results_button = widgets.danger_outline_button(RESET_RESULTS_TEXT, self._confirm_reset_results)
        self.reset_project_button = widgets.danger_outline_button(RESET_PROJECT_TEXT, self._confirm_reset_project)
        card = QFrame()
        card.setObjectName(widgets.DANGER_ZONE_NAME)
        grid = QGridLayout(card)
        grid.setContentsMargins(14, 10, 14, 12)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)
        title = widgets.heading_label("⚠ Danger zone")
        title.setObjectName(widgets.DANGER_TITLE_NAME)
        grid.addWidget(title, 0, 0, 1, 2)
        for row, (button, text) in enumerate(
            ((self.reset_results_button, RESET_RESULTS_HINT), (self.reset_project_button, RESET_PROJECT_HINT)), 1
        ):
            hint = QLabel(text)
            hint.setWordWrap(True)
            grid.addWidget(hint, row, 0)
            grid.addWidget(button, row, 1)
        grid.setColumnStretch(0, 1)
        self.danger_zone = card
        return card

    def set_blocked(self, blocked: bool) -> None:
        """No reset while a run writes into the project (the main window calls this)."""
        for button in (self.reset_results_button, self.reset_project_button):
            button.setEnabled(not blocked)
            button.setToolTip("Not while a run is in progress." if blocked else "")

    # ── resets ──────────────────────────────────────────────────────────────

    def _confirm_reset_results(self) -> None:
        if dialogs.ask_yes_no(
            self,
            "Confirm Reset",
            "Are you sure you want to reset execution results?\nThis will delete all execution data and reports.",
        ):
            self.reset(results_only=True)

    def _confirm_reset_project(self) -> None:
        if dialogs.ask_yes_no(
            self,
            "Confirm Reset",
            "Are you sure you want to reset the entire project?\n"
            "This will delete all data except the configuration files.",
        ):
            self.reset(results_only=False)

    def reset(self, *, results_only: bool) -> None:
        arguments = copy.copy(self.arguments)
        arguments.reset = not results_only
        arguments.reset_execution_results = results_only
        what = "Execution results" if results_only else "Project"
        try:
            reset_project(arguments)
        except Exception as e:
            self.status.set(f"Error resetting {what.lower()}: {e}", widgets.STATUS_FAIL)
            return
        self.status.set(f"{what} reset successfully", widgets.STATUS_OK)
        self.project_state.publish(ResultsChanged())
        if not results_only:
            # the profiling data, the suggestions, the hotspots and the autotuner's results are gone too
            for event in (PatternsChanged(), HotspotsChanged(), AutotuningChanged()):
                self.project_state.publish(event)

    def _on_excluded_directories_changed(self, excluded: List[str]) -> None:
        self.status.set(
            "Excluded directories: " + (", ".join(excluded) if excluded else "none"), widgets.STATUS_OK, reset_ms=3000
        )
        # they change what the builds of every configuration instrument
        self.project_state.publish(ConfigurationsChanged())

    def output_console(self) -> widgets.OutputConsole:
        return self.console

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 (Qt's name)
        # the files may have been changed outside the GUI meanwhile, and a build may have created directories
        self.reload_unmodified()
        self.excluded_directories.reload()
        super().showEvent(event)

    # ── the instrumentation scope ───────────────────────────────────────────

    def _may_rewrite_scripts(self) -> bool:
        """The one-click fix rewrites files the editors show: not while they hold unsaved changes."""
        if any(editor.document().isModified() for editor in self.editors.values()):
            dialogs.show_warning(
                self,
                "Unsaved changes",
                "Save or discard the changes of compile.sh and the settings first: the scripts are rewritten on disk.",
            )
            return False
        return self._may_rewrite_configuration_scripts is None or self._may_rewrite_configuration_scripts()

    def _on_scripts_rewritten(self) -> None:
        self.reload_unmodified()
        if self._configuration_scripts_rewritten is not None:
            self._configuration_scripts_rewritten()
        self.status.set("Replaced DP_PROJECT_ROOT_DIR by DP_RUN_ROOT_DIR", widgets.STATUS_OK, reset_ms=2000)
        self.project_state.publish(ConfigurationsChanged())

    # ── loading ─────────────────────────────────────────────────────────────

    def _path(self, name: str) -> str:
        return os.path.join(self.arguments.project_config_dir, name)

    def _disk_content(self, name: str) -> Tuple[str, bool]:
        """What the editor of ``name`` shows for the file on disk, and whether it is read-only (absent optional
        file: saving must not create it from the placeholder text)."""
        path = self._path(name)
        if os.path.exists(path):
            try:
                with open(path, "r") as f:
                    content = f.read()
                return (format_json_content(content) if name.endswith(".json") else content), False
            except Exception as e:
                return f"Error loading file: {e}", False
        if name in OPTIONAL_FILES:
            return OPTIONAL_FILE_PLACEHOLDERS[name], True
        return f"File not found: {path}", False

    def load_files(self) -> None:
        """Show the files from disk, dropping unsaved changes; derived settings that do not exist stay disabled."""
        for name in self.editors:
            self._load_file(name)
        self._update_shared_validation_button()
        self._update_tabs()

    def reload_unmodified(self) -> None:
        """Read the files again whose editors hold no unsaved changes; an unchanged file keeps its cursor."""
        for name, editor in self.editors.items():
            if editor.document().isModified():
                continue
            text, read_only = self._disk_content(name)
            if text != editor.text() or read_only != editor.isReadOnly():
                self._load_file(name)
        if self.environment_widget.is_modified():
            # the scripts may use the scope variable now, or no longer
            self.environment_widget.refresh()
        else:
            # the wizard or the MCP server may have stored another scope
            self.environment_widget.load()
        self._update_shared_validation_button()
        self._update_tabs()

    def _load_file(self, name: str) -> None:
        editor = self.editors[name]
        text, read_only = self._disk_content(name)
        editor.setReadOnly(False)
        editor.set_text(text)
        editor.setReadOnly(read_only)

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
        unsaved = self.has_unsaved_changes()
        self.tabs.set_tab_title(TAB_SETUP, f"{TAB_SETUP} *" if unsaved else TAB_SETUP)
        self._update_chip()
        self._update_buttons()

    def _update_chip(self) -> None:
        if self.has_unsaved_changes():
            self.header.chip.set_status(widgets.CHIP_WARN, "Unsaved changes", "Save with Ctrl+S.")
        else:
            self.header.chip.set_status(*self._test_chip)

    def has_unsaved_changes(self) -> bool:
        return (
            any(editor.document().isModified() for editor in self.editors.values())
            or self.environment_widget.is_modified()
        )

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
        # only this file is reloaded: the other tabs may hold unsaved changes (this one cannot: without the file it is
        # read-only, and a removed file has nothing left to keep)
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
        if self.environment_widget.is_modified():
            if not self.environment_widget.save():
                self._update_tabs()
                return False
            saved_files.append("instrumentation scope")
            self.project_state.publish(ProjectEnvironmentChanged())
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
        # compile.sh may use the scope variable now, or no longer
        self.environment_widget.refresh()
        self._update_tabs()
        if not saved_files:
            self.status.set("No changes to save")
            return True
        self.status.set(f"Saved {', '.join(saved_files)}", widgets.STATUS_OK, reset_ms=2000)
        if saved_files != ["instrumentation scope"]:
            self.project_state.publish(ConfigurationsChanged())
        return True

    # ── test compilation ────────────────────────────────────────────────────

    def test_compilation(self) -> None:
        """Compile once with the shown compile.sh and seq_settings.json (saved first); no result is recorded.

        The output goes to the output pane, the outcome to the chip of the header.
        """
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
        self._test_chip = (widgets.CHIP_BUSY, "Compiling…", "")
        self._update_chip()
        self.console.set_text("Running compilation test...\n")
        self.output_requested.emit()
        arguments = self.arguments

        def compile_once(_ctx: WorkContext) -> Optional[Tuple[int, float, str, str]]:
            return run_test_compilation(arguments)

        def handle(event: WorkEvent) -> None:
            if not isinstance(event, WorkFinished):
                return
            result = event.result if event.error is None else None
            if event.error is not None or result is None:
                reason = str(event.error) if event.error is not None else "settings not found"
                self.status.set(f"✗ Compilation test failed: {reason}", widgets.STATUS_FAIL)
                self.console.set_text(f"Compilation test failed: {reason}\n")
                self._test_chip = (widgets.CHIP_ERROR, "Test compilation failed", reason)
            else:
                return_code, elapsed, stdout, stderr = result
                if return_code == 0:
                    self.status.set(f"✓ Compilation successful ({elapsed:.2f}s)", widgets.STATUS_OK)
                    self._test_chip = (widgets.CHIP_OK, f"Compiles ({elapsed:.2f}s)", "")
                else:
                    self.status.set(
                        f"✗ Compilation failed (exit code: {return_code}, {elapsed:.2f}s)", widgets.STATUS_FAIL
                    )
                    self._test_chip = (
                        widgets.CHIP_ERROR,
                        f"Compilation failed (exit code {return_code})",
                        "The output is in the output pane below.",
                    )
                self.console.set_text(describe_compilation_test(return_code, elapsed, stdout, stderr))
            self._testing = False
            self.test_compilation_button.setText(TEST_BUTTON_TEXT)
            self._update_chip()
            self._update_buttons()

        start_work(self, compile_once, handle)

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

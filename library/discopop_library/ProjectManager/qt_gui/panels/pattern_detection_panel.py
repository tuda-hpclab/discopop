# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Pattern Detection tab: runs ``discopop_explorer`` on the profiling data and opens the suggestions.

Ported from ``gui/mixins/explorer_integration.py``. A run with "Show graph visualization" is a subprocess like a
plain run (``discopop_explorer --visualize``): the explorer opens its own visualizer window, so this window stays
responsive and Stop works.
"""

import importlib.util
import os
import queue
from typing import Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFormLayout,
    QFrame,
    QLabel,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.plots import hotspot_data

from discopop_library.ProjectManager.qt_gui import dialogs, suggestion_browser, widgets
from discopop_library.ProjectManager.qt_gui.widgets import CodeView
from discopop_library.ProjectManager.qt_gui.job_adapter import QtJobAdapter
from discopop_library.ProjectManager.qt_gui.suggestion_table import NO_SUGGESTIONS_TEXT, SuggestionTable
from discopop_library.ProjectManager.qt_gui.tabs import TAB_HOTSPOT, TAB_PATTERN_DETECTION, TAB_PROFILING
from discopop_library.ProjectManager.qt_gui.panel import Panel, TabHost
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.services import explorer_state
from discopop_library.ProjectManager.services.commands import explorer_command
from discopop_library.ProjectManager.services.explorer_state import (
    DEFAULT_DETECTION_MODE,
    DETECTION_MODES,
    NO_STATES_DETECTION_MODE,
)
from discopop_library.ProjectManager.services.jobs import (
    CancelPolicy,
    JobEvent,
    JobFailedToStart,
    JobFinished,
    JobOutput,
    JobRunner,
    JobSpec,
)
from discopop_library.ProjectManager.services.project_state import (
    ConfigurationsChanged,
    HotspotsChanged,
    PatternsChanged,
    ProjectDirectoriesChanged,
    ProjectState,
    ResultsChanged,
)
from discopop_library.ProjectManager.services.requests import ExplorerRequest
from discopop_library.ProjectManager.services.patches import discover_patches
from discopop_library.ProjectManager.services.suggestions import (
    SuggestionInfo,
    load_suggestions,
    suggestion_detail_fields,
)
from discopop_library.ProjectManager.services.text import clean_ansi_output
from discopop_library.ProjectManager.services.workflow_status import detection_is_stale
from discopop_library.ProjectManager.services.vscode import (
    VSCODE_NOT_FOUND_MESSAGE,
    find_code_executable,
    open_file_at,
    open_project,
)

PATTERN_TYPES = ("reduction", "doall", "task")
_DEFAULT_PATTERN_TYPES = ("reduction", "doall")
_RUN_TEXT = "Run Pattern Detection"
_NONE_FOUND_TEXT = "No patterns found."
# the width of the settings column
_SETTINGS_WIDTH = 340
_SELECT_HINT = "Select a suggestion to see its details and patch."
_VISUALIZER_MISSING = (
    "Graph visualization needs the package discopop_gui, which is not installed.\n"
    "Install it (pip install discopop-gui) or run the detection without 'Show graph visualization'."
)


def visualizer_available() -> bool:
    """Whether ``discopop_explorer --visualize`` can import its visualizer."""
    return importlib.util.find_spec("discopop_gui") is not None


class PatternDetectionPanel(Panel):
    """The Pattern Detection tab.

    The panel owns the enabled state and tooltip of its tab (disabled until a profiling run exists); the Autotuning
    tab is not touched here. ``tabs.show_tab(TAB_HOTSPOT)`` is called by the hotspot hint. After a run the
    panel publishes ``PatternsChanged``. The window calls :meth:`refresh` once the panel sits in its tab, as adding the
    tab may replace the widget the state was set on.
    """

    output_title = "Patterns"

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
        self.explorer_running = False
        self._explorer_stopped = False
        self._explorer_job: Optional[JobRunner] = None
        self.browser: Optional[QWidget] = None
        self._selected: Optional[SuggestionInfo] = None

        self.hotspot_hint = self._build_hotspot_hint()

        self.run_button = widgets.RunStopButton(_RUN_TEXT, self.run_pattern_detection, self.stop_pattern_detection)
        self.run_button.setEnabled(False)
        self.header = widgets.PanelHeader(
            "Pattern Detection",
            "Finds parallelization suggestions in the profiling data.",
            [self.run_button],
        )

        self.console = self.make_console()
        self.table = SuggestionTable()
        # what concerns all suggestions: below the table, at the right of their number
        self.browse_button = widgets.create_button(
            "Browse / Edit Patches…", self.open_suggestion_browser, tooltip="Look at and edit the patches"
        )
        self.vscode_button = widgets.create_button(
            "Show Suggestions in VSCode", self.open_in_vscode, tooltip="Open the suggestions in VSCode"
        )
        for button in (self.browse_button, self.vscode_button):
            button.setObjectName(widgets.COMPACT_NAME)
            button.setEnabled(False)
            self.table.footer_layout.addWidget(button)
        self.table.current_changed.connect(self._on_suggestion_selected)
        self.results_stack = QStackedWidget()
        self.results_stack.addWidget(self._build_results())
        self.results_stack.addWidget(self._build_locked_view())

        self.splitter = widgets.SettingsSplitter(self._build_settings(), self.results_stack, _SETTINGS_WIDTH)
        self.header.add_action(self.splitter.toggle_button, 0)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.addWidget(self.header)
        layout.addWidget(self.splitter, 1)

        # prerequisites may appear after a profiling run, the hotspot hint follows the hotspot results
        for event_type in (
            ResultsChanged,
            ConfigurationsChanged,
            HotspotsChanged,
            PatternsChanged,
            ProjectDirectoriesChanged,
        ):
            project_state.subscribe(event_type, lambda _event: self.refresh())
        self.refresh()

    def output_console(self) -> widgets.OutputConsole:
        return self.console

    # ── building ────────────────────────────────────────────────────────────

    def _build_hotspot_hint(self) -> widgets.FormSection:
        card = widgets.FormSection("Hotspots")
        card.add_widget(
            widgets.error_label("No hotspot detection results available."),
            "Pattern detection restricts its analysis to the hot parts of the program when hotspot information is "
            "available; measuring hotspots first can speed this step up significantly.",
        )
        self.goto_hotspot_button = widgets.create_button("Go to Hotspots", lambda: self.tabs.show_tab(TAB_HOTSPOT))
        card.add_widget(widgets.hbox(self.goto_hotspot_button, None))
        return card

    def _build_settings(self) -> QWidget:
        self.pattern_checks: Dict[str, QCheckBox] = {}
        pattern_row: List[QWidget] = []
        for pattern in PATTERN_TYPES:
            check = QCheckBox(pattern)
            check.setChecked(pattern in _DEFAULT_PATTERN_TYPES)
            self.pattern_checks[pattern] = check
            pattern_row.append(check)
        self.jobs_selector = widgets.ThreadSelector()

        detection = widgets.FormSection("Detection")
        detection.add_row("Pattern types:", widgets.hbox(*pattern_row, None))
        detection.add_row("Threads:", self.jobs_selector, "auto = unlimited; custom counts can be typed.")

        self.mode_buttons: Dict[str, QRadioButton] = {}
        mode_group = QButtonGroup(self)
        mode_column = QVBoxLayout()
        mode_column.setContentsMargins(0, 0, 0, 0)
        for mode_value, mode_label in DETECTION_MODES:
            button = QRadioButton(mode_label)
            button.setChecked(mode_value == DEFAULT_DETECTION_MODE)
            mode_group.addButton(button)
            self.mode_buttons[mode_value] = button
            mode_column.addWidget(button)
        self.visualize_check = QCheckBox("Show graph visualization")
        self.visualize_check.setToolTip(
            "The explorer opens the graphs in a window of its own; this window stays responsive while it runs."
        )
        advanced = widgets.FormSection()
        advanced.add_row(
            "Dependency data:",
            mode_column,
            "'no_states' ignores the profiler's callpath state markers, which also reclassifies the affected "
            "dependencies from dynamic to static. Re-running detection in either mode replaces the existing "
            "suggestions.",
        )
        advanced.add_widget(self.visualize_check, "The graphs open in a window of their own.")
        self.advanced = widgets.CollapsibleSection("Advanced", advanced, summary="dependency data, graph visualization")

        column = QWidget()
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.addWidget(detection)
        column_layout.addWidget(self.hotspot_hint)
        column_layout.addWidget(self.advanced)
        return column

    def _build_results(self) -> QWidget:
        self.detail_title = widgets.heading_label("")
        self.open_vscode_button = widgets.create_button(
            "Open Code in VSCode",
            self.open_selected_in_vscode,
            tooltip="Open the source file at the code of the selected suggestion",
        )
        self.open_vscode_button.setEnabled(False)
        self.detail_form = QFormLayout()
        self.detail_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        self.detail_form.setContentsMargins(0, 0, 8, 0)
        fields = QWidget()
        fields_layout = QVBoxLayout(fields)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        fields_layout.addLayout(self.detail_form)
        fields_layout.addStretch(1)
        fields_area = QScrollArea()
        fields_area.setWidgetResizable(True)
        fields_area.setFrameShape(QFrame.Shape.NoFrame)
        fields_area.setWidget(fields)
        fields_area.setMinimumWidth(240)
        self.patch_view = CodeView()
        self.patch_view.setPlaceholderText("The patch of the suggestion appears here.")
        self.detail_body = QSplitter(Qt.Orientation.Horizontal)
        self.detail_body.addWidget(fields_area)
        self.detail_body.addWidget(self.patch_view)
        self.detail_body.setStretchFactor(1, 1)
        self.detail_body.setSizes([300, 700])
        self.detail_placeholder = widgets.empty_state_label(_SELECT_HINT)
        self.detail_stack = QStackedWidget()
        self.detail_stack.addWidget(self.detail_placeholder)
        self.detail_stack.addWidget(self.detail_body)
        detail = self.detail_area = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.setContentsMargins(0, 4, 0, 0)
        detail_layout.addLayout(widgets.hbox(self.detail_title, None, self.open_vscode_button))
        detail_layout.addWidget(self.detail_stack, 1)

        results = QSplitter(Qt.Orientation.Vertical)
        results.addWidget(self.table)
        results.addWidget(detail)
        results.setStretchFactor(0, 3)
        results.setStretchFactor(1, 2)
        results.setChildrenCollapsible(False)
        return results

    def _build_locked_view(self) -> QWidget:
        self.locked_title = widgets.heading_label("Needs profiling data", title=True)
        self.locked_reason = widgets.empty_state_label("")
        self.goto_profiling_button = widgets.primary_button(
            "Go to Profiling", lambda: self.tabs.show_tab(TAB_PROFILING)
        )
        view = QWidget()
        layout = QVBoxLayout(view)
        layout.addStretch(1)
        layout.addWidget(self.locked_title, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self.locked_reason)
        layout.addWidget(self.goto_profiling_button, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(2)
        return view

    # ── state ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Bring the enabled states, the chip, the results and the hints up to date with what is on disk."""
        dot_dp = self.arguments.dot_dp
        ready = explorer_state.explorer_prerequisites_met(dot_dp)

        self.hotspot_hint.setVisible(not hotspot_data.hotspots_available_for_explorer(dot_dp))
        self.run_button.setEnabled(ready and not self.explorer_running)

        infos = load_suggestions(dot_dp)
        if infos != self.table.suggestions():
            self.table.set_suggestions(infos)
        none_found = explorer_state.pattern_detection_executed(dot_dp) and not explorer_state.patterns_found(dot_dp)
        self.table.set_empty_text(_NONE_FOUND_TEXT if none_found else NO_SUGGESTIONS_TEXT)
        self.vscode_button.setEnabled(bool(infos))
        self.browse_button.setEnabled(bool(infos))
        self.detail_area.setVisible(bool(infos))
        self._update_chip(ready, len(infos), none_found)

        if ready:
            self.results_stack.setCurrentIndex(0)
        else:
            lines = ["Profiling data not found."]
            missing = explorer_state.missing_explorer_files(dot_dp)
            if missing:
                lines.append("Missing in " + dot_dp + ":")
                lines.extend("  " + os.path.relpath(path, dot_dp) for path in missing)
            lines.append("Run the Profiling stage first.")
            self.locked_reason.setText("\n".join(lines))
            self.results_stack.setCurrentIndex(1)
        # the tab stays reachable: without profiling data it explains what to do instead of being grayed out
        self.tabs.set_tab_enabled(TAB_PATTERN_DETECTION, True, "")

    def _update_chip(self, ready: bool, count: int, none_found: bool) -> None:
        chip = self.header.chip
        dot_dp = self.arguments.dot_dp
        if self.explorer_running:
            chip.set_status(widgets.CHIP_BUSY, "Running...")
        elif (stale := explorer_state.stale_profiling_data_message(self.arguments)) is not None:
            chip.set_status(widgets.CHIP_WARN, "Project directories changed", stale)
        elif not ready:
            chip.set_status(widgets.CHIP_IDLE, "Not run yet", "Needs profiling data from the Profiling stage.")
        elif detection_is_stale(dot_dp):
            chip.set_status(
                widgets.CHIP_WARN,
                "Profiling data newer than the results",
                "The profiling data changed after the last detection. Run it again to update the suggestions.",
            )
        elif none_found:
            chip.set_status(widgets.CHIP_WARN, "No suggestions found")
        elif count:
            chip.set_status(widgets.CHIP_OK, f"{count} suggestion{'' if count == 1 else 's'}")
        else:
            chip.set_status(widgets.CHIP_IDLE, "Not run yet")

    def snapshot_request(self) -> ExplorerRequest:
        """Read the panel into an immutable request; call on the main thread only."""
        selected = [pattern for pattern, check in self.pattern_checks.items() if check.isChecked()]
        return ExplorerRequest(
            enable_patterns=",".join(selected) if selected else ",".join(_DEFAULT_PATTERN_TYPES),
            jobs=self.jobs_selector.value(),
            ignore_dependency_states=self.mode_buttons[NO_STATES_DETECTION_MODE].isChecked(),
            visualize=self.visualize_check.isChecked(),
        )

    # ── running ─────────────────────────────────────────────────────────────

    def run_pattern_detection(self) -> None:
        if not explorer_state.explorer_prerequisites_met(self.arguments.dot_dp):
            dialogs.show_error(
                self,
                "Prerequisites Not Met",
                "Profiling data not found.\nPlease run the Profiling stage first.",
            )
            return
        if self.explorer_running:
            dialogs.show_error(self, "Already Running", "Pattern detection is already running.")
            return
        request = self.snapshot_request()
        if request.visualize and not visualizer_available():
            self.console.set_text(_VISUALIZER_MISSING + "\n")
            dialogs.show_warning(self, "Graph Visualization Not Available", _VISUALIZER_MISSING)
            return

        self.explorer_running = True
        self._explorer_stopped = False
        self.run_button.set_running(True)
        self._update_chip(True, len(self.table.suggestions()), False)
        self.output_requested.emit()
        self.status.set("⏳ Pattern detection in progress...", widgets.STATUS_BUSY)
        self.console.set_text("")
        self._start_explorer_job(request)

    def _start_explorer_job(self, request: ExplorerRequest) -> None:
        dot_dp = self.arguments.dot_dp
        self.console.append_text("Starting pattern detection...\n")
        self.console.append_text("Loading explorer configuration...\n")

        missing_files = explorer_state.missing_explorer_files(dot_dp)
        if missing_files:
            self.console.append_text("\nMissing required files:\n")
            for file_path in missing_files:
                self.console.append_text(f"  - {file_path}\n")
            self.console.append_text("\nError: Missing required profiling data files\n")
            self._on_complete(error=True)
            return

        mode = NO_STATES_DETECTION_MODE if request.ignore_dependency_states else DEFAULT_DETECTION_MODE
        self.console.append_text("Configuration:\n")
        self.console.append_text(f"  Patterns: {request.enable_patterns}\n")
        self.console.append_text(f"  Threads: {request.jobs}\n")
        self.console.append_text(f"  Dependency data: {mode}\n")
        if request.visualize:
            self.console.append_text("  Graph visualization: enabled (opens in a window of its own)\n")
        self.console.append_text("\nRunning pattern detection...\n\n")

        events: "queue.Queue[JobEvent]" = queue.Queue()
        # SIGTERM to the process group: the explorer may have started worker processes of its own
        job = JobRunner(
            JobSpec(
                explorer_command(request),
                cwd=dot_dp,
                cancel_policy=CancelPolicy.SIGTERM_GROUP,
                new_session=True,
            ),
            events,
        )
        self._explorer_job = job
        QtJobAdapter(self, events, self._on_job_event).start()
        job.start()

    def _on_job_event(self, event: JobEvent) -> None:
        """Handle one event of the explorer job; runs on the main thread."""
        if isinstance(event, JobOutput):
            cleaned = clean_ansi_output(event.line)
            if cleaned:
                self.console.append_text(cleaned + "\n")
        elif isinstance(event, JobFinished):
            self._explorer_job = None
            if event.cancelled or self._explorer_stopped:
                self.console.append_text("\nPattern detection stopped.\n")
                self._on_complete(stopped=True)
            elif event.returncode != 0:
                self.console.append_text(f"\nError: Explorer exited with return code {event.returncode}\n")
                self._on_complete(error=True)
            else:
                if not self._explorer_stopped:
                    self.console.append_text("\nPattern detection completed.\n")
                self._on_complete()
        elif isinstance(event, JobFailedToStart):
            self._explorer_job = None
            self.console.append_text(f"\nError: {event.error}\n")
            self._on_complete(error=True)

    def _on_complete(self, error: bool = False, stopped: bool = False) -> None:
        self.explorer_running = False
        self.run_button.set_running(False)
        self.refresh()
        # the Autotuning and Patch Repair tabs work on the freshly generated patches
        self.project_state.publish(PatternsChanged())
        if stopped:
            self.status.set("Pattern detection stopped", widgets.STATUS_STOP, reset_ms=3000)
        elif error:
            self.status.set("Pattern detection failed", widgets.STATUS_FAIL, reset_ms=3000)
        else:
            self.status.set("Pattern detection completed successfully", widgets.STATUS_OK, reset_ms=3000)

    def stop_pattern_detection(self) -> None:
        self._explorer_stopped = True
        job = self._explorer_job
        if job is not None:
            job.cancel()
        self.run_button.set_stopping()
        self.status.set("Stopping pattern detection...", widgets.STATUS_STOP)

    def cancel_jobs(self) -> None:
        job = self._explorer_job
        if job is not None:
            job.cancel()

    # ── the suggestions ─────────────────────────────────────────────────────

    def _on_suggestion_selected(self, info: Optional[SuggestionInfo]) -> None:
        self._selected = info
        self.open_vscode_button.setEnabled(info is not None)
        if info is None:
            self.detail_title.setText("")
            self.detail_stack.setCurrentWidget(self.detail_placeholder)
            return
        self.detail_title.setText(f"Suggestion {info.id}")
        while self.detail_form.rowCount():
            self.detail_form.removeRow(0)
        for label, value in suggestion_detail_fields(info):
            if label == "Suggestion":
                continue
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.detail_form.addRow(label + ":", value_label)
        filenames = discover_patches(self.arguments.dot_dp).get(info.id, [])
        self.patch_view.set_diff(suggestion_browser.read_suggestion_patches(self.arguments.dot_dp, info.id, filenames))
        self.detail_stack.setCurrentWidget(self.detail_body)

    def open_selected_in_vscode(self) -> None:
        info = self._selected
        if info is None or not info.file_path or info.start_line <= 0:
            self.open_in_vscode()
            return
        code_executable = find_code_executable()
        if code_executable is None:
            dialogs.show_error(self, "VSCode Not Found", VSCODE_NOT_FOUND_MESSAGE)
            return
        try:
            open_file_at(code_executable, info.file_path, info.start_line)
        except OSError as e:
            dialogs.show_error(self, "Failed to open VSCode", f"Could not launch VSCode:\n{e}")
            return
        self.status.set(f"Opening {info.location} in VSCode...", widgets.STATUS_BUSY, reset_ms=3000)

    def open_suggestion_browser(self) -> None:
        self.browser = suggestion_browser.open_suggestion_browser(self, self.arguments.dot_dp)

    def open_in_vscode(self) -> None:
        code_executable = find_code_executable()
        if code_executable is None:
            dialogs.show_error(self, "VSCode Not Found", VSCODE_NOT_FOUND_MESSAGE)
            return
        try:
            open_project(code_executable, self.arguments.dot_dp)
        except OSError as e:
            dialogs.show_error(self, "Failed to open VSCode", f"Could not launch VSCode:\n{e}")
            return
        self.status.set("Opening project in VSCode...", widgets.STATUS_BUSY, reset_ms=3000)

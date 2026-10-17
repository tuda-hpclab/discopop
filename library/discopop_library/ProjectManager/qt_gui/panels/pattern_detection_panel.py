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
import queue
from typing import Dict, List, Optional

from PySide6.QtWidgets import QButtonGroup, QCheckBox, QGroupBox, QRadioButton, QSplitter, QVBoxLayout, QWidget

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.plots import hotspot_data

from discopop_library.ProjectManager.qt_gui import dialogs, suggestion_browser, widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import QtJobAdapter
from discopop_library.ProjectManager.qt_gui.tabs import TAB_HOTSPOT, TAB_PATTERN_DETECTION
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
from discopop_library.ProjectManager.services.patches import count_patches
from discopop_library.ProjectManager.services.project_state import (
    ConfigurationsChanged,
    HotspotsChanged,
    PatternsChanged,
    ProjectState,
    ResultsChanged,
)
from discopop_library.ProjectManager.services.requests import ExplorerRequest
from discopop_library.ProjectManager.services.text import clean_ansi_output
from discopop_library.ProjectManager.services.vscode import VSCODE_NOT_FOUND_MESSAGE, find_code_executable, open_project

PATTERN_TYPES = ("reduction", "doall", "task")
_DEFAULT_PATTERN_TYPES = ("reduction", "doall")
_RUN_TEXT = "Run Pattern Detection"
_RUNNING_TEXT = "⟳ Running..."
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

        self.hotspot_hint = self._build_hotspot_hint()
        settings = self._build_settings()

        self.run_button = widgets.primary_button(_RUN_TEXT, self.run_pattern_detection)
        self.run_button.setEnabled(False)
        self.stop_button = widgets.danger_button("Stop", self.stop_pattern_detection)
        self.stop_button.setEnabled(False)
        self.vscode_button = widgets.create_button("Show Suggestions in VSCode", self.open_in_vscode)
        self.vscode_button.setEnabled(False)
        self.browse_button = widgets.create_button("Browse Suggestions", self.open_suggestion_browser)
        self.browse_button.setEnabled(False)
        self.no_suggestions_label = widgets.error_label("No patterns found.")
        self.no_suggestions_label.hide()

        left = QWidget()
        left_layout = widgets.vbox(
            self.hotspot_hint,
            settings,
            widgets.hbox(self.run_button, self.stop_button, None),
            widgets.hbox(self.vscode_button, None),
            widgets.hbox(self.browse_button, None),
            self.no_suggestions_label,
            None,
            margins=5,
        )
        left.setLayout(left_layout)

        self.console = widgets.OutputConsole()
        output_layout = QVBoxLayout()
        output_layout.addWidget(self.console)
        output = widgets.group_box("Output", output_layout)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(output)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([650, 650])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        # prerequisites may appear after a profiling run, the hotspot hint follows the hotspot results
        for event_type in (ResultsChanged, ConfigurationsChanged, HotspotsChanged, PatternsChanged):
            project_state.subscribe(event_type, lambda _event: self.refresh())
        self.refresh()

    # ── building ────────────────────────────────────────────────────────────

    def _build_hotspot_hint(self) -> QGroupBox:
        warning = widgets.error_label("⚠ No Hotspot Detection results available.")
        explanation = widgets.caption_label(
            "Pattern detection restricts its analysis to the hot parts of the program when hotspot\n"
            "information is available. Measuring hotspots first is therefore recommended: the\n"
            "filtering it enables can speed up this step significantly."
        )
        self.goto_hotspot_button = widgets.create_button(
            "Go to Hotspot Detection", lambda: self.tabs.show_tab(TAB_HOTSPOT)
        )
        return widgets.group_box(
            "Hotspot Information", widgets.vbox(warning, explanation, widgets.hbox(self.goto_hotspot_button, None))
        )

    def _build_settings(self) -> QGroupBox:
        self.pattern_checks: Dict[str, QCheckBox] = {}
        pattern_row: List[QWidget] = [widgets.heading_label("Pattern Types:")]
        for pattern in PATTERN_TYPES:
            check = QCheckBox(pattern)
            check.setChecked(pattern in _DEFAULT_PATTERN_TYPES)
            self.pattern_checks[pattern] = check
            pattern_row.append(check)

        self.mode_buttons: Dict[str, QRadioButton] = {}
        mode_group = QButtonGroup(self)
        mode_column = QVBoxLayout()
        mode_column.setContentsMargins(15, 0, 0, 0)
        for mode_value, mode_label in DETECTION_MODES:
            button = QRadioButton(mode_label)
            button.setChecked(mode_value == DEFAULT_DETECTION_MODE)
            mode_group.addButton(button)
            self.mode_buttons[mode_value] = button
            mode_column.addWidget(button)
        mode_caption = widgets.caption_label(
            "'no_states' ignores the profiler's callpath state markers, which also reclassifies the\n"
            "affected dependencies from dynamic to static. Re-running detection in either mode\n"
            "replaces the existing suggestions."
        )

        self.jobs_selector = widgets.ThreadSelector()
        jobs_caption = widgets.caption_label("(auto = unlimited; custom counts can be typed)")

        self.visualize_check = QCheckBox("Show graph visualization")
        self.visualize_check.setToolTip(
            "The explorer opens the graphs in a window of its own; this window stays responsive while it runs."
        )
        visualize_caption = widgets.caption_label("(the graphs open in a window of their own)")

        return widgets.group_box(
            "Settings",
            widgets.vbox(
                widgets.hbox(*pattern_row, None),
                widgets.heading_label("Dependency Data:"),
                mode_column,
                mode_caption,
                widgets.hbox(widgets.heading_label("Threads:"), self.jobs_selector, jobs_caption, None),
                widgets.hbox(self.visualize_check, visualize_caption, None),
            ),
        )

    # ── state ───────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        """Bring the enabled states, the hints and the tab up to date with what is on disk."""
        dot_dp = self.arguments.dot_dp
        ready = explorer_state.explorer_prerequisites_met(dot_dp)

        self.hotspot_hint.setVisible(not hotspot_data.hotspots_available_for_explorer(dot_dp))
        self.run_button.setEnabled(ready and not self.explorer_running)

        browse_ready = count_patches(dot_dp) > 0
        self.browse_button.setEnabled(browse_ready)
        self.vscode_button.setEnabled(browse_ready)

        none_found = explorer_state.pattern_detection_executed(dot_dp) and not explorer_state.patterns_found(dot_dp)
        self.no_suggestions_label.setVisible(none_found and not self.explorer_running)

        self.tabs.set_tab_enabled(
            TAB_PATTERN_DETECTION,
            ready,
            "" if ready else explorer_state.pattern_detection_tooltip_text(dot_dp),
        )

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
                "Profiling data not found.\nPlease execute a configuration in 'dp' mode with 'inplace' enabled first.",
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
        self.run_button.setEnabled(False)
        self.run_button.setText(_RUNNING_TEXT)
        self.stop_button.setEnabled(True)
        self.no_suggestions_label.hide()
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
        self.run_button.setText(_RUN_TEXT)
        self.stop_button.setEnabled(False)
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
        self.stop_button.setEnabled(False)
        self.status.set("Stopping pattern detection...", widgets.STATUS_STOP)

    def cancel_jobs(self) -> None:
        job = self._explorer_job
        if job is not None:
            job.cancel()

    # ── the suggestions ─────────────────────────────────────────────────────

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

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Profiling stage: build the selected configuration with the DiscoPoP profiler and run it once, in place, so that
the profiling data for the pattern detection lands in ``.discopop/profiler``.

The work is :func:`services.execution_run.run_preparation` (formerly the "Profile for Pattern Detection" button of the
Execute stage).
"""

import datetime
import logging
import os
from typing import Callable, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QSpinBox, QVBoxLayout, QWidget

from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.qt_gui.panel import Panel, TabHost
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.tabs import TAB_SETUP
from discopop_library.ProjectManager.services.execution_run import PreparationRequest, run_preparation
from discopop_library.ProjectManager.services.explorer_state import (
    explorer_prerequisites_met,
    missing_explorer_files,
    required_explorer_files,
)
from discopop_library.ProjectManager.services.jobs import (
    StatusKind,
    WorkEvent,
    WorkFinished,
    WorkOutput,
    WorkRunner,
    WorkStatus,
)
from discopop_library.ProjectManager.services.modes import available_modes
from discopop_library.ProjectManager.services.project_state import (
    ConfigChanged,
    ConfigurationsChanged,
    ProjectState,
    ResultsChanged,
)

PROFILE_TEXT = "Profile for Pattern Detection"
_MAX_SECONDS = 10_000_000
_STATUS_RESET_MS = 3000
_SETTINGS_MAX_WIDTH = 760

_STATUS_COLORS = {
    StatusKind.BUSY: widgets.STATUS_BUSY,
    StatusKind.IDLE: widgets.STATUS_IDLE,
    StatusKind.OK: widgets.STATUS_OK,
    StatusKind.FAIL: widgets.STATUS_FAIL,
    StatusKind.STOP: widgets.STATUS_STOP,
}

WHAT_HAPPENS = (
    "Compiles the selected configuration with the DiscoPoP compiler wrappers (the settings of dp_settings.json) and "
    "runs its execute.sh once. The instrumented program records the data dependences that occur while it runs; "
    "the pattern detection works on them."
)
IN_PLACE_NOTE = (
    "The build and the run happen in the project directory itself (in place), so that the profiling data is kept "
    "in .discopop/profiler. A new profiling run replaces the data of the previous one."
)
INPUT_NOTE = (
    "The instrumented program runs much slower than the original one: give the configuration a small, but "
    "representative input. Only code that runs is profiled."
)


class ProfilingPanel(Panel):
    """The Profiling stage.

    ``run_state_changed`` is told True when a profiling run starts and False when it ended (the main window keeps
    the Execute stage from starting a run meanwhile, and the Report holds its report back). :meth:`set_blocked`
    is the other direction: no profiling run while the Execute stage runs.
    """

    output_title = "Profiling"

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        tabs: TabHost,
        parent: Optional[QWidget] = None,
        *,
        run_state_changed: Optional[Callable[[bool], None]] = None,
    ) -> None:
        super().__init__(arguments, project_state, status, parent)
        self.tabs = tabs
        self._run_state_changed = run_state_changed
        self._job: Optional[WorkRunner] = None
        self._blocked = False
        self._run_failed = False
        self._hint_shown = False

        # ── what happens ────────────────────────────────────────────────────
        about = widgets.FormSection("What happens")
        about.add_widget(self._wrapped(WHAT_HAPPENS))
        about.add_widget(self._wrapped(IN_PLACE_NOTE))
        about.add_widget(self._wrapped(INPUT_NOTE))

        # ── the data of the last run ────────────────────────────────────────
        self.data_label = QLabel("")
        self.data_label.setWordWrap(True)
        self.data_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.configuration_label = QLabel("")
        self.configuration_label.setWordWrap(True)
        self.goto_setup_button = widgets.create_button("Go to Project Setup", lambda: self.tabs.show_tab(TAB_SETUP))
        self.goto_setup_button.setVisible(False)
        data = widgets.FormSection("Profiling data")
        data.add_row("Configuration:", self.configuration_label, stretch_field=True)
        data.add_row("Last run:", self.data_label, stretch_field=True)
        data.add_widget(widgets.hbox(self.goto_setup_button, None, margins=0))

        # ── limits ──────────────────────────────────────────────────────────
        self.timeout_compilation_spin = self._timeout_spin()
        self.timeout_execution_spin = self._timeout_spin()
        self.timeout_validation_spin = self._timeout_spin()
        limits = widgets.FormSection()
        limits.add_row("Compilation timeout (s):", self.timeout_compilation_spin, "0 = disabled")
        limits.add_row(
            "Execution timeout (s):",
            self.timeout_execution_spin,
            "0 = disabled; the instrumented program is much slower than the original one",
        )
        limits.add_row("Validation timeout (s):", self.timeout_validation_spin, "0 = disabled; validate.sh only")
        self.limits_section = widgets.CollapsibleSection("Advanced", limits, summary="timeouts")

        # ── header ──────────────────────────────────────────────────────────
        self.run_button = widgets.RunStopButton(PROFILE_TEXT, self._profile, self._stop)
        self.run_button.setToolTip("Runs the selected configuration in 'dp' mode with 'inplace' enabled.")
        self.run_button.setEnabled(False)
        self.header = widgets.PanelHeader(
            "Profiling",
            "Record the data dependences of the selected configuration for the pattern detection.",
            [self.run_button],
        )

        column = QWidget()
        column.setMaximumWidth(_SETTINGS_MAX_WIDTH)
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(12)
        for section in (data, about, self.limits_section):
            column_layout.addWidget(section)
        column_layout.addStretch(1)
        options = QWidget()
        options_layout = QHBoxLayout(options)
        options_layout.setContentsMargins(0, 0, 8, 0)
        options_layout.addWidget(column, 100, Qt.AlignmentFlag.AlignTop)
        options_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(options)

        self.console = self.make_console()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        layout.addWidget(scroll, 1)

        project_state.subscribe(ConfigChanged, lambda _event: self.refresh())
        project_state.subscribe(ConfigurationsChanged, lambda _event: self.refresh())
        project_state.subscribe(ResultsChanged, lambda _event: self.refresh())
        self.refresh()

    @staticmethod
    def _wrapped(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        return label

    @staticmethod
    def _timeout_spin() -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, _MAX_SECONDS)
        spin.setValue(3600)
        return spin

    def output_console(self) -> widgets.OutputConsole:
        return self.console

    def is_running(self) -> bool:
        return self._job is not None

    # ── what the stage shows ─────────────────────────────────────────────────

    def _missing_requirement(self) -> Tuple[str, bool]:
        """Why the selected configuration cannot be profiled ("" if it can); whether Project Setup fixes it."""
        config = self.project_state.current_config
        if not config:
            return "No configuration selected.", False
        compile_sh = resolve_compile_script_path(self.arguments.project_config_dir, config)
        execute_sh = os.path.join(self.arguments.project_config_dir, config, "execute.sh")
        if not os.path.exists(compile_sh):
            return "No compile.sh: write it in Project Setup.", True
        if not os.path.exists(execute_sh):
            return "The configuration has no execute.sh: write it in Configuration Setup.", False
        if not available_modes(self.arguments.project_config_dir, compile_sh, execute_sh)["dp"]:
            return "No dp_settings.json: derive the settings from seq_settings.json in Project Setup.", True
        return "", False

    def _data_text(self) -> str:
        dot_dp = self.arguments.dot_dp
        if not explorer_prerequisites_met(dot_dp):
            return "No profiling data yet."
        # the newest profiling file: a new run rewrites them, which leaves the directory's time unchanged
        times = [os.path.getmtime(path) for path in required_explorer_files(dot_dp) if os.path.exists(path)]
        try:
            times.append(os.path.getmtime(os.path.join(dot_dp, "profiler")))
        except OSError:
            pass
        text = datetime.datetime.fromtimestamp(max(times)).strftime("%Y-%m-%d %H:%M") if times else "unknown"
        missing = missing_explorer_files(dot_dp)
        if missing:
            text += " — incomplete, missing: " + ", ".join(os.path.basename(path) for path in missing)
        return text

    def refresh(self) -> None:
        """The configuration, the data of the last run and whether a run can start."""
        self.configuration_label.setText(self.project_state.current_config or "—")
        self.data_label.setText(self._data_text())
        missing, setup_fixes_it = self._missing_requirement()
        self.goto_setup_button.setVisible(setup_fixes_it)
        if not self.is_running():
            self.run_button.setEnabled(not missing and not self._blocked)
            # the chip says why the button is off; once it is on again, the outcome of the last run is not restored
            if missing:
                self.header.chip.set_status(widgets.CHIP_WARN, "Cannot profile", missing)
            elif self._blocked:
                self.header.chip.set_status(widgets.CHIP_IDLE, "Execute is running")
            elif self._hint_shown:
                self.header.chip.set_status(widgets.CHIP_IDLE, "")
            self._hint_shown = bool(missing) or self._blocked

    def set_blocked(self, blocked: bool) -> None:
        """Another stage runs the configuration (Execute): no profiling run meanwhile."""
        self._blocked = blocked
        self.refresh()

    # ── running ──────────────────────────────────────────────────────────────

    def _profile(self) -> None:
        configuration = self.project_state.current_config
        if not configuration:
            dialogs.show_warning(self, "No Configuration Selected", "Please select a configuration first.")
            return
        request = PreparationRequest(
            configuration=configuration,
            mode="dp",
            settings_filename="dp_settings.json",
            status_noun="pattern detection",
            timeout_execution=self.timeout_execution_spin.value(),
            timeout_compilation=self.timeout_compilation_spin.value(),
            timeout_validation=self.timeout_validation_spin.value(),
        )
        self._run_failed = False
        self.run_button.setEnabled(False)  # remembered: "can a run be started" once this one ended
        self.run_button.set_running(True)
        self.header.chip.set_status(widgets.CHIP_BUSY, "Profiling")
        self.status.set("⏳ Preparing pattern detection...", widgets.STATUS_BUSY)
        self.console.clear()
        self.output_requested.emit()
        if self._run_state_changed is not None:
            self._run_state_changed(True)
        restore_logging = widgets.redirect_logging_to_console(self.console, "INFO")
        arguments = self.arguments
        logger = logging.getLogger("Prepare Pattern Detection")

        def handle(event: WorkEvent) -> None:
            if isinstance(event, WorkOutput):
                self.console.append_text(event.text)
            elif isinstance(event, WorkStatus):
                self._run_failed = self._run_failed or event.kind == StatusKind.FAIL
                if not self._stop_requested():
                    self.status.set(event.text, _STATUS_COLORS[event.kind])
            elif isinstance(event, WorkFinished):
                job = self._job
                restore_logging()
                if event.error is not None:  # a crash of the work must not leave the button disabled
                    logger.error("preparation failed: %s", event.error)
                    self.console.append_text(f"\nError: {event.error}\n")
                success = event.error is None and bool(event.result)
                stopped = job is not None and job.cancel_requested
                self._run_failed = self._run_failed or not (success or stopped)
                self._end_run(stopped)
                if success or stopped:
                    self.status.set("Ready", widgets.STATUS_IDLE)
                else:
                    self.status.set(
                        "Pattern detection preparation failed", widgets.STATUS_FAIL, reset_ms=_STATUS_RESET_MS
                    )
                self.project_state.publish(ResultsChanged())

        self._job = start_work(self, lambda ctx: run_preparation(arguments, request, ctx), handle)

    def _end_run(self, stopped: bool) -> None:
        self._job = None
        self.run_button.set_running(False)
        if stopped:
            self.header.chip.set_status(widgets.CHIP_WARN, "Stopped")
        elif self._run_failed:
            self.header.chip.set_status(widgets.CHIP_ERROR, "Failed", "The output is in the output pane below.")
        else:
            self.header.chip.set_status(widgets.CHIP_OK, "Profiled")
        self.refresh()
        if self._run_state_changed is not None:
            self._run_state_changed(False)

    def _stop_requested(self) -> bool:
        return self._job is not None and self._job.cancel_requested

    def _stop(self) -> None:
        job = self._job
        if job is not None:
            job.cancel()
        self.run_button.set_stopping()
        self.status.set("Stopping profiling...", widgets.STATUS_STOP)

    def cancel_jobs(self) -> None:
        job = self._job
        if job is not None:
            job.cancel()

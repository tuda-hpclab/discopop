# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Build stage: compile the selected configuration in a mode (seq, dp, hd) into a kept build, without running it.

The stages after it (Profiling, Hotspots, Execute) run what is built here; they compile only if there is no current
build. The work is :func:`services.execution_run.run_preparation` with ``build_only``.
"""

import logging
import os
from typing import Callable, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QSpinBox, QVBoxLayout, QWidget

from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.build_controls import BuildsAndRuns
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.qt_gui.panel import Panel, TabHost
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.tabs import TAB_SETUP
from discopop_library.ProjectManager.services import build_overview
from discopop_library.ProjectManager.services.execution_run import PreparationRequest, run_preparation
from discopop_library.ProjectManager.services.jobs import (
    StatusKind,
    WorkEvent,
    WorkFinished,
    WorkOutput,
    WorkRunner,
    WorkStatus,
)
from discopop_library.ProjectManager.services.modes import available_modes, settings_file_name
from discopop_library.ProjectManager.services.project_state import (
    ConfigChanged,
    ConfigurationsChanged,
    ProjectDirectoriesChanged,
    ProjectState,
    ResultsChanged,
)

BUILD_TEXT = "Build"
REBUILD_TEXT = "Rebuild"
_MAX_SECONDS = 10_000_000
_STATUS_RESET_MS = 3000

# the modes that are built here; par needs suggestions and is built by the stages that apply them
MODE_TEXTS = (
    ("seq", "seq: the original program"),
    ("dp", "dp: instrumented for profiling (Profiling)"),
    ("hd", "hd: instrumented for hotspot detection (Hotspots)"),
)

_STATUS_COLORS = {
    StatusKind.BUSY: widgets.STATUS_BUSY,
    StatusKind.IDLE: widgets.STATUS_IDLE,
    StatusKind.OK: widgets.STATUS_OK,
    StatusKind.FAIL: widgets.STATUS_FAIL,
    StatusKind.STOP: widgets.STATUS_STOP,
}

WHAT_HAPPENS = (
    "Compiles the selected configuration with compile.sh in the selected mode into a build: a copy of the project "
    "that is kept. Nothing is run. Profiling, Hotspots and Execute run in the build and compile only if there is "
    "no current one, so a long compilation is not repeated. A build is current as long as the project files, "
    "the compile script, the settings and the project directories are unchanged. Builds are only deleted by you."
)


class BuildPanel(Panel):
    """The Build stage.

    ``run_state_changed`` is told True when a build starts and False when it ended (the stages that run the
    configuration wait meanwhile). :meth:`set_blocked` is the other direction.
    """

    output_title = "Build"

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
        # whether the chip shows "Cannot build" / "Another stage is running", which refresh() has to take back
        self._chip_shows_obstacle = False
        self._failed = False
        self._rebuild = False

        about = widgets.FormSection("What happens")
        about_label = QLabel(WHAT_HAPPENS)
        about_label.setWordWrap(True)
        about.add_widget(about_label)

        self.mode_combo = QComboBox()
        for mode, text in MODE_TEXTS:
            self.mode_combo.addItem(text, mode)
        self.mode_combo.setCurrentIndex(1)
        self.configuration_label = QLabel("")
        self.build_label = QLabel("")
        self.goto_setup_button = widgets.create_button("Go to Project Setup", lambda: self.tabs.show_tab(TAB_SETUP))
        self.goto_setup_button.setVisible(False)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(0, _MAX_SECONDS)
        self.timeout_spin.setValue(3600)
        target = widgets.FormSection("Build")
        target.add_row("Configuration:", self.configuration_label, stretch_field=True)
        target.add_row("Mode:", self.mode_combo, "the settings file of the mode decides the compiler and its flags")
        target.add_row("Latest build:", self.build_label, stretch_field=True)
        target.add_row("Compilation timeout (s):", self.timeout_spin, "0 = disabled")
        target.add_widget(widgets.hbox(self.goto_setup_button, None, margins=0))

        self.builds = BuildsAndRuns(arguments, changed=lambda: project_state.publish(ResultsChanged()), show_runs=False)

        self.run_button = widgets.RunStopButton(BUILD_TEXT, self._build, self._stop)
        self.run_button.setToolTip("Compiles the configuration unless there already is a current build of the mode.")
        self.run_button.setEnabled(False)
        self.rebuild_button = widgets.create_button(
            REBUILD_TEXT,
            self._rebuild_now,
            tooltip="Compiles again, even if the build is current.",
        )
        self.rebuild_button.setEnabled(False)
        self.header = widgets.PanelHeader(
            "Build",
            "Compile the selected configuration into a kept build; the following stages run it.",
            [self.rebuild_button, self.run_button],
        )

        column = QWidget()
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(widgets.CARD_SPACING)
        for section in (target, about, self.builds):
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

        self.mode_combo.currentIndexChanged.connect(lambda _index: self.refresh())
        project_state.subscribe(ConfigChanged, lambda _event: self.refresh())
        project_state.subscribe(ConfigurationsChanged, lambda _event: self.refresh())
        project_state.subscribe(ResultsChanged, lambda _event: self.refresh())
        project_state.subscribe(ProjectDirectoriesChanged, lambda _event: self.refresh())
        self.refresh()

    def output_console(self) -> widgets.OutputConsole:
        return self.console

    def is_running(self) -> bool:
        return self._job is not None

    def mode(self) -> str:
        return str(self.mode_combo.currentData())

    # ── what the stage shows ─────────────────────────────────────────────────

    def _missing_requirement(self) -> str:
        """Why the selected configuration cannot be built in the mode ("" if it can)."""
        config = self.project_state.current_config
        if not config:
            return "No configuration selected."
        compile_sh = resolve_compile_script_path(self.arguments.project_config_dir, config)
        execute_sh = os.path.join(self.arguments.project_config_dir, config, "execute.sh")
        modes: Dict[str, bool] = available_modes(self.arguments.project_config_dir, compile_sh, execute_sh)
        if not modes[self.mode()]:
            return "Missing compile.sh, execute.sh or the settings file of the mode (%s)." % settings_file_name(
                self.mode()
            )
        return ""

    def refresh(self) -> None:
        config = self.project_state.current_config
        self.configuration_label.setText(config or "—")
        self.build_label.setText(build_overview.last_build_text(self.arguments, config, self.mode()))
        self.builds.refresh()
        missing = self._missing_requirement()
        self.goto_setup_button.setVisible(bool(missing) and bool(config))
        if not self.is_running():
            can_start = not missing and not self._blocked
            self.run_button.setEnabled(can_start)
            self.rebuild_button.setEnabled(can_start)
            if missing:
                self.header.chip.set_status(widgets.CHIP_WARN, "Cannot build", missing)
                self._chip_shows_obstacle = True
            elif self._blocked:
                self.header.chip.set_status(widgets.CHIP_IDLE, "Another stage is running")
                self._chip_shows_obstacle = True
            elif self._chip_shows_obstacle:
                self.header.chip.set_status(widgets.CHIP_IDLE, "Ready to build")
                self._chip_shows_obstacle = False

    def set_blocked(self, blocked: bool) -> None:
        """A stage that runs the configuration is busy: no build meanwhile."""
        self._blocked = blocked
        if not self.is_running():
            self.builds.set_blocked(blocked)
        self.refresh()

    # ── building ─────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._start(rebuild=False)

    def _rebuild_now(self) -> None:
        self._start(rebuild=True)

    def _start(self, rebuild: bool) -> None:
        configuration = self.project_state.current_config
        if not configuration:
            dialogs.show_warning(self, "No Configuration Selected", "Please select a configuration first.")
            return
        mode = self.mode()
        settings = settings_file_name(mode)
        assert settings is not None
        request = PreparationRequest(
            configuration=configuration,
            mode=mode,
            settings_filename=settings,
            status_noun="build",
            timeout_execution=0,
            timeout_compilation=self.timeout_spin.value(),
            timeout_validation=0,
            build_policy="rebuild" if rebuild else "auto",
            build_only=True,
        )
        self._failed = False
        self._rebuild = rebuild
        self.run_button.setEnabled(False)
        self.rebuild_button.setEnabled(False)
        self.run_button.set_running(True)
        self.builds.set_blocked(True)
        self.header.chip.set_status(widgets.CHIP_BUSY, "Building")
        self.status.set("⏳ Building...", widgets.STATUS_BUSY)
        self.console.clear()
        self.output_requested.emit()
        if self._run_state_changed is not None:
            self._run_state_changed(True)
        restore_logging = widgets.redirect_logging_to_console(self.console, "INFO")
        arguments = self.arguments
        logger = logging.getLogger("Build")

        def handle(event: WorkEvent) -> None:
            if isinstance(event, WorkOutput):
                self.console.append_text(event.text)
            elif isinstance(event, WorkStatus):
                self._failed = self._failed or event.kind == StatusKind.FAIL
                if not self._stop_requested():
                    self.status.set(event.text, _STATUS_COLORS[event.kind])
            elif isinstance(event, WorkFinished):
                job = self._job
                restore_logging()
                if event.error is not None:
                    logger.error("build failed: %s", event.error)
                    self.console.append_text(f"\nError: {event.error}\n")
                success = event.error is None and bool(event.result)
                stopped = job is not None and job.cancel_requested
                self._failed = self._failed or not (success or stopped)
                self._end(stopped)
                if success or stopped:
                    self.status.set("Ready", widgets.STATUS_IDLE)
                else:
                    self.status.set("Build failed", widgets.STATUS_FAIL, reset_ms=_STATUS_RESET_MS)
                self.project_state.publish(ResultsChanged())

        self._job = start_work(self, lambda ctx: run_preparation(arguments, request, ctx), handle)

    def _end(self, stopped: bool) -> None:
        self._job = None
        self.run_button.set_running(False)
        self.builds.set_blocked(self._blocked)
        if stopped:
            self.header.chip.set_status(widgets.CHIP_WARN, "Stopped")
        elif self._failed:
            self.header.chip.set_status(widgets.CHIP_ERROR, "Failed", "The output is in the output pane below.")
        else:
            self.header.chip.set_status(widgets.CHIP_OK, "Built")
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
        self.status.set("Stopping build...", widgets.STATUS_STOP)

    def cancel_jobs(self) -> None:
        job = self._job
        if job is not None:
            job.cancel()

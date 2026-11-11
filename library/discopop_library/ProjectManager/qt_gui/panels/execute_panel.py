# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The Execute tab: the execution modes and settings, the suggestions to apply, and the output of a run.

Ported from ``gui/mixins/execute_panel.py``, ``gui/mixins/execution.py`` and ``_update_execute_modes`` of
``gui/mixins/config_list.py``. The work of a run is :func:`services.execution_run.run_execution`; this panel reads its
widgets into a request, starts the work and shows the events.
"""

import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.configurations.execution_time import read_execution_time_settings
from discopop_library.ProjectManager.configurations.repetitions import (
    DEFAULT_MEASURED_REPETITIONS,
    validate_repetitions,
)
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.qt_gui import dialogs, widgets
from discopop_library.ProjectManager.qt_gui.job_adapter import start_work
from discopop_library.ProjectManager.qt_gui.panel import Panel, TabHost
from discopop_library.ProjectManager.qt_gui.status import StatusLine
from discopop_library.ProjectManager.qt_gui.suggestion_browser import open_suggestion_browser
from discopop_library.ProjectManager.qt_gui.suggestion_selector import SuggestionSelector
from discopop_library.ProjectManager.services.autotuner_results import (
    autotuner_results_exist,
    read_autotuner_applied_suggestions,
)
from discopop_library.ProjectManager.services.execution_run import (
    SUGGESTIONS_AUTOTUNER,
    SUGGESTIONS_MANUAL,
    SUGGESTIONS_NONE,
    ExecutionRequest,
    PreparationRequest,
    execution_time_summary,
    run_execution,
    run_preparation,
    suggestion_ids_to_apply,
)
from discopop_library.ProjectManager.services.jobs import (
    StatusKind,
    WorkEvent,
    WorkFinished,
    WorkOutput,
    WorkRunner,
    WorkStatus,
)
from discopop_library.ProjectManager.services.modes import EXECUTION_MODES, available_modes
from discopop_library.ProjectManager.services.patches import sort_suggestion_ids
from discopop_library.ProjectManager.services.project_state import (
    AutotuningChanged,
    AutotuningFinished,
    ConfigChanged,
    ConfigurationsChanged,
    PatternsChanged,
    ProjectState,
    ResultsChanged,
)

MODE_TEXTS = {
    "seq": "Sequential (seq)",
    "dp": "DiscoPoP Instrumented (dp)",
    "hd": "Hotspot Detection (hd)",
    "par": "Parallel (par)",
}

_STATUS_COLORS = {
    StatusKind.BUSY: widgets.STATUS_BUSY,
    StatusKind.IDLE: widgets.STATUS_IDLE,
    StatusKind.OK: widgets.STATUS_OK,
    StatusKind.FAIL: widgets.STATUS_FAIL,
    StatusKind.STOP: widgets.STATUS_STOP,
}

RUN_TEXT = "Run"
PREPARE_TEXT = "Profile for Pattern Detection"
_MAX_THREADS = 4096
_MAX_SECONDS = 10_000_000
_MAX_REPETITIONS = 1000
_STATUS_RESET_MS = 3000
_SETTINGS_MAX_WIDTH = 760


class ExecutePanel(Panel):
    """The Execute tab.

    ``tabs`` is offered for tab switches (the Execute tab does not need one at the moment). ``console`` shows the
    output of a run (shown in the output pane of the main window); the Report panel writes the progress of its PDF
    report into it. ``timeouts()`` returns the timeout settings for the Hotspot panel.
    """

    output_title = "Execute"

    def __init__(
        self,
        arguments: ProjectManagerArguments,
        project_state: ProjectState,
        status: StatusLine,
        tabs: Optional[TabHost] = None,
        parent: Optional[QWidget] = None,
        *,
        run_state_changed: Optional[Callable[[bool], None]] = None,
    ) -> None:
        super().__init__(arguments, project_state, status, parent)
        self.tabs = tabs
        # told True when a run or preparation starts and False when it ended (the Report tab holds its report back)
        self._run_state_changed = run_state_changed
        self._job: Optional[WorkRunner] = None
        self._browser: Optional[QWidget] = None
        self._autotuner_prefix_auto_value = ""
        self._publishing = False
        self._run_failed = False

        cpu_count = os.cpu_count() or 4
        self._cpu_count = cpu_count

        # ── execution modes ──────────────────────────────────────────────────
        self.mode_checks: Dict[str, QCheckBox] = {}
        for mode in EXECUTION_MODES:
            check = QCheckBox(MODE_TEXTS[mode])
            check.setChecked(mode == "seq")
            check.setEnabled(False)
            self.mode_checks[mode] = check
        modes_grid = QGridLayout()
        modes_grid.setContentsMargins(0, 0, 0, 0)
        for index, check in enumerate(self.mode_checks.values()):
            modes_grid.addWidget(check, index // 2, index % 2)
        modes_grid.setColumnStretch(2, 1)
        modes_section = widgets.FormSection("Modes")
        modes_section.add_widget(modes_grid)

        # ── execution settings ───────────────────────────────────────────────
        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(1, _MAX_THREADS)
        self.thread_spin.setValue(max(1, cpu_count // 2))
        # Beside the thread count rather than among the timeouts: this is part of what the run measures, not a limit
        # imposed on it. Only the seq and par runs are repeated.
        self.repetitions_spin = QSpinBox()
        self.repetitions_spin.setRange(1, _MAX_REPETITIONS)
        self.repetitions_spin.setValue(DEFAULT_MEASURED_REPETITIONS)
        # The setting itself lives in Editor -> execute.sh; it is mirrored here read-only, because the run is started
        # from this tab and this tab must say which of the two times it produces.
        self.execution_time_summary_label = QLabel("")
        self.execution_time_summary_label.setWordWrap(True)
        self.label_prefix_edit = QLineEdit()
        run_section = widgets.FormSection("Run")
        run_section.add_row("Threads:", self.thread_spin, f"This machine has {cpu_count} CPUs.")
        run_section.add_row(
            "Repetitions:",
            self.repetitions_spin,
            "The median of N runs is reported; 1 = measure once. Only seq and par runs are repeated.",
        )
        run_section.add_row("Execution time:", self.execution_time_summary_label)
        run_section.add_row("Label prefix:", self.label_prefix_edit, stretch_field=True)

        # ── timeouts, logging and behavior (advanced) ────────────────────────
        self.timeout_execution_spin = self._timeout_spin()
        self.timeout_compilation_spin = self._timeout_spin()
        self.timeout_validation_spin = self._timeout_spin()
        self.log_level_combo = widgets.log_level_selector("WARNING")
        self.inplace_check = QCheckBox("Execute in-place (skip project copy)")
        self.inplace_check.setToolTip(
            "In-place: execution modifies your project directory directly\n"
            "Non-in-place: execution happens in a copy, keeping your project clean"
        )
        self.skip_cleanup_check = QCheckBox("Skip cleanup (keep project copies)")
        self.skip_cleanup_check.setToolTip(
            "Warning: Enabling this may result in significant disk space usage\n"
            "as project copies are retained after execution."
        )
        advanced = widgets.FormSection()
        advanced.add_row("Execution timeout (s):", self.timeout_execution_spin, "0 = disabled")
        advanced.add_row("Compilation timeout (s):", self.timeout_compilation_spin, "0 = disabled")
        advanced.add_row("Validation timeout (s):", self.timeout_validation_spin, "0 = disabled; validate.sh only")
        advanced.add_row("Log level:", self.log_level_combo)
        advanced.add_widget(self.inplace_check)
        advanced.add_widget(self.skip_cleanup_check)
        self.advanced_section = widgets.CollapsibleSection(
            "Advanced", advanced, summary="timeouts, log level, in-place, cleanup"
        )

        # ── apply suggestions ────────────────────────────────────────────────
        self.none_radio = QRadioButton("None (apply no suggestions)")
        self.apply_suggestions_rb = QRadioButton("Apply manually selected suggestions")
        self.apply_autotuner_suggestions_rb = QRadioButton("Apply autotuner-selected suggestions")
        self.suggestions_group = QButtonGroup(self)
        self._suggestion_radios = {
            SUGGESTIONS_NONE: self.none_radio,
            SUGGESTIONS_MANUAL: self.apply_suggestions_rb,
            SUGGESTIONS_AUTOTUNER: self.apply_autotuner_suggestions_rb,
        }
        for radio in self._suggestion_radios.values():
            self.suggestions_group.addButton(radio)
        self.none_radio.setChecked(True)
        self.apply_suggestions_rb.setEnabled(False)
        self.apply_autotuner_suggestions_rb.setEnabled(False)
        self.suggestions_count_label = widgets.caption_label("No suggestions available")
        self.suggestions_count_label.setWordWrap(False)
        self.browse_edit_suggestions_button = widgets.create_button("Browse / Edit →", self._open_suggestion_browser)
        self.browse_edit_suggestions_button.setEnabled(False)
        self.execute_suggestion_selector = SuggestionSelector(
            self.arguments.dot_dp, "execute", on_change=self._update_suggestion_count
        )
        self.autotuner_suggestions_info_label = widgets.caption_label("No autotuner results available")
        suggestions_section = widgets.FormSection("Apply suggestions")
        suggestions_section.add_widget(self.none_radio)
        suggestions_section.add_widget(self.apply_suggestions_rb)
        suggestions_section.add_widget(
            widgets.hbox(self.suggestions_count_label, None, self.browse_edit_suggestions_button, margins=0)
        )
        suggestions_section.add_widget(self.execute_suggestion_selector)
        suggestions_section.add_widget(self.apply_autotuner_suggestions_rb)
        suggestions_section.add_widget(self.autotuner_suggestions_info_label)
        self.suggestions_group.buttonToggled.connect(lambda _button, _checked: self._on_suggestions_mode_change())

        # ── actions in the header ────────────────────────────────────────────
        self.run_button = widgets.RunStopButton(RUN_TEXT, self._run_execution, self._stop_execution)
        self.run_button.setEnabled(False)
        self.prepare_pattern_detection_button = widgets.create_button(
            PREPARE_TEXT,
            self._prepare_pattern_detection,
            tooltip="Runs the selected configuration in 'dp' mode with 'inplace' enabled.",
        )
        self.prepare_pattern_detection_button.setEnabled(False)
        self.header = widgets.PanelHeader(
            "Execute",
            "Build and run the selected configuration in the chosen modes.",
            [self.prepare_pattern_detection_button, self.run_button],
        )

        # ── layout: the header, below it the settings column (scrollable, left-aligned) ─────────────
        column = QWidget()
        column.setMaximumWidth(_SETTINGS_MAX_WIDTH)
        column_layout = QVBoxLayout(column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(12)
        for section in (modes_section, run_section, suggestions_section, self.advanced_section):
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

        # the output is shown in the output pane of the main window
        self.console = self.make_console()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        layout.addWidget(scroll, 1)

        project_state.subscribe(ConfigChanged, lambda _event: self._on_config_changed())
        project_state.subscribe(ConfigurationsChanged, lambda _event: self._update_modes())
        project_state.subscribe(ResultsChanged, lambda _event: self._on_results_changed())
        project_state.subscribe(PatternsChanged, lambda _event: self._refresh_suggestion_selection_display())
        project_state.subscribe(AutotuningChanged, lambda _event: self._on_autotuning_changed())
        project_state.subscribe(AutotuningFinished, lambda _event: self._refresh_suggestion_selection_display())
        self._update_modes()
        self._refresh_suggestion_selection_display(publish=False)

    @staticmethod
    def _timeout_spin() -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(0, _MAX_SECONDS)
        spin.setValue(3600)
        return spin

    # ── what the other panels read ───────────────────────────────────────────

    def output_console(self) -> widgets.OutputConsole:
        return self.console

    def timeouts(self) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """The execution, compilation and validation timeouts in seconds; 0 is disabled.

        0 is passed on as 0, as the Tk GUI did: the script then still runs under ``timeout 0``, which forwards a
        Stop to the program (without the wrapper only the shell would be terminated).
        """

        def seconds(spin: QSpinBox) -> Optional[float]:
            return float(spin.value())

        return (
            seconds(self.timeout_execution_spin),
            seconds(self.timeout_compilation_spin),
            seconds(self.timeout_validation_spin),
        )

    def suggestions_mode(self) -> str:
        for mode, radio in self._suggestion_radios.items():
            if radio.isChecked():
                return mode
        return SUGGESTIONS_NONE

    def set_suggestions_mode(self, mode: str) -> None:
        self._suggestion_radios[mode].setChecked(True)

    def is_running(self) -> bool:
        return self._job is not None

    # ── reactions to the project state ───────────────────────────────────────

    def _on_config_changed(self) -> None:
        self._update_modes()
        self._refresh_suggestion_selection_display()

    def _on_autotuning_changed(self) -> None:
        if not self._publishing:
            self._refresh_suggestion_selection_display(publish=False)

    def _on_results_changed(self) -> None:
        self._update_modes()

    def _update_execution_time_summary(self) -> None:
        """Mirror the stored setting of the selected configuration (Editor -> execute.sh)."""
        config = self.project_state.current_config
        enabled = False
        if config:
            enabled = read_execution_time_settings(os.path.join(self.arguments.project_config_dir, config))[0]
        self.execution_time_summary_label.setText(execution_time_summary(self.arguments.execution_time_regex, enabled))

    def _update_modes(self) -> None:
        """Which modes and buttons the selected configuration offers."""
        self._update_execution_time_summary()
        config = self.project_state.current_config
        if not config:
            for mode, check in self.mode_checks.items():
                check.setEnabled(False)
                check.setChecked(mode == "seq")
            if not self.is_running():
                self.run_button.setEnabled(False)
                self.prepare_pattern_detection_button.setEnabled(False)
            self.console.clear()
            return
        config_path = os.path.join(self.arguments.project_config_dir, config)
        compile_sh = resolve_compile_script_path(self.arguments.project_config_dir, config)
        execute_sh = os.path.join(config_path, "execute.sh")
        for mode, exists in available_modes(self.arguments.project_config_dir, compile_sh, execute_sh).items():
            self.mode_checks[mode].setEnabled(exists)
            if not exists:
                self.mode_checks[mode].setChecked(False)
        # a run in progress keeps both buttons off until it is finished
        if not self.is_running():
            self.run_button.setEnabled(True)
            self.prepare_pattern_detection_button.setEnabled(True)

    # ── the suggestions ──────────────────────────────────────────────────────

    def _on_suggestions_mode_change(self) -> None:
        mode = self.suggestions_mode()
        if mode == SUGGESTIONS_AUTOTUNER:
            self._autotuner_prefix_auto_value = "auto"
            self.label_prefix_edit.setText("auto")
        else:
            if self.label_prefix_edit.text() == self._autotuner_prefix_auto_value:
                self.label_prefix_edit.setText("")
            self._autotuner_prefix_auto_value = ""
        self.execute_suggestion_selector.set_enabled(mode == SUGGESTIONS_MANUAL)
        # only manually selected suggestions use it: hidden otherwise rather than a large disabled table
        self.execute_suggestion_selector.setVisible(mode == SUGGESTIONS_MANUAL)

    def _update_suggestion_count(self) -> None:
        """The "N of M selected" label from the selector."""
        total = len(self.execute_suggestion_selector.get_available_ids())
        selected = len(self.execute_suggestion_selector.get_selected_ids())
        if total == 0:
            self.suggestions_count_label.setText("No suggestions available")
            widgets.set_label_color(self.suggestions_count_label, widgets.STATUS_IDLE)
        else:
            self.suggestions_count_label.setText(f"{selected} of {total} selected")
            if selected > 0:
                self.suggestions_count_label.setStyleSheet("")
            else:
                widgets.set_label_color(self.suggestions_count_label, widgets.STATUS_IDLE)

    def _refresh_suggestion_selection_display(self, publish: bool = True) -> None:
        """Re-scan the suggestions and the autotuner's selection; ``publish``: tell the Autotuning tab afterwards."""
        self.execute_suggestion_selector.refresh()
        total = len(self.execute_suggestion_selector.get_available_ids())
        self._update_suggestion_count()
        self.apply_suggestions_rb.setEnabled(total > 0)
        self.browse_edit_suggestions_button.setEnabled(total > 0)
        if total == 0 and self.suggestions_mode() == SUGGESTIONS_MANUAL:
            self.set_suggestions_mode(SUGGESTIONS_NONE)
        self.execute_suggestion_selector.set_enabled(total > 0 and self.suggestions_mode() == SUGGESTIONS_MANUAL)
        self.execute_suggestion_selector.setVisible(self.suggestions_mode() == SUGGESTIONS_MANUAL)

        config = self.project_state.current_config or ""
        executed = autotuner_results_exist(self.arguments.dot_dp)
        ids: List[str] = []
        if executed and config:
            ids = sort_suggestion_ids(read_autotuner_applied_suggestions(self.arguments.dot_dp, config))
        if ids:
            self.autotuner_suggestions_info_label.setText("Suggestion IDs: " + ", ".join(ids))
            self.autotuner_suggestions_info_label.setStyleSheet("")
        else:
            text = "No suggestions selected" if executed and config else "Autotuner not yet executed"
            self.autotuner_suggestions_info_label.setText(text)
            widgets.set_label_color(self.autotuner_suggestions_info_label, widgets.STATUS_IDLE)
        self.apply_autotuner_suggestions_rb.setEnabled(bool(executed and config))
        if not (executed and config) and self.suggestions_mode() == SUGGESTIONS_AUTOTUNER:
            self.set_suggestions_mode(SUGGESTIONS_NONE)
        if publish:
            # the Autotuning tab shows the same suggestions; its own change of them is not echoed back to this tab
            self._publishing = True
            try:
                self.project_state.publish(AutotuningChanged())
            finally:
                self._publishing = False

    def _open_suggestion_browser(self) -> None:
        self._browser = open_suggestion_browser(self, self.arguments.dot_dp)

    # ── running ──────────────────────────────────────────────────────────────

    def _validate_inputs(self) -> bool:
        """The spin boxes only hold valid numbers; what is left is the warning for more threads than CPUs."""
        if self.thread_spin.value() > self._cpu_count:
            self.status.set(
                f"Warning: Thread count ({self.thread_spin.value()}) exceeds CPU count ({self._cpu_count})",
                widgets.STATUS_STOP,
                reset_ms=_STATUS_RESET_MS,
            )
        problem = validate_repetitions(self.repetitions_spin.value())
        if problem is not None:
            self.status.set("Error: repetitions: " + problem, widgets.STATUS_FAIL, reset_ms=_STATUS_RESET_MS)
            return False
        return True

    def _selected_modes(self) -> List[str]:
        return [mode for mode, check in self.mode_checks.items() if check.isChecked()]

    def _append_output(self, text: str) -> None:
        self.console.append_text(text)

    def _run_execution(self) -> None:
        if not self._validate_inputs():
            return
        modes = self._selected_modes()
        if not modes:
            dialogs.show_warning(self, "No mode selected", "Please select at least one execution mode.")
            return
        configuration = self.project_state.current_config
        if not configuration:
            dialogs.show_warning(self, "No Configuration Selected", "Please select a configuration first.")
            return
        inplace = self.inplace_check.isChecked()
        suggestions_mode = self.suggestions_mode()
        if inplace and suggestions_mode != SUGGESTIONS_NONE:
            if not dialogs.ask_yes_no(
                self,
                "Dangerous Configuration",
                "Warning: You have selected inplace execution with suggestion application.\n\n"
                "This will directly modify your project directory and may overwrite existing files.\n\n"
                "Do you want to proceed?",
            ):
                return

        log_level = self.log_level_combo.currentText()
        request = ExecutionRequest(
            configuration=configuration,
            modes=tuple(modes),
            inplace=inplace,
            skip_cleanup=self.skip_cleanup_check.isChecked(),
            thread_count=self.thread_spin.value(),
            label_prefix=self.label_prefix_edit.text(),
            timeout_execution=self.timeout_execution_spin.value(),
            timeout_compilation=self.timeout_compilation_spin.value(),
            timeout_validation=self.timeout_validation_spin.value(),
            repetitions=self.repetitions_spin.value(),
            log_level=log_level,
            suggestion_ids=suggestion_ids_to_apply(
                suggestions_mode,
                self.execute_suggestion_selector.get_selected_ids(),
                self.arguments.dot_dp,
                configuration,
            ),
        )
        self._begin_run(self.run_button, "Running", "⏳ Execution in progress...")
        restore_logging = widgets.redirect_logging_to_console(self.console, log_level)
        logging.getLogger("Execute").info(f"Starting execution of configuration: {configuration}")
        arguments = self.arguments
        self._job = start_work(
            self,
            lambda ctx: run_execution(arguments, request, ctx),
            lambda event: self._on_execution_event(event, restore_logging),
        )

    def _begin_run(self, _button: QPushButton, chip_text: str, status_text: str) -> None:
        """Turn Run into Stop, disable the other button, clear the output and open the output pane."""
        self._run_failed = False
        self.run_button.setEnabled(False)  # remembered: "can a run be started" once this one ended
        self.run_button.set_running(True)
        self.prepare_pattern_detection_button.setEnabled(False)
        self.header.chip.set_status(widgets.CHIP_BUSY, chip_text)
        self.status.set(status_text, widgets.STATUS_BUSY)
        self.console.clear()
        self.output_requested.emit()
        if self._run_state_changed is not None:
            self._run_state_changed(True)

    def _end_run(self, stopped: bool = False) -> None:
        """Back to Run; the chip tells how the run ended (stopped / failed / finished)."""
        self._job = None
        self.run_button.set_running(False)
        if stopped:
            self.header.chip.set_status(widgets.CHIP_WARN, "Stopped")
        elif self._run_failed:
            self.header.chip.set_status(widgets.CHIP_ERROR, "Failed")
        else:
            self.header.chip.set_status(widgets.CHIP_OK, "Finished")
        self._update_modes()
        if self._run_state_changed is not None:
            self._run_state_changed(False)

    def _on_execution_event(self, event: WorkEvent, restore_logging: Callable[[], None]) -> None:
        """Handle one event of the execution work; runs on the main thread."""
        if isinstance(event, WorkOutput):
            self._append_output(event.text)
        elif isinstance(event, WorkStatus):
            self._run_failed = self._run_failed or event.kind == StatusKind.FAIL
            if not self._stop_requested():
                self.status.set(event.text, _STATUS_COLORS[event.kind])
        elif isinstance(event, WorkFinished):
            restore_logging()
            failures: List[Tuple[str, Any]] = []
            if event.error is not None:  # a crash of the work must not leave the buttons disabled
                logging.getLogger("Execute").error("execution failed: %s", event.error)
                self._append_output(f"\nError: {event.error}\n")
            else:
                failures = event.result
            self._finish_execution(failures, failed=event.error is not None)

    def _finish_execution(self, application_failures: List[Tuple[str, Any]], failed: bool = False) -> None:
        if application_failures:
            modes_str = ", ".join(mode for mode, _result in application_failures)
            details = "\n\n".join(mode + ": " + result.summary() for mode, result in application_failures)
            self._append_output(
                "\n⚠ "
                + str(len(application_failures))
                + " run(s) were SKIPPED because their suggestions could not be applied ("
                + modes_str
                + ").\n  They appear as '⚠ not applied' in the Report tab.\n"
            )
            dialogs.show_warning(
                self,
                "Suggestion Application Failed",
                "The selected parallelization suggestions could not be applied.\n\n"
                + details
                + "\n\nThe affected runs were skipped, because executing them would have "
                "measured the unmodified sequential code. They are recorded as "
                "'not applied' in the Report tab so they can be told apart from a "
                "parallel run without a speedup.",
            )
        self._append_output("\n=== Execution complete ===\n")
        stopped = self._stop_requested()
        self._run_failed = self._run_failed or failed or bool(application_failures)
        self._end_run(stopped=stopped)
        self.inplace_check.setChecked(False)
        if application_failures:
            self.status.set("⚠ Suggestion application failed", widgets.STATUS_FAIL)
        else:
            self.status.set("Ready", widgets.STATUS_IDLE)
        self.project_state.publish(ConfigurationsChanged())
        self.project_state.publish(ResultsChanged())

    def _prepare_pattern_detection(self) -> None:
        self._prepare_inplace_run(
            mode="dp",
            settings_filename="dp_settings.json",
            status_noun="pattern detection",
        )

    def _prepare_inplace_run(self, mode: str, settings_filename: str, status_noun: str) -> None:
        """Compile and execute the selected configuration in ``mode`` with inplace execution."""
        configuration = self.project_state.current_config
        if not configuration:
            dialogs.show_warning(self, "No Configuration Selected", "Please select a configuration first.")
            return
        request = PreparationRequest(
            configuration=configuration,
            mode=mode,
            settings_filename=settings_filename,
            status_noun=status_noun,
            timeout_execution=self.timeout_execution_spin.value(),
            timeout_compilation=self.timeout_compilation_spin.value(),
            timeout_validation=self.timeout_validation_spin.value(),
        )
        self._begin_run(self.prepare_pattern_detection_button, "Preparing", f"⏳ Preparing {status_noun}...")
        restore_logging = widgets.redirect_logging_to_console(self.console, "INFO")
        arguments = self.arguments
        failure_status = f"{status_noun.capitalize()} preparation failed"
        logger = logging.getLogger(f"Prepare {status_noun.title()}")

        def handle(event: WorkEvent) -> None:
            if isinstance(event, WorkOutput):
                self._append_output(event.text)
            elif isinstance(event, WorkStatus):
                self._run_failed = self._run_failed or event.kind == StatusKind.FAIL
                self.status.set(event.text, _STATUS_COLORS[event.kind])
            elif isinstance(event, WorkFinished):
                job = self._job
                restore_logging()
                if event.error is not None:  # a crash of the work must not leave the buttons disabled
                    logger.error("preparation failed: %s", event.error)
                    self._append_output(f"\nError: {event.error}\n")
                success = event.error is None and bool(event.result)
                stopped = job is not None and job.cancel_requested
                self._run_failed = self._run_failed or not (success or stopped)
                self._end_run(stopped=stopped)
                if success or stopped:
                    self.status.set("Ready", widgets.STATUS_IDLE)
                else:
                    self.status.set(failure_status, widgets.STATUS_FAIL, reset_ms=_STATUS_RESET_MS)
                self.project_state.publish(ResultsChanged())

        self._job = start_work(self, lambda ctx: run_preparation(arguments, request, ctx), handle)

    def _stop_requested(self) -> bool:
        """Whether Stop was pressed; a progress status the work sends afterwards would hide "Stopping ..."."""
        return self._job is not None and self._job.cancel_requested

    def _stop_execution(self) -> None:
        job = self._job
        if job is not None:
            job.cancel()
        self.run_button.set_stopping()
        self.status.set("Stopping execution...", widgets.STATUS_STOP)

    def cancel_jobs(self) -> None:
        job = self._job
        if job is not None:
            job.cancel()

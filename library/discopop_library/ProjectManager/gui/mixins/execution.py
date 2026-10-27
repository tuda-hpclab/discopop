# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
import os
import queue
import tkinter as tk
from typing import Any, Callable, Optional

from discopop_library.ProjectManager.configurations.repetitions import validate_repetitions
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.job_adapter import TkJobAdapter
from discopop_library.ProjectManager.gui.mixins.helpers import redirect_logging_to_text_area, show_warning
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui.rounded_button import RoundedButton
from discopop_library.ProjectManager.services.execution_run import (
    ExecutionRequest,
    PreparationRequest,
    run_execution,
    run_preparation,
    suggestion_ids_to_apply,
)
from discopop_library.ProjectManager.services.jobs import (
    StatusKind,
    WorkContext,
    WorkEvent,
    WorkFinished,
    WorkOutput,
    WorkRunner,
    WorkStatus,
)
from discopop_library.ProjectManager.services.project_state import ResultsChanged

_STATUS_COLORS = {
    StatusKind.BUSY: widgets.STATUS_BUSY,
    StatusKind.IDLE: widgets.STATUS_IDLE,
    StatusKind.OK: widgets.STATUS_OK,
    StatusKind.FAIL: widgets.STATUS_FAIL,
    StatusKind.STOP: widgets.STATUS_STOP,
}


class ExecutionMixin(ConfigManagerMixinBase):
    _execution_job: Optional[WorkRunner] = None
    stop_execution_button: Optional[RoundedButton] = None

    def _validate_execution_inputs(self) -> bool:
        cpu_count = os.cpu_count() or 4
        try:
            thread_count = self.thread_var.get()
            if thread_count < 1:
                self._set_status("Error: Thread count must be >= 1", fg=widgets.STATUS_FAIL, reset_delay=3000)
                return False
            if thread_count > cpu_count:
                self._set_status(
                    f"Warning: Thread count ({thread_count}) exceeds CPU count ({cpu_count})",
                    fg=widgets.STATUS_STOP,
                    reset_delay=3000,
                )
        except (ValueError, tk.TclError):
            self._set_status("Error: Thread count must be a valid integer", fg=widgets.STATUS_FAIL, reset_delay=3000)
            return False

        try:
            timeout_exec = self.timeout_execution_var.get()
            if timeout_exec < 0:
                self._set_status(
                    "Error: Execution timeout cannot be negative", fg=widgets.STATUS_FAIL, reset_delay=3000
                )
                return False
        except (ValueError, tk.TclError):
            self._set_status(
                "Error: Execution timeout must be a valid integer", fg=widgets.STATUS_FAIL, reset_delay=3000
            )
            return False

        try:
            timeout_comp = self.timeout_compilation_var.get()
            if timeout_comp < 0:
                self._set_status(
                    "Error: Compilation timeout cannot be negative", fg=widgets.STATUS_FAIL, reset_delay=3000
                )
                return False
        except (ValueError, tk.TclError):
            self._set_status(
                "Error: Compilation timeout must be a valid integer", fg=widgets.STATUS_FAIL, reset_delay=3000
            )
            return False

        try:
            timeout_val = self.timeout_validation_var.get()
            if timeout_val < 0:
                self._set_status(
                    "Error: Validation timeout cannot be negative", fg=widgets.STATUS_FAIL, reset_delay=3000
                )
                return False
        except (ValueError, tk.TclError):
            self._set_status(
                "Error: Validation timeout must be a valid integer", fg=widgets.STATUS_FAIL, reset_delay=3000
            )
            return False

        try:
            repetitions = self.execution_repetitions_var.get()
            problem = validate_repetitions(repetitions)
            if problem is not None:
                self._set_status("Error: repetitions: " + problem, fg=widgets.STATUS_FAIL, reset_delay=3000)
                return False
        except (ValueError, tk.TclError):
            # An empty or non-numeric entry; caught here because reading it again
            # in the worker thread would raise where nothing reports it and the
            # buttons have already been disabled.
            self._set_status("Error: Repetitions must be a valid integer", fg=widgets.STATUS_FAIL, reset_delay=3000)
            return False

        return True

    def _run_execution(self) -> None:
        if not self._validate_execution_inputs():
            return

        selected_modes = [mode for mode, var in self.mode_vars.items() if var.get()]
        if not selected_modes:
            show_warning(self, "No mode selected", "Please select at least one execution mode.")
            return

        inplace = self.inplace_var.get()
        suggestions_mode = self.suggestions_mode_var.get()
        if inplace and suggestions_mode != "none":
            from discopop_library.ProjectManager.gui.mixins.helpers import ask_yes_no

            if not ask_yes_no(
                self,
                "Dangerous Configuration",
                "Warning: You have selected inplace execution with suggestion application.\n\n"
                "This will directly modify your project directory and may overwrite existing files.\n\n"
                "Do you want to proceed?",
            ):
                return

        if self.stop_execution_button is not None:
            self.stop_execution_button.config(state="normal")

        self.run_button.config(state="disabled", text="⟳ Running...")
        self.prepare_pattern_detection_button.config(state="disabled")
        self.generate_report_button.config(state="disabled")
        self.view_report_button.config(state="disabled")

        self.status_label.config(text="⏳ Execution in progress...", foreground=widgets.STATUS_BUSY)

        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.config(state="disabled")

        def append_output(text: str) -> None:
            self.output_text.config(state=tk.NORMAL)
            self.output_text.insert(tk.END, text)
            self.output_text.see(tk.END)
            self.output_text.config(state="disabled")

        inplace = self.inplace_var.get()
        suggestions_mode = self.suggestions_mode_var.get()
        assert self.current_config is not None
        current_config = self.current_config
        log_level = self.log_level_var.get()
        manual_ids = (
            self.execute_suggestion_selector.get_selected_ids() if hasattr(self, "execute_suggestion_selector") else []
        )
        request = ExecutionRequest(
            configuration=current_config,
            modes=tuple(selected_modes),
            inplace=inplace,
            skip_cleanup=self.skip_cleanup_var.get(),
            thread_count=self.thread_var.get(),
            label_prefix=self.label_prefix_var.get(),
            timeout_execution=self.timeout_execution_var.get(),
            timeout_compilation=self.timeout_compilation_var.get(),
            timeout_validation=self.timeout_validation_var.get(),
            repetitions=self.execution_repetitions_var.get(),
            log_level=log_level,
            suggestion_ids=suggestion_ids_to_apply(suggestions_mode, manual_ids, self.arguments.dot_dp, current_config),
        )

        restore_logging = redirect_logging_to_text_area(self.output_text, log_level)

        logger = logging.getLogger("Execute")
        logger.info(f"Starting execution of configuration: {current_config}")

        def work(ctx: WorkContext) -> list[tuple[str, Any]]:
            return run_execution(self.arguments, request, ctx)

        events: "queue.Queue[WorkEvent]" = queue.Queue()
        job = WorkRunner(work, events)
        self._execution_job = job
        TkJobAdapter(
            self, events, lambda event: self._on_execution_event(event, append_output, restore_logging)
        ).start()
        job.start()

    def _on_execution_event(
        self, event: WorkEvent, append_output: Callable[[str], None], restore_logging: Callable[[], None]
    ) -> None:
        """Handle one event of the execution work; runs on the Tk main thread."""
        if isinstance(event, WorkOutput):
            append_output(event.text)
        elif isinstance(event, WorkStatus):
            self.status_label.config(text=event.text, foreground=_STATUS_COLORS[event.kind])
        elif isinstance(event, WorkFinished):
            self._execution_job = None
            restore_logging()
            application_failures: list[tuple[str, Any]] = []
            if event.error is not None:  # a crash of the work must not leave the buttons disabled
                logging.getLogger("Execute").error("execution failed: %s", event.error)
                append_output(f"\nError: {event.error}\n")
            else:
                application_failures = event.result
            self._finish_execution(application_failures, append_output)

    def _finish_execution(
        self, application_failures: list[tuple[str, Any]], append_output: Callable[[str], None]
    ) -> None:
        if application_failures:
            modes_str = ", ".join(mode for mode, _res in application_failures)
            details = "\n\n".join(mode + ": " + res.summary() for mode, res in application_failures)
            append_output(
                "\n⚠ "
                + str(len(application_failures))
                + " run(s) were SKIPPED because their suggestions could not be applied ("
                + modes_str
                + ").\n  They appear as '⚠ not applied' in the Report tab.\n"
            )
            show_warning(
                self,
                "Suggestion Application Failed",
                "The selected parallelization suggestions could not be applied.\n\n"
                + details
                + "\n\nThe affected runs were skipped, because executing them would have "
                "measured the unmodified sequential code. They are recorded as "
                "'not applied' in the Report tab so they can be told apart from a "
                "parallel run without a speedup.",
            )

        append_output("\n=== Execution complete ===\n")
        self.run_button.config(state=tk.NORMAL, text="Run")
        if self.stop_execution_button is not None:
            self.stop_execution_button.config(state="disabled")
        self.generate_report_button.config(state=tk.NORMAL)
        self.inplace_var.set(False)
        if application_failures:
            self.status_label.config(text="⚠ Suggestion application failed", foreground=widgets.STATUS_FAIL)
        else:
            self.status_label.config(text="Ready", foreground=widgets.STATUS_IDLE)
        self._refresh_config_list()
        self.project_state.publish(ResultsChanged())
        self._update_pattern_detection_ui()

    def _prepare_pattern_detection(self) -> None:
        self._prepare_inplace_run(
            mode="dp",
            settings_filename="dp_settings.json",
            button=self.prepare_pattern_detection_button,
            button_label="Prepare Pattern Detection",
            status_noun="pattern detection",
        )

    def _prepare_inplace_run(
        self,
        mode: str,
        settings_filename: str,
        button: RoundedButton,
        button_label: str,
        status_noun: str,
    ) -> None:
        """Compile and execute the selected configuration in ``mode`` with inplace execution."""
        if not self.current_config:
            show_warning(self, "No Configuration Selected", "Please select a configuration first.")
            return

        if self.stop_execution_button is not None:
            self.stop_execution_button.config(state="normal")

        button.config(state="disabled", text="⟳ Preparing...")
        self.run_button.config(state="disabled")
        self.generate_report_button.config(state="disabled")
        self.view_report_button.config(state="disabled")

        self.status_label.config(text=f"⏳ Preparing {status_noun}...", foreground=widgets.STATUS_BUSY)

        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.config(state="disabled")

        def append_output(text: str) -> None:
            self.output_text.config(state=tk.NORMAL)
            self.output_text.insert(tk.END, text)
            self.output_text.see(tk.END)
            self.output_text.config(state="disabled")

        current_config = self.current_config
        request = PreparationRequest(
            configuration=current_config,
            mode=mode,
            settings_filename=settings_filename,
            status_noun=status_noun,
            timeout_execution=self.timeout_execution_var.get(),
            timeout_compilation=self.timeout_compilation_var.get(),
            timeout_validation=self.timeout_validation_var.get(),
        )

        restore_logging = redirect_logging_to_text_area(self.output_text, "INFO")

        logger = logging.getLogger(f"Prepare {status_noun.title()}")
        failure_status = f"{status_noun.capitalize()} preparation failed"

        def work(ctx: WorkContext) -> bool:
            return run_preparation(self.arguments, request, ctx)

        events: "queue.Queue[WorkEvent]" = queue.Queue()
        job = WorkRunner(work, events)
        self._execution_job = job

        def on_event(event: WorkEvent) -> None:
            if isinstance(event, WorkOutput):
                append_output(event.text)
            elif isinstance(event, WorkStatus):
                self.status_label.config(text=event.text, foreground=_STATUS_COLORS[event.kind])
            elif isinstance(event, WorkFinished):
                self._execution_job = None
                restore_logging()
                if event.error is not None:  # a crash of the work must not leave the buttons disabled
                    logger.error("preparation failed: %s", event.error)
                    append_output(f"\nError: {event.error}\n")
                success = event.error is None and bool(event.result)
                button.config(state=tk.NORMAL, text=button_label)
                self._update_execute_modes()
                if self.stop_execution_button is not None:
                    self.stop_execution_button.config(state="disabled")
                self.run_button.config(state=tk.NORMAL)
                self.generate_report_button.config(state=tk.NORMAL)
                if success or job.cancel_requested:
                    self.status_label.config(text="Ready", foreground=widgets.STATUS_IDLE)
                else:
                    self._set_status(failure_status, fg=widgets.STATUS_FAIL, reset_delay=3000)
                self.project_state.publish(ResultsChanged())
                self._update_pattern_detection_ui()

        TkJobAdapter(self, events, on_event).start()
        job.start()

    def _stop_execution(self) -> None:
        job = self._execution_job
        if job is not None:
            job.cancel()
        if self.run_button is not None:
            self.run_button.config(state="normal", text="Run")
        if self.prepare_pattern_detection_button is not None:
            self.prepare_pattern_detection_button.config(state="normal", text="Prepare Pattern Detection")
        if self.stop_execution_button is not None:
            self.stop_execution_button.config(state="disabled")
        self.status_label.config(text="Stopping execution...", foreground=widgets.STATUS_STOP)

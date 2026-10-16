# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
import logging
import os
import queue
import tkinter as tk


from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.PatchApplicator.PatchApplicationResult import clear_application_result
from discopop_library.ProjectManager.configurations.copying import (
    copy_configuration,
    get_application_result,
    patch_applicator_dir_of,
)
from discopop_library.ProjectManager.configurations.deletion import delete_configuration
from discopop_library.ProjectManager.configurations.execution import execute_configuration, record_skipped_execution
from discopop_library.ProjectManager.configurations.repetitions import repetitions_for_mode, validate_repetitions
from discopop_library.ProjectManager.configurations.execution_time import (
    extract_execution_time,
    resolve_execution_time_regex,
)
from discopop_library.ProjectManager.configurations.validation import has_validate_script, run_validation_phase
from discopop_library.ProjectManager.gui.job_adapter import TkJobAdapter
from discopop_library.ProjectManager.services.jobs import (
    StatusKind,
    WorkContext,
    WorkEvent,
    WorkFinished,
    WorkOutput,
    WorkRunner,
    WorkStatus,
)
from discopop_library.ProjectManager.services.autotuner_results import read_autotuner_applied_suggestions
from discopop_library.ProjectManager.services.modes import settings_path as mode_settings_path
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui.mixins.helpers import redirect_logging_to_text_area, show_warning
from discopop_library.ProjectManager.gui.rounded_button import RoundedButton
from typing import Any, Callable, Optional

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

    def _describe_execution_time(self, elapsed: float, stdout: str, stderr: str, regex: Optional[str]) -> str:
        """How to phrase the runtime of one execute.sh run in the output pane.

        A run whose configuration asked for the program's own timing must say
        which of the two times it actually reports: a pattern that found nothing
        falls back to the wall clock time, and a fallback that looked like a
        measurement would be indistinguishable from one.
        """
        if regex is None:
            return f"{elapsed:.2f}s"
        # quiet: execute_configuration already searched this output and logged
        # whatever went wrong; a second warning in the pane only confuses.
        if extract_execution_time(stdout, stderr, regex, quiet=True) is None:
            return f"{elapsed:.2f}s wall clock (the output reported no execution time)"
        return f"{elapsed:.2f}s reported by the program"

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
        skip_cleanup = self.skip_cleanup_var.get()
        thread_count = self.thread_var.get()
        label_prefix = self.label_prefix_var.get()
        timeout_execution = self.timeout_execution_var.get()
        timeout_compilation = self.timeout_compilation_var.get()
        timeout_validation = self.timeout_validation_var.get()
        execution_repetitions = self.execution_repetitions_var.get()
        log_level = self.log_level_var.get()
        suggestions_mode = self.suggestions_mode_var.get()
        assert self.current_config is not None
        current_config = self.current_config
        config_path = os.path.join(self.config_dir, current_config)
        # Only execute.sh is searched for a time the program reports itself; the
        # setting belongs to that script and is stored with it (Editor -> execute.sh).
        execution_time_regex = resolve_execution_time_regex(config_path, self.arguments.execution_time_regex)
        args_copy = copy.copy(self.arguments)
        args_copy.execute_inplace = inplace
        args_copy.skip_cleanup = skip_cleanup
        args_copy.label_prefix = label_prefix
        args_copy.timeout_execution = timeout_execution
        args_copy.timeout_compilation = timeout_compilation
        args_copy.timeout_validation = timeout_validation
        args_copy.execution_repetitions = execution_repetitions
        args_copy.log_level = log_level

        combined_ids: list[str] = []

        if suggestions_mode == "manual":
            if hasattr(self, "execute_suggestion_selector"):
                combined_ids += self.execute_suggestion_selector.get_selected_ids()

        if suggestions_mode == "autotuner":
            autotuner_ids = read_autotuner_applied_suggestions(args_copy.dot_dp, current_config)
            combined_ids += [sid for sid in autotuner_ids if sid not in combined_ids]

        args_copy.apply_suggestions = ",".join(combined_ids) if combined_ids else None

        restore_logging = redirect_logging_to_text_area(self.output_text, log_level)

        logger = logging.getLogger("Execute")
        logger.info(f"Starting execution of configuration: {current_config}")

        # modes whose run was skipped because their patches could not be applied
        application_failures: list[tuple[str, Any]] = []

        def work(ctx: WorkContext) -> list[tuple[str, Any]]:
            if inplace:
                # the project root's .discopop survives between runs; a result recorded
                # by an earlier apply must not be attributed to this run
                clear_application_result(patch_applicator_dir_of(self.arguments.project_root))
            if inplace and args_copy.apply_suggestions:
                ctx.output("Note: Apply suggestions is ignored in inplace mode.\n")

            compile_sh = resolve_compile_script_path(self.arguments.project_config_dir, current_config)

            for mode in selected_modes:
                if ctx.cancel_event.is_set():
                    ctx.output("Execution stopped by user.\n")
                    break

                ctx.output(f"\n=== {mode.upper()} mode ===\n")

                resolved_settings_path = mode_settings_path(self.arguments.project_config_dir, mode)
                if resolved_settings_path is None:
                    continue
                settings_path = resolved_settings_path

                if inplace:
                    project_copy_path = self.arguments.project_root
                else:
                    ctx.output("Copying project...\n")
                    try:
                        project_copy_path = copy_configuration(args_copy, config_path, settings_path)
                    except Exception as e:
                        ctx.output(f"Error copying project: {e}\n")
                        continue

                    # A failed patch application leaves the copy holding the ORIGINAL
                    # code. Compiling and running it would produce a measurement that
                    # looks like a parallel configuration without a speedup, so the run
                    # is skipped and recorded as such instead.
                    application_result = get_application_result(project_copy_path)
                    if application_result is not None and application_result.failure:
                        summary = application_result.summary()
                        failed_ids = ", ".join(application_result.unapplied)
                        ctx.output(
                            "\n⚠ SUGGESTION APPLICATION FAILED for: "
                            + failed_ids
                            + "\n  "
                            + summary
                            + "\n  Skipping this run: executing the copy would measure the UNMODIFIED code.\n"
                        )
                        try:
                            record_skipped_execution(
                                args_copy,
                                project_copy_path,
                                config_path,
                                settings_path,
                                os.path.join(config_path, "execute.sh"),
                                1 if mode == "seq" else thread_count,
                                application_result,
                            )
                        except Exception as e:
                            ctx.output(f"Error recording skipped run: {e}\n")
                        application_failures.append((mode, application_result))
                        if not skip_cleanup:
                            try:
                                delete_configuration(args_copy, project_copy_path)
                            except Exception:
                                pass
                        continue

                ctx.status("⏳ Compiling...", StatusKind.BUSY)
                ctx.output("Compiling...\n")
                compile_result = execute_configuration(
                    args_copy,
                    project_copy_path,
                    config_path,
                    settings_path,
                    compile_sh,
                    1 if mode == "seq" else thread_count,
                    args_copy.timeout_compilation,
                    process_started_callback=ctx.register_process,
                )
                ctx.clear_process()

                if compile_result is None or compile_result[0] != 0:
                    ret_code = compile_result[0] if compile_result else "None"
                    ctx.output(f"Compilation failed (return code: {ret_code})\n")
                    if not inplace and not skip_cleanup:
                        try:
                            delete_configuration(args_copy, project_copy_path)
                        except Exception:
                            pass
                    continue

                ret_code, elapsed, stdout, stderr = compile_result
                ctx.output(f"Compilation succeeded ({elapsed:.2f}s)\n")
                if stdout:
                    ctx.output(f"stdout: {stdout}\n")
                if stderr:
                    ctx.output(f"stderr: {stderr}\n")

                if ctx.cancel_event.is_set():
                    ctx.output("Execution stopped by user.\n")
                    break

                ctx.status("⏳ Executing...", StatusKind.BUSY)
                ctx.output("Executing...\n")
                execute_result = execute_configuration(
                    args_copy,
                    project_copy_path,
                    config_path,
                    settings_path,
                    os.path.join(config_path, "execute.sh"),
                    1 if mode == "seq" else thread_count,
                    args_copy.timeout_execution,
                    process_started_callback=ctx.register_process,
                    execution_time_regex=execution_time_regex,
                    # Which modes are repeated is decided in one place, shared with
                    # the command line, so the two cannot drift apart.
                    repetitions=repetitions_for_mode(mode, args_copy.execution_repetitions),
                    should_abort=ctx.cancel_event.is_set,
                )
                ctx.clear_process()

                if execute_result is None or execute_result[0] != 0:
                    ret_code = execute_result[0] if execute_result else "None"
                    ctx.output(f"Execution failed (return code: {ret_code})\n")
                else:
                    ret_code, elapsed, stdout, stderr = execute_result
                    described = self._describe_execution_time(elapsed, stdout, stderr, execution_time_regex)
                    ctx.output(f"Execution succeeded ({described})\n")
                    if stdout:
                        ctx.output(f"stdout: {stdout}\n")
                    if stderr:
                        ctx.output(f"stderr: {stderr}\n")

                    # optional output validation (auto-run when validate.sh exists),
                    # applied only to the "real" runs (seq/par) — matching the CLI.
                    if mode in ("seq", "par") and has_validate_script(config_path):

                        def report_step(status: str, message: str) -> None:
                            ctx.status(status, StatusKind.BUSY)
                            ctx.output(message)

                        validation = run_validation_phase(
                            args_copy,
                            project_copy_path,
                            config_path,
                            settings_path,
                            1 if mode == "seq" else thread_count,
                            timeout_compilation=args_copy.timeout_compilation,
                            timeout_validation=args_copy.timeout_validation,
                            process_started_callback=ctx.register_process,
                            on_compile_start=lambda _script: report_step(
                                "⏳ Compiling for validation...", "Compiling for validation...\n"
                            ),
                            on_validate_start=lambda _script: report_step("⏳ Validating...", "Validating output...\n"),
                            should_abort=ctx.cancel_event.is_set,
                        )
                        ctx.clear_process()

                        if validation.compile_required:
                            if validation.compile_successful:
                                assert validation.compile_result is not None
                                _, c_elapsed, c_stdout, c_stderr = validation.compile_result
                                ctx.output(f"Validation build succeeded ({c_elapsed:.2f}s)\n")
                                if c_stdout:
                                    ctx.output(f"stdout: {c_stdout}\n")
                                if c_stderr:
                                    ctx.output(f"stderr: {c_stderr}\n")
                            else:
                                c_rc = validation.compile_result[0] if validation.compile_result else "None"
                                ctx.output(f"Validation build FAILED (return code: {c_rc})\n")

                        if validation.aborted:
                            ctx.output("Execution stopped by user.\n")
                        elif validation.compile_required and not validation.compile_successful:
                            ctx.output("Validation skipped: its build failed.\n")
                        elif not validation.validate_successful:
                            v_rc = validation.validate_result[0] if validation.validate_result else "None"
                            ctx.output(f"Validation FAILED (return code: {v_rc})\n")
                        else:
                            assert validation.validate_result is not None
                            _, v_elapsed, v_stdout, v_stderr = validation.validate_result
                            ctx.output(f"Validation succeeded ({v_elapsed:.2f}s)\n")
                            if v_stdout:
                                ctx.output(f"stdout: {v_stdout}\n")
                            if v_stderr:
                                ctx.output(f"stderr: {v_stderr}\n")

                if not inplace and not skip_cleanup:
                    try:
                        delete_configuration(args_copy, project_copy_path)
                    except Exception:
                        pass

            return application_failures

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
        self._update_report_display()
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

        args_copy = copy.copy(self.arguments)
        args_copy.execute_inplace = True
        args_copy.skip_cleanup = False
        args_copy.label_prefix = ""
        args_copy.timeout_execution = self.timeout_execution_var.get()
        args_copy.timeout_compilation = self.timeout_compilation_var.get()
        args_copy.timeout_validation = self.timeout_validation_var.get()
        args_copy.log_level = "INFO"
        args_copy.apply_suggestions = None

        current_config = self.current_config
        config_path = os.path.join(self.config_dir, current_config)

        restore_logging = redirect_logging_to_text_area(self.output_text, "INFO")

        logger = logging.getLogger(f"Prepare {status_noun.title()}")
        failure_status = f"{status_noun.capitalize()} preparation failed"

        def work(ctx: WorkContext) -> bool:
            logger.info(f"Starting {status_noun} preparation for: {current_config}")
            ctx.output(f"Compiling in '{mode}' mode with inplace execution...\n\n")
            # this always runs inplace; see the note in _run_execution
            clear_application_result(patch_applicator_dir_of(self.arguments.project_root))

            compile_sh = resolve_compile_script_path(self.arguments.project_config_dir, current_config)
            shared_settings = os.path.join(self.arguments.project_config_dir, settings_filename)

            ctx.status("⏳ Compiling...", StatusKind.BUSY)
            ctx.output("Compiling...\n")

            compile_result = execute_configuration(
                args_copy,
                self.arguments.project_root,
                config_path,
                shared_settings,
                compile_sh,
                1,
                args_copy.timeout_compilation,
                process_started_callback=ctx.register_process,
            )
            ctx.clear_process()

            success = False
            if compile_result is None or compile_result[0] != 0:
                ret_code = compile_result[0] if compile_result else "None"
                ctx.output(f"Compilation failed (return code: {ret_code})\n")
            else:
                ret_code, elapsed, stdout, stderr = compile_result
                ctx.output(f"Compilation succeeded ({elapsed:.2f}s)\n")
                if stdout:
                    ctx.output(f"stdout: {stdout}\n")
                if stderr:
                    ctx.output(f"stderr: {stderr}\n")

                if ctx.cancel_event.is_set():
                    ctx.output(f"{status_noun.capitalize()} preparation stopped by user.\n")
                else:
                    ctx.status("⏳ Executing...", StatusKind.BUSY)
                    ctx.output("Executing...\n")

                    execute_result = execute_configuration(
                        args_copy,
                        self.arguments.project_root,
                        config_path,
                        shared_settings,
                        os.path.join(config_path, "execute.sh"),
                        1,
                        args_copy.timeout_execution,
                        process_started_callback=ctx.register_process,
                        execution_time_regex=resolve_execution_time_regex(
                            config_path, self.arguments.execution_time_regex
                        ),
                    )
                    ctx.clear_process()

                    if execute_result is None or execute_result[0] != 0:
                        ret_code = execute_result[0] if execute_result else "None"
                        ctx.output(f"Execution failed (return code: {ret_code})\n")
                    else:
                        ret_code, elapsed, stdout, stderr = execute_result
                        ctx.output(
                            "Execution succeeded ("
                            + self._describe_execution_time(
                                elapsed,
                                stdout,
                                stderr,
                                resolve_execution_time_regex(config_path, self.arguments.execution_time_regex),
                            )
                            + ")\n"
                        )
                        if stdout:
                            ctx.output(f"stdout: {stdout}\n")
                        if stderr:
                            ctx.output(f"stderr: {stderr}\n")
                        success = True

            if not ctx.cancel_event.is_set():
                outcome = "complete" if success else "failed"
                ctx.output(f"\n=== {status_noun.capitalize()} preparation {outcome} ===\n")
            return success

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
                self._update_report_display()
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

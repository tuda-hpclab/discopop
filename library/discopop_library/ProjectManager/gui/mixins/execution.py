# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
import json
import logging
import os
import subprocess
import threading
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
from discopop_library.ProjectManager.gui import widgets
from discopop_library.ProjectManager.gui.mixins.mixin_base import ConfigManagerMixinBase
from discopop_library.ProjectManager.gui.mixins.helpers import show_warning
from discopop_library.ProjectManager.gui.rounded_button import RoundedButton
from typing import Any, Optional


class ExecutionMixin(ConfigManagerMixinBase):
    _execution_stop_event: threading.Event = threading.Event()
    _execution_process: Optional["subprocess.Popen[bytes]"] = None
    stop_execution_button: Optional[RoundedButton] = None

    def _register_execution_process(self, p: "subprocess.Popen[bytes]") -> None:
        self._execution_process = p

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

        self._execution_stop_event.clear()
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
            results_path = os.path.join(args_copy.dot_dp, "auto_tuner", "results.json")
            try:
                with open(results_path, "r") as f:
                    results_data = json.load(f)
                autotuner_ids = [str(s) for s in results_data.get(current_config, {}).get("applied_suggestions", [])]
                combined_ids += [sid for sid in autotuner_ids if sid not in combined_ids]
            except (json.JSONDecodeError, IOError):
                pass

        args_copy.apply_suggestions = ",".join(combined_ids) if combined_ids else None

        logging.basicConfig(level=log_level, force=True)
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)

        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        from discopop_library.ProjectManager.gui.mixins.helpers import TextAreaHandler

        text_handler = TextAreaHandler(self.output_text)
        text_handler.setLevel(log_level)
        formatter = logging.Formatter("[%(name)s] %(levelname)s: %(message)s")
        text_handler.setFormatter(formatter)
        root_logger.addHandler(text_handler)

        logger = logging.getLogger("Execute")
        logger.info(f"Starting execution of configuration: {current_config}")

        # modes whose run was skipped because their patches could not be applied
        application_failures: list[tuple[str, Any]] = []

        def thread_func() -> None:
            if inplace:
                # the project root's .discopop survives between runs; a result recorded
                # by an earlier apply must not be attributed to this run
                clear_application_result(patch_applicator_dir_of(self.arguments.project_root))
            if inplace and args_copy.apply_suggestions:
                self.after(  # type: ignore
                    0,
                    lambda: append_output("Note: Apply suggestions is ignored in inplace mode.\n"),
                )

            compile_sh = resolve_compile_script_path(self.arguments.project_config_dir, current_config)
            shared_seq_settings = os.path.join(self.arguments.project_config_dir, "seq_settings.json")
            shared_dp_settings = os.path.join(self.arguments.project_config_dir, "dp_settings.json")
            shared_hd_settings = os.path.join(self.arguments.project_config_dir, "hd_settings.json")
            shared_par_settings = os.path.join(self.arguments.project_config_dir, "par_settings.json")

            for mode in selected_modes:
                if self._execution_stop_event.is_set():
                    self.after(0, lambda: append_output("Execution stopped by user.\n"))  # type: ignore
                    break

                self.after(0, lambda m=mode: append_output(f"\n=== {m.upper()} mode ===\n"))  # type: ignore

                settings_file = f"{mode}_settings.json"
                if mode == "seq":
                    settings_path = shared_seq_settings
                elif mode == "dp":
                    settings_path = shared_dp_settings
                elif mode == "hd":
                    settings_path = shared_hd_settings
                elif mode == "par":
                    settings_path = shared_par_settings
                else:
                    continue

                if inplace:
                    project_copy_path = self.arguments.project_root
                else:
                    self.after(0, lambda: append_output("Copying project...\n"))  # type: ignore
                    try:
                        project_copy_path = copy_configuration(args_copy, config_path, settings_path)
                    except Exception as e:
                        self.after(0, lambda e_msg=str(e): append_output(f"Error copying project: {e_msg}\n"))  # type: ignore
                        continue

                    # A failed patch application leaves the copy holding the ORIGINAL
                    # code. Compiling and running it would produce a measurement that
                    # looks like a parallel configuration without a speedup, so the run
                    # is skipped and recorded as such instead.
                    application_result = get_application_result(project_copy_path)
                    if application_result is not None and application_result.failure:
                        summary = application_result.summary()
                        failed_ids = ", ".join(application_result.unapplied)
                        self.after(  # type: ignore
                            0,
                            lambda s=summary, ids=failed_ids: append_output(
                                "\n⚠ SUGGESTION APPLICATION FAILED for: "
                                + ids
                                + "\n  "
                                + s
                                + "\n  Skipping this run: executing the copy would measure the UNMODIFIED code.\n"
                            ),
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
                            self.after(0, lambda e_msg=str(e): append_output(f"Error recording skipped run: {e_msg}\n"))  # type: ignore
                        application_failures.append((mode, application_result))
                        if not skip_cleanup:
                            try:
                                delete_configuration(args_copy, project_copy_path)
                            except Exception:
                                pass
                        continue

                self.after(0, lambda: self.status_label.config(text="⏳ Compiling...", foreground=widgets.STATUS_BUSY))  # type: ignore
                self.after(0, lambda: append_output("Compiling...\n"))  # type: ignore
                compile_result = execute_configuration(
                    args_copy,
                    project_copy_path,
                    config_path,
                    settings_path,
                    compile_sh,
                    1 if mode == "seq" else thread_count,
                    args_copy.timeout_compilation,
                    process_started_callback=self._register_execution_process,
                )
                self._execution_process = None

                if compile_result is None or compile_result[0] != 0:
                    ret_code = compile_result[0] if compile_result else "None"
                    self.after(0, lambda rc=ret_code: append_output(f"Compilation failed (return code: {rc})\n"))  # type: ignore
                    if not inplace and not skip_cleanup:
                        try:
                            delete_configuration(args_copy, project_copy_path)
                        except Exception:
                            pass
                    continue

                ret_code, elapsed, stdout, stderr = compile_result
                self.after(0, lambda e=elapsed: append_output(f"Compilation succeeded ({e:.2f}s)\n"))  # type: ignore
                if stdout:
                    self.after(0, lambda o=stdout: append_output(f"stdout: {o}\n"))  # type: ignore
                if stderr:
                    self.after(0, lambda e=stderr: append_output(f"stderr: {e}\n"))  # type: ignore

                if self._execution_stop_event.is_set():
                    self.after(0, lambda: append_output("Execution stopped by user.\n"))  # type: ignore
                    break

                self.after(0, lambda: self.status_label.config(text="⏳ Executing...", foreground=widgets.STATUS_BUSY))  # type: ignore
                self.after(0, lambda: append_output("Executing...\n"))  # type: ignore
                execute_result = execute_configuration(
                    args_copy,
                    project_copy_path,
                    config_path,
                    settings_path,
                    os.path.join(config_path, "execute.sh"),
                    1 if mode == "seq" else thread_count,
                    args_copy.timeout_execution,
                    process_started_callback=self._register_execution_process,
                    execution_time_regex=execution_time_regex,
                    # Which modes are repeated is decided in one place, shared with
                    # the command line, so the two cannot drift apart.
                    repetitions=repetitions_for_mode(mode, args_copy.execution_repetitions),
                    should_abort=self._execution_stop_event.is_set,
                )
                self._execution_process = None

                if execute_result is None or execute_result[0] != 0:
                    ret_code = execute_result[0] if execute_result else "None"
                    self.after(0, lambda rc=ret_code: append_output(f"Execution failed (return code: {rc})\n"))  # type: ignore
                else:
                    ret_code, elapsed, stdout, stderr = execute_result
                    described = self._describe_execution_time(elapsed, stdout, stderr, execution_time_regex)
                    self.after(0, lambda d=described: append_output(f"Execution succeeded ({d})\n"))  # type: ignore
                    if stdout:
                        self.after(0, lambda o=stdout: append_output(f"stdout: {o}\n"))  # type: ignore
                    if stderr:
                        self.after(0, lambda e=stderr: append_output(f"stderr: {e}\n"))  # type: ignore

                    # optional output validation (auto-run when validate.sh exists),
                    # applied only to the "real" runs (seq/par) — matching the CLI.
                    if mode in ("seq", "par") and has_validate_script(config_path):

                        def report_step(status: str, message: str) -> None:
                            self.after(0, lambda: self.status_label.config(text=status, foreground=widgets.STATUS_BUSY))  # type: ignore
                            self.after(0, lambda: append_output(message))  # type: ignore

                        validation = run_validation_phase(
                            args_copy,
                            project_copy_path,
                            config_path,
                            settings_path,
                            1 if mode == "seq" else thread_count,
                            timeout_compilation=args_copy.timeout_compilation,
                            timeout_validation=args_copy.timeout_validation,
                            process_started_callback=self._register_execution_process,
                            on_compile_start=lambda _script: report_step(
                                "⏳ Compiling for validation...", "Compiling for validation...\n"
                            ),
                            on_validate_start=lambda _script: report_step("⏳ Validating...", "Validating output...\n"),
                            should_abort=self._execution_stop_event.is_set,
                        )
                        self._execution_process = None

                        if validation.compile_required:
                            if validation.compile_successful:
                                assert validation.compile_result is not None
                                _, c_elapsed, c_stdout, c_stderr = validation.compile_result
                                self.after(0, lambda e=c_elapsed: append_output(f"Validation build succeeded ({e:.2f}s)\n"))  # type: ignore
                                if c_stdout:
                                    self.after(0, lambda o=c_stdout: append_output(f"stdout: {o}\n"))  # type: ignore
                                if c_stderr:
                                    self.after(0, lambda e=c_stderr: append_output(f"stderr: {e}\n"))  # type: ignore
                            else:
                                c_rc = validation.compile_result[0] if validation.compile_result else "None"
                                self.after(0, lambda rc=c_rc: append_output(f"Validation build FAILED (return code: {rc})\n"))  # type: ignore

                        if validation.aborted:
                            self.after(0, lambda: append_output("Execution stopped by user.\n"))  # type: ignore
                        elif validation.compile_required and not validation.compile_successful:
                            self.after(0, lambda: append_output("Validation skipped: its build failed.\n"))  # type: ignore
                        elif not validation.validate_successful:
                            v_rc = validation.validate_result[0] if validation.validate_result else "None"
                            self.after(0, lambda rc=v_rc: append_output(f"Validation FAILED (return code: {rc})\n"))  # type: ignore
                        else:
                            assert validation.validate_result is not None
                            _, v_elapsed, v_stdout, v_stderr = validation.validate_result
                            self.after(0, lambda e=v_elapsed: append_output(f"Validation succeeded ({e:.2f}s)\n"))  # type: ignore
                            if v_stdout:
                                self.after(0, lambda o=v_stdout: append_output(f"stdout: {o}\n"))  # type: ignore
                            if v_stderr:
                                self.after(0, lambda e=v_stderr: append_output(f"stderr: {e}\n"))  # type: ignore

                if not inplace and not skip_cleanup:
                    try:
                        delete_configuration(args_copy, project_copy_path)
                    except Exception:
                        pass

            if application_failures:
                modes_str = ", ".join(mode for mode, _res in application_failures)
                details = "\n\n".join(mode + ": " + res.summary() for mode, res in application_failures)
                self.after(  # type: ignore
                    0,
                    lambda: append_output(
                        "\n⚠ "
                        + str(len(application_failures))
                        + " run(s) were SKIPPED because their suggestions could not be applied ("
                        + modes_str
                        + ").\n  They appear as '⚠ not applied' in the Report tab.\n"
                    ),
                )
                self.after(  # type: ignore
                    0,
                    lambda: show_warning(
                        self,
                        "Suggestion Application Failed",
                        "The selected parallelization suggestions could not be applied.\n\n"
                        + details
                        + "\n\nThe affected runs were skipped, because executing them would have "
                        "measured the unmodified sequential code. They are recorded as "
                        "'not applied' in the Report tab so they can be told apart from a "
                        "parallel run without a speedup.",
                    ),
                )

            self.after(0, lambda: append_output("\n=== Execution complete ===\n"))  # type: ignore
            self.after(0, lambda: self.run_button.config(state=tk.NORMAL, text="Run"))  # type: ignore
            self.after(0, lambda: self.stop_execution_button.config(state="disabled") if self.stop_execution_button else None)  # type: ignore
            self.after(0, lambda: self.generate_report_button.config(state=tk.NORMAL))  # type: ignore
            self.after(0, lambda: self.inplace_var.set(False))  # type: ignore
            if application_failures:
                self.after(  # type: ignore
                    0,
                    lambda: self.status_label.config(
                        text="⚠ Suggestion application failed", foreground=widgets.STATUS_FAIL
                    ),
                )
            else:
                self.after(0, lambda: self.status_label.config(text="Ready", foreground=widgets.STATUS_IDLE))  # type: ignore
            self.after(0, lambda: self._refresh_config_list())  # type: ignore
            self.after(0, lambda: self._update_report_display())  # type: ignore
            self.after(0, lambda: self._update_pattern_detection_ui())  # type: ignore

        threading.Thread(target=thread_func, daemon=True).start()

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

        self._execution_stop_event.clear()
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

        def emit(text: str) -> None:
            """Schedule ``text`` for display; safe to call from the worker thread."""
            self.after(0, lambda t=text: append_output(t))  # type: ignore

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

        import logging

        logging.basicConfig(level="INFO", force=True)
        root_logger = logging.getLogger()
        root_logger.setLevel("INFO")

        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        from discopop_library.ProjectManager.gui.mixins.helpers import TextAreaHandler

        text_handler = TextAreaHandler(self.output_text)
        text_handler.setLevel("INFO")
        formatter = logging.Formatter("[%(name)s] %(levelname)s: %(message)s")
        text_handler.setFormatter(formatter)
        root_logger.addHandler(text_handler)

        logger = logging.getLogger(f"Prepare {status_noun.title()}")
        failure_status = f"{status_noun.capitalize()} preparation failed"

        def thread_func() -> None:
            logger.info(f"Starting {status_noun} preparation for: {current_config}")
            emit(f"Compiling in '{mode}' mode with inplace execution...\n\n")
            # this always runs inplace; see the note in _run_execution
            clear_application_result(patch_applicator_dir_of(self.arguments.project_root))

            compile_sh = resolve_compile_script_path(self.arguments.project_config_dir, current_config)
            shared_settings = os.path.join(self.arguments.project_config_dir, settings_filename)

            self.after(0, lambda: self.status_label.config(text="⏳ Compiling...", foreground=widgets.STATUS_BUSY))  # type: ignore
            emit("Compiling...\n")

            compile_result = execute_configuration(
                args_copy,
                self.arguments.project_root,
                config_path,
                shared_settings,
                compile_sh,
                1,
                args_copy.timeout_compilation,
                process_started_callback=self._register_execution_process,
            )
            self._execution_process = None

            success = False
            if compile_result is None or compile_result[0] != 0:
                ret_code = compile_result[0] if compile_result else "None"
                emit(f"Compilation failed (return code: {ret_code})\n")
            else:
                ret_code, elapsed, stdout, stderr = compile_result
                emit(f"Compilation succeeded ({elapsed:.2f}s)\n")
                if stdout:
                    emit(f"stdout: {stdout}\n")
                if stderr:
                    emit(f"stderr: {stderr}\n")

                if self._execution_stop_event.is_set():
                    emit(f"{status_noun.capitalize()} preparation stopped by user.\n")
                else:
                    self.after(0, lambda: self.status_label.config(text="⏳ Executing...", foreground=widgets.STATUS_BUSY))  # type: ignore
                    emit("Executing...\n")

                    execute_result = execute_configuration(
                        args_copy,
                        self.arguments.project_root,
                        config_path,
                        shared_settings,
                        os.path.join(config_path, "execute.sh"),
                        1,
                        args_copy.timeout_execution,
                        process_started_callback=self._register_execution_process,
                        execution_time_regex=resolve_execution_time_regex(
                            config_path, self.arguments.execution_time_regex
                        ),
                    )
                    self._execution_process = None

                    if execute_result is None or execute_result[0] != 0:
                        ret_code = execute_result[0] if execute_result else "None"
                        emit(f"Execution failed (return code: {ret_code})\n")
                    else:
                        ret_code, elapsed, stdout, stderr = execute_result
                        emit(
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
                            emit(f"stdout: {stdout}\n")
                        if stderr:
                            emit(f"stderr: {stderr}\n")
                        success = True

            if not self._execution_stop_event.is_set():
                outcome = "complete" if success else "failed"
                emit(f"\n=== {status_noun.capitalize()} preparation {outcome} ===\n")
            self.after(0, lambda: button.config(state=tk.NORMAL, text=button_label))  # type: ignore
            self.after(0, lambda: self._update_execute_modes())  # type: ignore
            self.after(0, lambda: self.stop_execution_button.config(state="disabled") if self.stop_execution_button else None)  # type: ignore
            self.after(0, lambda: self.run_button.config(state=tk.NORMAL))  # type: ignore
            self.after(0, lambda: self.generate_report_button.config(state=tk.NORMAL))  # type: ignore
            if success or self._execution_stop_event.is_set():
                self.after(0, lambda: self.status_label.config(text="Ready", foreground=widgets.STATUS_IDLE))  # type: ignore
            else:
                self.after(0, lambda: self._set_status(failure_status, fg=widgets.STATUS_FAIL, reset_delay=3000))  # type: ignore
            self.after(0, lambda: self._update_report_display())  # type: ignore
            self.after(0, lambda: self._update_pattern_detection_ui())  # type: ignore

        threading.Thread(target=thread_func, daemon=True).start()

    def _stop_execution(self) -> None:
        self._execution_stop_event.set()
        if self._execution_process is not None:
            self._execution_process.terminate()
        if self.run_button is not None:
            self.run_button.config(state="normal", text="Run")
        if self.prepare_pattern_detection_button is not None:
            self.prepare_pattern_detection_button.config(state="normal", text="Prepare Pattern Detection")
        if self.stop_execution_button is not None:
            self.stop_execution_button.config(state="disabled")
        self.status_label.config(text="Stopping execution...", foreground=widgets.STATUS_STOP)

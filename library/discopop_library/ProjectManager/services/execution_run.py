# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the Execute tab runs in the background, without a toolkit.

A panel reads its widgets into an :class:`ExecutionRequest` (or a :class:`PreparationRequest`) on the main thread and
hands it to :func:`run_execution` (or :func:`run_preparation`) as the work of a ``WorkRunner``: the function reports
only through the ``WorkContext`` and never touches a widget.
"""

import copy
import logging
import os
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from discopop_library.PatchApplicator.PatchApplicationResult import clear_application_result
from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.configurations.copying import (
    copy_configuration,
    get_application_result,
    patch_applicator_dir_of,
)
from discopop_library.ProjectManager.configurations.deletion import delete_configuration
from discopop_library.ProjectManager.configurations.execution import execute_configuration, record_skipped_execution
from discopop_library.ProjectManager.configurations.execution_time import (
    EXECUTION_TIME_DISABLED,
    extract_execution_time,
    resolve_execution_time_regex,
)
from discopop_library.ProjectManager.configurations.repetitions import repetitions_for_mode
from discopop_library.ProjectManager.configurations.validation import has_validate_script, run_validation_phase
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.services.autotuner_results import read_autotuner_applied_suggestions
from discopop_library.ProjectManager.services.jobs import StatusKind, WorkContext
from discopop_library.ProjectManager.services.modes import settings_path as mode_settings_path

SUGGESTIONS_NONE = "none"
SUGGESTIONS_MANUAL = "manual"
SUGGESTIONS_AUTOTUNER = "autotuner"


@dataclass(frozen=True)
class ExecutionRequest:
    """The settings of one run of the Execute tab."""

    configuration: str
    modes: Tuple[str, ...]
    inplace: bool
    skip_cleanup: bool
    thread_count: int
    label_prefix: str
    timeout_execution: int
    timeout_compilation: int
    timeout_validation: int
    repetitions: int
    log_level: str
    suggestion_ids: Tuple[str, ...]


@dataclass(frozen=True)
class PreparationRequest:
    """The settings of a preparation run (compile and execute once, in place)."""

    configuration: str
    mode: str
    settings_filename: str
    status_noun: str
    timeout_execution: int
    timeout_compilation: int
    timeout_validation: int


def suggestion_ids_to_apply(
    suggestions_mode: str, manual_ids: List[str], dot_dp: str, configuration: str
) -> Tuple[str, ...]:
    """The suggestion IDs a run applies: the selected ones (manual) or the autotuner's selection."""
    combined: List[str] = []
    if suggestions_mode == SUGGESTIONS_MANUAL:
        combined += manual_ids
    if suggestions_mode == SUGGESTIONS_AUTOTUNER:
        combined += [sid for sid in read_autotuner_applied_suggestions(dot_dp, configuration) if sid not in combined]
    return tuple(combined)


def execution_time_summary(override: Optional[str], enabled: bool) -> str:
    """How the runtime of a configuration is measured, for the Execute tab (``enabled``: the stored setting)."""
    if override is not None:
        if override != EXECUTION_TIME_DISABLED:
            return "from the console output (forced by --execution-time-regex)"
        return "wall clock of execute.sh (forced by --execution-time-regex)"
    if enabled:
        return "from the console output (see Editor -> execute.sh)"
    return "wall clock of execute.sh"


def describe_execution_time(elapsed: float, stdout: str, stderr: str, regex: Optional[str]) -> str:
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


def run_execution(
    arguments: ProjectManagerArguments, request: ExecutionRequest, ctx: WorkContext
) -> List[Tuple[str, Any]]:
    """Run ``request`` and return the modes whose run was skipped because their patches could not be applied."""
    current_config = request.configuration
    inplace = request.inplace
    skip_cleanup = request.skip_cleanup
    thread_count = request.thread_count
    config_path = os.path.join(arguments.project_config_dir, current_config)
    # Only execute.sh is searched for a time the program reports itself; the
    # setting belongs to that script and is stored with it (Editor -> execute.sh).
    execution_time_regex = resolve_execution_time_regex(config_path, arguments.execution_time_regex)
    args_copy = copy.copy(arguments)
    args_copy.execute_inplace = inplace
    args_copy.skip_cleanup = skip_cleanup
    args_copy.label_prefix = request.label_prefix
    args_copy.timeout_execution = request.timeout_execution
    args_copy.timeout_compilation = request.timeout_compilation
    args_copy.timeout_validation = request.timeout_validation
    args_copy.execution_repetitions = request.repetitions
    args_copy.log_level = request.log_level
    args_copy.apply_suggestions = ",".join(request.suggestion_ids) if request.suggestion_ids else None

    # modes whose run was skipped because their patches could not be applied
    application_failures: List[Tuple[str, Any]] = []

    if inplace:
        # the project root's .discopop survives between runs; a result recorded
        # by an earlier apply must not be attributed to this run
        clear_application_result(patch_applicator_dir_of(arguments.project_root))
    if inplace and args_copy.apply_suggestions:
        ctx.output("Note: Apply suggestions is ignored in inplace mode.\n")

    compile_sh = resolve_compile_script_path(arguments.project_config_dir, current_config)

    for mode in request.modes:
        if ctx.cancel_event.is_set():
            ctx.output("Execution stopped by user.\n")
            break

        ctx.output(f"\n=== {mode.upper()} mode ===\n")

        resolved_settings_path = mode_settings_path(arguments.project_config_dir, mode)
        if resolved_settings_path is None:
            continue
        settings_path = resolved_settings_path

        if inplace:
            project_copy_path = arguments.project_root
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
            described = describe_execution_time(elapsed, stdout, stderr, execution_time_regex)
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


def run_preparation(arguments: ProjectManagerArguments, request: PreparationRequest, ctx: WorkContext) -> bool:
    """Compile and execute ``request.configuration`` in ``request.mode`` in place; True if both succeeded."""
    mode = request.mode
    status_noun = request.status_noun
    current_config = request.configuration
    config_path = os.path.join(arguments.project_config_dir, current_config)
    args_copy = copy.copy(arguments)
    args_copy.execute_inplace = True
    args_copy.skip_cleanup = False
    args_copy.label_prefix = ""
    args_copy.timeout_execution = request.timeout_execution
    args_copy.timeout_compilation = request.timeout_compilation
    args_copy.timeout_validation = request.timeout_validation
    args_copy.log_level = "INFO"
    args_copy.apply_suggestions = None

    logger = logging.getLogger(f"Prepare {status_noun.title()}")
    logger.info(f"Starting {status_noun} preparation for: {current_config}")
    ctx.output(f"Compiling in '{mode}' mode with inplace execution...\n\n")
    # this always runs inplace; see the note in run_execution
    clear_application_result(patch_applicator_dir_of(arguments.project_root))

    compile_sh = resolve_compile_script_path(arguments.project_config_dir, current_config)
    shared_settings = os.path.join(arguments.project_config_dir, request.settings_filename)

    ctx.status("⏳ Compiling...", StatusKind.BUSY)
    ctx.output("Compiling...\n")

    compile_result = execute_configuration(
        args_copy,
        arguments.project_root,
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

            execution_time_regex = resolve_execution_time_regex(config_path, arguments.execution_time_regex)
            execute_result = execute_configuration(
                args_copy,
                arguments.project_root,
                config_path,
                shared_settings,
                os.path.join(config_path, "execute.sh"),
                1,
                args_copy.timeout_execution,
                process_started_callback=ctx.register_process,
                execution_time_regex=execution_time_regex,
            )
            ctx.clear_process()

            if execute_result is None or execute_result[0] != 0:
                ret_code = execute_result[0] if execute_result else "None"
                ctx.output(f"Execution failed (return code: {ret_code})\n")
            else:
                ret_code, elapsed, stdout, stderr = execute_result
                described = describe_execution_time(elapsed, stdout, stderr, execution_time_regex)
                ctx.output(f"Execution succeeded ({described})\n")
                if stdout:
                    ctx.output(f"stdout: {stdout}\n")
                if stderr:
                    ctx.output(f"stderr: {stderr}\n")
                success = True

    if not ctx.cancel_event.is_set():
        outcome = "complete" if success else "failed"
        ctx.output(f"\n=== {status_noun.capitalize()} preparation {outcome} ===\n")
    return success

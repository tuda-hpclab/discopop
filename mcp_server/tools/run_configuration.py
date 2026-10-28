# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""run_configuration: build the project as it is and run an execution configuration.

The agent edits the sources itself, so it needs a way to build and run the result and to read what
it took: the time, whether it succeeded, what the program printed, and the errors and warnings that
came up on the way. Nothing here is instrumented; it is the plain build the program is shipped with.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from mcp.types import TextContent, Tool, ToolAnnotations

from discopop_library.ProjectManager.configurations.compile_script import (
    resolve_compile_script_path,
    resolve_validation_compile_script_path,
    validation_needs_separate_compile,
)
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.configurations.execution_time import resolve_execution_time_regex
from discopop_library.ProjectManager.configurations.repetitions import validate_repetitions
from mcp_server.tools.helpers import (
    ToolContext,
    configuration_names,
    diagnostics,
    invalid_configuration_name,
    tail_of_output,
    unknown_configuration_message,
)

logger = logging.getLogger("discopop-mcp")

TOOL_NAME = "run_configuration"

# Diagnostics of a compiler or a script listed in the answer; the number of the rest is given.
MAX_DIAGNOSTICS = 5
# How much of the program's output and of what it wrote to stderr the answer carries.
MAX_OUTPUT_LINES = 15
MAX_LINE_CHARS = 200

TOOL = Tool(
    name=TOOL_NAME,
    # Builds in the project (its build directory) and records the runs; the sources are never touched.
    annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True, openWorldHint=False),
    description=(
        "Build the project as it is now, without instrumentation, and run an execution configuration: "
        "to check that your changes compile and give the same result, and to measure how long the program "
        "takes, e.g. with different thread counts. Returns a text: whether the build and the run "
        "succeeded and the time of the run (the median of repetitions; the program's own timing output "
        "if the configuration extracts one), the result of the configuration's validate.sh if it has "
        "one, the errors and warnings of the build and of the run, and the end of the program's output. "
        "Without a validate.sh only the exit code is checked, so compare the output yourself."
        "\n\n"
        "The build uses the project's compile script, the run the configuration's execute.sh, with "
        "OMP_NUM_THREADS set to threads. The runtime of the unmodified program is what you compare "
        "against: run this before you change the sources, and again after. Does not modify the sources."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root directory.",
            },
            "config_name": {
                "type": "string",
                "description": "The execution configuration to run, as listed by get_configurations.",
            },
            "threads": {
                "type": "integer",
                "description": "Number of OpenMP threads (OMP_NUM_THREADS). Default: the number of CPUs.",
            },
            "repetitions": {
                "type": "integer",
                "description": "How often to run it; the median time is reported. Default: 1.",
            },
            "rebuild": {
                "type": "boolean",
                "description": "Build before running. Set to false to run the last build again, e.g. for another "
                "thread count. Default: true.",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "Maximum time of the build and of each run. Default: 3600.",
            },
        },
        "required": ["project_path", "config_name"],
        "additionalProperties": False,
    },
)


def _lines(text: Any, count: int) -> list[str]:
    """The last `count` non-empty lines of a script's output, each cut to a readable length."""
    tail, _ = tail_of_output(text)
    lines = [line.rstrip() for line in tail.splitlines() if line.strip()]
    return [line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + "..." for line in lines[-count:]]


def _diagnostic_lines(title: str, found: list[str]) -> list[str]:
    if not found:
        return []
    lines = [f"{title} ({len(found)}):"] + [f"- {line}" for line in found[:MAX_DIAGNOSTICS]]
    if len(found) > MAX_DIAGNOSTICS:
        lines.append(f"- {len(found) - MAX_DIAGNOSTICS} more.")
    return lines


def _plain_settings(configs_dir: Path) -> Optional[Path]:
    """What the parallelized code is built with: par_settings.json, else seq_settings.json."""
    for name in ("par_settings.json", "seq_settings.json"):
        if (configs_dir / name).exists():
            return configs_dir / name
    return None


def _run(
    ctx: ToolContext,
    project_path: str,
    config_dir: Path,
    settings: Path,
    script: str,
    threads: int,
    timeout_seconds: int,
    **extra: Any,
) -> Optional[tuple[int, float, str, str]]:
    original_cwd = os.getcwd()
    try:
        result: Optional[tuple[int, float, str, str]] = execute_configuration(
            arguments=ctx.make_pm_args(project_path, timeout_seconds),
            project_copy_root_path=project_path,
            config_path=str(config_dir),
            settings_path=str(settings),
            script_path=script,
            thread_count=threads,
            timeout=float(timeout_seconds),
            process_started_callback=ctx.track_process,
            should_abort=lambda: ctx.cancelled,
            **extra,
        )
        return result
    finally:
        os.chdir(original_cwd)


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path: str = arguments.get("project_path", "")
        config_name: str = arguments.get("config_name", "")
        threads = int(arguments["threads"]) if arguments.get("threads") is not None else (os.cpu_count() or 1)
        repetitions = int(arguments.get("repetitions", 1))
        rebuild = bool(arguments.get("rebuild", True))
        timeout_seconds = int(arguments.get("timeout_seconds", 3600))

        name_error = invalid_configuration_name(config_name)
        if name_error is not None:
            return ctx.error(name_error, project_path, TOOL_NAME)
        if threads < 1:
            return ctx.error(f"threads must be at least 1, not {threads}.", project_path, TOOL_NAME)
        repetitions_error = validate_repetitions(repetitions)
        if repetitions_error is not None:
            return ctx.error(f"repetitions: {repetitions_error}.", project_path, TOOL_NAME)

        configs_dir = Path(project_path) / ".discopop" / "project" / "configs"
        config_dir = configs_dir / config_name
        if not (config_dir / "execute.sh").is_file():
            return ctx.error(
                unknown_configuration_message(configs_dir, config_name),
                project_path,
                TOOL_NAME,
                next_step=f"The configurations are {configuration_names(configs_dir)}; get_configurations shows them.",
            )
        settings = _plain_settings(configs_dir)
        if settings is None:
            return ctx.error("The project has no seq_settings.json. Run initialize_discopop_directory first.")

        with ctx.heartbeat():
            text = _build_run_validate(
                ctx,
                project_path,
                config_name,
                configs_dir,
                config_dir,
                settings,
                threads,
                repetitions,
                rebuild,
                timeout_seconds,
            )
        ctx.log_action(project_path, TOOL_NAME, f"Ran '{config_name}' with {threads} threads")
        return [TextContent(type="text", text=text)]

    except Exception as e:
        error_msg = f"Error running the configuration: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return ctx.error(error_msg, arguments.get("project_path", ""), TOOL_NAME)


def _build_run_validate(
    ctx: ToolContext,
    project_path: str,
    config_name: str,
    configs_dir: Path,
    config_dir: Path,
    settings: Path,
    threads: int,
    repetitions: int,
    rebuild: bool,
    timeout_seconds: int,
) -> str:
    lines: list[str] = []
    header = f"Configuration '{config_name}' with {threads} thread{'s' if threads != 1 else ''}"

    # --- build
    build_diagnostics: list[str] = []
    if rebuild:
        compile_sh = resolve_compile_script_path(str(configs_dir), config_name)
        built = _run(ctx, project_path, config_dir, settings, compile_sh, 1, timeout_seconds)
        if built is None:
            return f"{header}: the build could not be started ({settings.name} is missing)."
        returncode, _, stdout, stderr = built
        build_diagnostics = diagnostics(stdout, stderr)
        if ctx.cancelled:
            return f"{header}: cancelled."
        if returncode != 0:
            failed = [f"{header}: the build failed (exit code {returncode}); the program was not run."]
            errors = [line for line in build_diagnostics if re.search(r"\berror\b", line, re.IGNORECASE)]
            failed += _diagnostic_lines("Build errors", errors)
            if not errors:
                failed += ["End of the build output:"] + [
                    f"  {line}" for line in _lines(stderr or stdout, MAX_OUTPUT_LINES)
                ]
            failed += _diagnostic_lines("Build warnings", [d for d in build_diagnostics if d not in errors])
            return "\n".join(failed)

    # --- run
    measurement: dict[str, Any] = {}
    execute_sh = str(config_dir / "execute.sh")
    ran = _run(
        ctx,
        project_path,
        config_dir,
        settings,
        execute_sh,
        threads,
        timeout_seconds,
        execution_time_regex=resolve_execution_time_regex(str(config_dir), None),
        measurement=measurement,
        repetitions=repetitions,
    )
    if ran is None:
        return f"{header}: the run could not be started."
    returncode, elapsed, stdout, stderr = ran
    if ctx.cancelled:
        return f"{header}: cancelled."

    timed_out = bool(measurement.get("timeout_expired"))
    if timed_out:
        lines.append(f"{header}: the run timed out after {timeout_seconds} s.")
    elif returncode != 0:
        lines.append(f"{header}: the run failed (exit code {returncode}).")
    else:
        how = f" (median of {repetitions} runs)" if repetitions > 1 else ""
        source = ""
        if measurement.get("time_source") == "console":
            source = ", as the program reports it"
        lines.append(f"{header}: built and ran successfully in {elapsed:.2f} s{how}{source}.")
    run_ok = returncode == 0 and not timed_out

    # --- validate
    if run_ok and (config_dir / "validate.sh").is_file():
        if validation_needs_separate_compile(str(configs_dir), config_name):
            compile_validate = resolve_validation_compile_script_path(str(configs_dir), config_name)
            _run(ctx, project_path, config_dir, settings, compile_validate, 1, timeout_seconds)
        validated = _run(ctx, project_path, config_dir, settings, str(config_dir / "validate.sh"), 1, timeout_seconds)
        if validated is not None and validated[0] == 0:
            lines.append("Validation passed.")
        elif validated is not None:
            lines.append(f"Validation failed (exit code {validated[0]}): the output is not the expected one.")
            lines += [f"  {line}" for line in _lines(validated[3] or validated[2], 5)]
    elif run_ok:
        lines.append("There is no validate.sh, so the output was not checked; only the exit code.")

    # --- what came up on the way
    lines += _diagnostic_lines("Build warnings", build_diagnostics)
    run_diagnostics = diagnostics(stderr)
    if run_ok:
        lines += _diagnostic_lines("Warnings of the run", run_diagnostics)
    else:
        lines += _diagnostic_lines("Errors of the run", run_diagnostics)
    shown_stderr = _lines(stderr, MAX_OUTPUT_LINES)
    if shown_stderr and (not run_ok or not run_diagnostics):
        lines += ["The program wrote to stderr:"] + [f"  {line}" for line in shown_stderr]
    shown_output = _lines(stdout, MAX_OUTPUT_LINES)
    lines += (
        ["Output (the end):"] + [f"  {line}" for line in shown_output]
        if shown_output
        else ["The program printed nothing."]
    )
    return "\n".join(lines)

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import logging
from pathlib import Path
from typing import Any, Optional

from mcp.types import TextContent, Tool, ToolAnnotations

# OUTPUT_TAIL_CHARS is re-exported: the limit belongs to this tool's documented output
from mcp_server.tools.helpers import OUTPUT_TAIL_CHARS as OUTPUT_TAIL_CHARS
from mcp_server.tools.helpers import ToolContext, tail_of_output

logger = logging.getLogger("discopop-mcp")

TOOL = Tool(
    name="get_execution_results",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Show the recorded runs of a project's scripts, to find out why something failed: "
        "a build or profiling step of gather_data, a candidate run_auto_tuning rejected, or a "
        "run started from the DiscoPoP GUI or command line. run_auto_tuning already reports "
        "its selection and speedup; this is where the individual runs behind it are."
        "\n\n"
        "Results are grouped by configuration, script (compile.sh, execute.sh, validate.sh, ...) "
        "and settings file (seq/dp/hd/par_settings.json), with one compact entry per run: "
        "code (return code; -1 = not executed because its suggestions could not be applied), "
        "time (seconds), time_source ('wall_clock'; 'console' when the program's own timing "
        "output was read, then wall_clock_time is given too; 'wall_clock_fallback' when that "
        "output was expected but missing), thread_count and applied_suggestions. "
        "failed_suggestions, timeout_expired, repetitions and label appear only when they "
        "carry information."
        "\n\n"
        "Program output is left out by default. Call with failed_only=true and "
        "include_output=true to see why runs failed; the output is cut to its last "
        f"{OUTPUT_TAIL_CHARS} characters per stream."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the target project root directory.",
            },
            "config_name": {
                "type": "string",
                "description": "Only return the runs of this execution configuration.",
            },
            "script": {
                "type": "string",
                "description": "Only return the runs of this script, e.g. 'execute.sh' or 'compile.sh'.",
            },
            "failed_only": {
                "type": "boolean",
                "description": (
                    "Only return runs that failed: a non-zero return code, a timeout, or suggestions "
                    "that could not be applied. Default: false."
                ),
            },
            "include_output": {
                "type": "boolean",
                "description": (
                    f"Add the last {OUTPUT_TAIL_CHARS} characters of each run's stdout and stderr. "
                    "Default: false. Combine with failed_only or the filters to keep the result small."
                ),
            },
        },
        "required": ["project_path"],
        "additionalProperties": False,
    },
)


def _failed(entry: dict[str, Any]) -> bool:
    return (
        entry.get("code") != 0
        or bool(entry.get("timeout_expired"))
        or bool(entry.get("suggestion_application_failed"))
        or entry.get("executed") is False
    )


def _summarize(entry: dict[str, Any], include_output: bool) -> dict[str, Any]:
    """One run, reduced to what tells runs apart; defaults are left out."""
    row: dict[str, Any] = {
        "code": entry.get("code"),
        "time": entry.get("time"),
        "time_source": entry.get("time_source", "wall_clock"),
        "thread_count": entry.get("thread_count"),
        "applied_suggestions": entry.get("applied_suggestions", []),
    }
    if row["time_source"] != "wall_clock" and "wall_clock_time" in entry:
        row["wall_clock_time"] = entry["wall_clock_time"]
    if entry.get("failed_suggestions"):
        row["failed_suggestions"] = entry["failed_suggestions"]
    if entry.get("timeout_expired"):
        row["timeout_expired"] = True
    if isinstance(entry.get("repetitions"), int) and entry["repetitions"] > 1:
        row["repetitions"] = entry["repetitions"]
    if entry.get("label"):
        row["label"] = entry["label"]
    if include_output:
        for stream in ("stdout", "stderr"):
            tail, full_length = tail_of_output(entry.get(stream))
            row[stream] = tail
            if full_length is not None:
                row[f"{stream}_length"] = full_length
    return row


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path = arguments.get("project_path", "")
        config_filter: Optional[str] = arguments.get("config_name")
        script_filter: Optional[str] = arguments.get("script")
        failed_only = bool(arguments.get("failed_only", False))
        include_output = bool(arguments.get("include_output", False))
        results_file = Path(project_path) / ".discopop" / "project" / "execution_results.json"

        recorded: dict[str, Any] = {}
        if results_file.exists() and results_file.is_file():
            with open(results_file, "r") as f:
                recorded = json.load(f)

        execution_results: dict[str, Any] = {}
        num_runs = 0
        num_failed = 0
        for config_name, scripts in recorded.items():
            if config_filter is not None and config_name != config_filter:
                continue
            for script_name, settings in scripts.items():
                if script_filter is not None and script_name != script_filter:
                    continue
                for settings_name, entries in settings.items():
                    for entry in entries if isinstance(entries, list) else [entries]:
                        failed = _failed(entry)
                        num_runs += 1
                        num_failed += failed
                        if failed_only and not failed:
                            continue
                        execution_results.setdefault(config_name, {}).setdefault(script_name, {}).setdefault(
                            settings_name, []
                        ).append(_summarize(entry, include_output))

        result: dict[str, Any] = {
            "status": "success",
            "project_path": project_path,
            "num_runs": num_runs,
            "num_failed": num_failed,
            "execution_results": execution_results,
        }
        if not recorded:
            result["next_step"] = (
                "No runs are recorded yet. gather_data records its compile and profiling runs, "
                "run_auto_tuning the runs of every candidate it measures."
            )
        elif num_failed and not include_output:
            result["next_step"] = (
                f"{num_failed} of the matching runs failed. Call again with failed_only=true and "
                "include_output=true to see their output."
            )
        ctx.log_response("get_execution_results", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error retrieving execution results: {str(e)}"
        logger.error(error_msg)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

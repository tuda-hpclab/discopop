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
from typing import Any

from mcp.types import TextContent, Tool, ToolAnnotations

from mcp_server.tools.helpers import ToolContext

logger = logging.getLogger("discopop-mcp")

TOOL = Tool(
    name="get_execution_results",
    annotations=ToolAnnotations(readOnlyHint=True),
    description=(
        "Retrieve stored execution results from prior DiscoPoP runs. "
        "Call this after gather_data to inspect timing, return codes, "
        "and captured output from previous executions, or to check whether profiling "
        "data has been collected. "
        "\n\n"
        "Results are keyed by configuration name, script name, and settings name. "
        "Each entry contains: code (return code), time (elapsed seconds), "
        "stdout/stderr (captured output), timeout_expired, thread_count, "
        "and applied_suggestions (list of patch IDs applied before the run). "
        "\n\n"
        "Returns an empty execution_results object if no runs have been recorded yet."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the target project root directory.",
            },
        },
        "required": ["project_path"],
        "additionalProperties": False,
    },
)


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path = arguments.get("project_path", "")
        results_file = Path(project_path) / ".discopop" / "project" / "execution_results.json"

        execution_results: dict[str, Any] = {}
        if results_file.exists() and results_file.is_file():
            with open(results_file, "r") as f:
                execution_results = json.load(f)

        result = {
            "status": "success",
            "project_path": project_path,
            "execution_results": execution_results,
        }
        ctx.log_response("get_execution_results", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error retrieving execution results: {str(e)}"
        logger.error(error_msg)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

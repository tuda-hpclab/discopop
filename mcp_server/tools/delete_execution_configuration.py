# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from mcp.types import TextContent, Tool, ToolAnnotations

from mcp_server.tools.helpers import (
    ToolContext,
    invalid_configuration_name,
    setup_next_step,
    unknown_configuration_message,
)

logger = logging.getLogger("discopop-mcp")

TOOL = Tool(
    name="delete_execution_configuration",
    # a second call with the same name finds nothing left to delete and reports so
    annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True, openWorldHint=False),
    description=(
        "Delete a named execution configuration of a DiscoPoP project, i.e. its directory "
        "under .discopop/project/configs/ with its execute.sh, validate.sh and any "
        "per-configuration compile scripts. Use it to drop a configuration that is no longer "
        "wanted, e.g. one with an input too large to profile. To change a configuration's "
        "scripts instead, call create_execution_configuration or set_compile_script again. "
        "\n\n"
        "Analysis results gathered with the configuration (profiling data, suggestions, "
        "hotspots) and its recorded runs in get_execution_results are kept. Cannot be undone."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root.",
            },
            "config_name": {
                "type": "string",
                "description": "Name of the execution configuration to delete.",
            },
        },
        "required": ["project_path", "config_name"],
        "additionalProperties": False,
    },
)


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path = arguments.get("project_path", "")
        config_name = arguments.get("config_name", "")

        configs_dir = Path(project_path) / ".discopop" / "project" / "configs"
        if not configs_dir.exists():
            return ctx.error(
                "DiscoPoP directory not initialized. Run initialize_discopop_directory first.",
                project_path,
                "delete_execution_configuration",
            )

        name_error = invalid_configuration_name(config_name)
        if name_error is not None:
            return ctx.error(name_error, project_path, "delete_execution_configuration")
        config_dir = configs_dir / config_name
        # Only a real directory directly under configs/ is a configuration; anything else (a
        # settings file, a symlink) must never reach rmtree.
        if config_dir.is_symlink() or config_dir.resolve().parent != configs_dir.resolve() or not config_dir.is_dir():
            return ctx.error(
                unknown_configuration_message(configs_dir, config_name),
                project_path,
                "delete_execution_configuration",
            )

        shutil.rmtree(config_dir)
        ctx.log_action(project_path, "delete_execution_configuration", f"Deleted config directory: {config_dir}")

        result: dict[str, Any] = {
            "status": "success",
            "project_path": project_path,
            "config_name": config_name,
            "deleted": str(config_dir),
            "next_step": setup_next_step(configs_dir),
        }
        ctx.log_response("delete_execution_configuration", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error deleting execution configuration: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import logging
import os
from pathlib import Path
from typing import Any

from mcp.types import TextContent, Tool, ToolAnnotations

from discopop_library.ProjectManager.configurations.validation import VALIDATE_SCRIPT_NAME
from discopop_library.ProjectManager.utilities.scriptFiles import write_script_file
from mcp_server.tools.helpers import ToolContext, invalid_configuration_name, setup_next_step

logger = logging.getLogger("discopop-mcp")

TOOL = Tool(
    name="create_execution_configuration",
    annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True, openWorldHint=False),
    description=(
        "Create a named execution configuration for a DiscoPoP project. "
        "Call this after set_compile_script to define how to run the compiled binary. "
        "\n\n"
        "Each configuration is a named subdirectory under .discopop/project/configs/ "
        "containing an execute.sh script. A project can have multiple configurations "
        "representing different execution scenarios (e.g. different input sizes or "
        "argument sets). "
        "\n\n"
        "A configuration compiles with the project's shared compile.sh. If it needs its own "
        "build (e.g. different compile-time parameters), call set_compile_script with its "
        "config_name afterwards. "
        "\n\n"
        "Optionally pass validate_script_body to add a validate.sh, which checks the "
        "program's output separately from the timed execute.sh run: the run counts as "
        "correct only if both exit 0, and validate.sh's duration never enters the measured "
        "runtime. If validation needs a differently compiled binary, set it with "
        "set_compile_script(purpose='validate'). validate.sh is ignored by the profiling "
        "modes (dp/hd), which only run execute.sh. Calling this again with the same "
        "config_name overwrites execute.sh, and validate.sh if given. "
        "\n\n"
        "IMPORTANT — profiling overhead: The instrumented binary records every memory "
        "access at runtime, which incurs significant overhead compared to the original "
        "program. In particularly bad cases overhead can reach up to 100x, although "
        "the average is far below that. If the program accepts input data or a parameter "
        "controlling problem size, always prefer the smallest input that still exercises "
        "the code paths of interest. Configurations with unnecessarily large workloads "
        "may become impractically slow under instrumentation. "
        "\n\n"
        "The execute.sh script is executed from the project root with the same environment "
        "variables as compile.sh: $CC, $CXX, $CFLAGS, $CXXFLAGS, $DP_PROJECT_ROOT_DIR, "
        "$DOT_DISCOPOP, $OMP_NUM_THREADS. The script must exit 0 on success. "
        "\n\n"
        "Examples for script_body:\n"
        "  Minimal:              ./myapp\n"
        "  Small input:          ./myapp --input data/small.txt --iterations 100\n"
        "  Multiple short runs:  ./myapp --mode A && ./myapp --mode B\n"
        "  Piped input:          ./myapp < test_data/small_input.dat\n"
        "\n"
        "After creating at least one configuration, call gather_data to instrument, profile "
        "and analyse the project."
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
                "description": (
                    "Identifier for this configuration. Used as the subdirectory name "
                    "under .discopop/project/configs/. Must not contain path separators. "
                    "Examples: default, small_input, large_input"
                ),
            },
            "script_body": {
                "type": "string",
                "description": (
                    "Full bash script body for running the compiled binary. "
                    "Executed from the project root. Must exit 0 on success. "
                    "A #!/bin/bash shebang is prepended automatically if not present."
                ),
            },
            "validate_script_body": {
                "type": "string",
                "description": (
                    "Optional. If given, writes configs/<config_name>/validate.sh, an untimed "
                    "output check run after a successful execute.sh. Must exit 0 when the output "
                    "is correct and non-zero otherwise. Example: './myapp > out.txt && diff "
                    "out.txt reference.txt'"
                ),
            },
        },
        "required": ["project_path", "config_name", "script_body"],
        "additionalProperties": False,
    },
)


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path = arguments.get("project_path", "")
        config_name = arguments.get("config_name", "")
        script_body = arguments.get("script_body", "")
        validate_script_body = arguments.get("validate_script_body")

        name_error = invalid_configuration_name(config_name)
        if name_error is not None:
            return ctx.error(name_error, project_path, "create_execution_configuration")

        configs_dir = Path(project_path) / ".discopop" / "project" / "configs"
        if not configs_dir.exists():
            return ctx.error(
                "DiscoPoP directory not initialized. Run initialize_discopop_directory first.",
                project_path,
                "create_execution_configuration",
            )

        config_dir = configs_dir / config_name
        # Guard against any remaining traversal after Path resolution.
        if not config_dir.resolve().is_relative_to(configs_dir.resolve()):
            return ctx.error(
                f"Invalid config_name '{config_name}': resolves outside configs directory.",
                project_path,
                "create_execution_configuration",
            )
        config_dir.mkdir(parents=True, exist_ok=True)
        ctx.log_action(project_path, "create_execution_configuration", f"Ensured config directory: {config_dir}")

        execute_sh = config_dir / "execute.sh"
        write_script_file(str(execute_sh), script_body)
        ctx.log_action(
            project_path,
            "create_execution_configuration",
            f"Wrote execute.sh for config '{config_name}' ({len(script_body)} bytes)",
        )

        result: dict[str, Any] = {
            "status": "success",
            "project_path": project_path,
            "config_name": config_name,
            "path": str(execute_sh),
        }

        if validate_script_body:
            validate_sh = str(config_dir / VALIDATE_SCRIPT_NAME)
            write_script_file(validate_sh, validate_script_body)
            ctx.log_action(
                project_path,
                "create_execution_configuration",
                f"Wrote validate.sh for config '{config_name}' ({len(validate_script_body)} bytes)",
            )
            result["validate_script_path"] = validate_sh

        result["next_step"] = setup_next_step(configs_dir)
        ctx.log_response("create_execution_configuration", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error creating execution configuration: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

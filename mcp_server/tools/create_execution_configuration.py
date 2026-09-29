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

from discopop_library.ProjectManager.configurations.compile_script import (
    get_per_config_compile_script_path,
    get_per_config_validation_compile_script_path,
)
from discopop_library.ProjectManager.configurations.validation import VALIDATE_SCRIPT_NAME
from discopop_library.ProjectManager.utilities.scriptFiles import write_script_file
from mcp_server.tools.helpers import ToolContext

logger = logging.getLogger("discopop-mcp")

TOOL = Tool(
    name="create_execution_configuration",
    annotations=ToolAnnotations(idempotentHint=True),
    description=(
        "Create a named execution configuration for a DiscoPoP project. "
        "Call this after set_compile_script to define how to run the compiled binary. "
        "\n\n"
        "Each configuration is a named subdirectory under .discopop/project/configs/ "
        "containing an execute.sh script. A project can have multiple configurations "
        "representing different execution scenarios (e.g. different input sizes or "
        "argument sets). "
        "\n\n"
        "By default a configuration compiles with the project's shared compile.sh. Pass "
        "compile_script_body to also give this configuration its own compile.sh override, "
        "used only for this configuration (e.g. when it needs different compile-time "
        "parameters) — equivalent to calling set_compile_script with this config_name. "
        "\n\n"
        "Optionally pass validate_script_body to add a validate.sh, which checks the "
        "program's output separately from the timed execute.sh run: the run counts as "
        "correct only if both exit 0, and validate.sh's duration never enters the measured "
        "runtime. If validation needs a differently compiled binary, also pass "
        "validation_compile_script_body — that build runs after execute.sh and before "
        "validate.sh. Both are ignored by the profiling modes (dp/hd), which only run "
        "execute.sh. "
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
        "After creating at least one configuration, call instrument_project to compile "
        "with DiscoPoP instrumentation."
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
            "compile_script_body": {
                "type": "string",
                "description": (
                    "Optional. If given, also writes a per-configuration compile.sh override to "
                    "configs/<config_name>/compile.sh, used instead of the shared compile.sh for "
                    "this configuration only. A #!/bin/bash shebang is prepended automatically "
                    "if not present."
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
            "validation_compile_script_body": {
                "type": "string",
                "description": (
                    "Optional. If given, writes configs/<config_name>/compile_validate.sh, a "
                    "separate build for validate.sh — use it only when validation needs a "
                    "differently compiled binary than execute.sh. Requires validate_script_body "
                    "(or an existing validate.sh), since otherwise there is nothing to run "
                    "against that build. Same requirements as compile.sh: use $CC/$CXX and "
                    "$CFLAGS/$CXXFLAGS."
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
        validation_compile_script_body = arguments.get("validation_compile_script_body")

        if not config_name or os.sep in config_name or "/" in config_name or config_name.startswith("."):
            return ctx.error(
                f"Invalid config_name '{config_name}'. Must be a plain name without path separators or leading dots.",
                project_path,
                "create_execution_configuration",
            )

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
        # A validation build without anything to validate would silently do nothing,
        # so reject it up front rather than writing an inert script.
        if validation_compile_script_body and not (
            validate_script_body or (config_dir / VALIDATE_SCRIPT_NAME).exists()
        ):
            return ctx.error(
                "validation_compile_script_body requires a validate.sh: pass validate_script_body "
                "as well, since a compile_validate.sh is ignored for configurations without one.",
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

        compile_script_body = arguments.get("compile_script_body")
        if compile_script_body:
            compile_sh = get_per_config_compile_script_path(str(configs_dir), config_name)
            write_script_file(compile_sh, compile_script_body)
            ctx.log_action(
                project_path,
                "create_execution_configuration",
                f"Wrote compile.sh override for config '{config_name}' ({len(compile_script_body)} bytes)",
            )
            result["compile_script_path"] = compile_sh

        if validate_script_body:
            validate_sh = str(config_dir / VALIDATE_SCRIPT_NAME)
            write_script_file(validate_sh, validate_script_body)
            ctx.log_action(
                project_path,
                "create_execution_configuration",
                f"Wrote validate.sh for config '{config_name}' ({len(validate_script_body)} bytes)",
            )
            result["validate_script_path"] = validate_sh

        if validation_compile_script_body:
            validation_compile_sh = get_per_config_validation_compile_script_path(str(configs_dir), config_name)
            write_script_file(validation_compile_sh, validation_compile_script_body)
            ctx.log_action(
                project_path,
                "create_execution_configuration",
                f"Wrote compile_validate.sh override for config '{config_name}' "
                f"({len(validation_compile_script_body)} bytes)",
            )
            result["validation_compile_script_path"] = validation_compile_sh

        ctx.log_response("create_execution_configuration", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error creating execution configuration: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

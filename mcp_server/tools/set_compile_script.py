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

from discopop_library.ProjectManager.configurations.compile_script import (
    get_per_config_compile_script_path,
    get_per_config_validation_compile_script_path,
    get_shared_compile_script_path,
    get_shared_validation_compile_script_path,
)
from discopop_library.ProjectManager.configurations.validation import VALIDATE_SCRIPT_NAME
from discopop_library.ProjectManager.utilities.scriptFiles import write_script_file
from mcp_server.tools.helpers import ToolContext

logger = logging.getLogger("discopop-mcp")

TOOL = Tool(
    name="set_compile_script",
    annotations=ToolAnnotations(idempotentHint=True),
    description=(
        "Write a compilation script compile.sh for a DiscoPoP project. "
        "Call this after initialize_discopop_directory, once you know how the project is built. "
        "\n\n"
        "The script is executed from the project root with these environment variables available:\n"
        "  $CC, $CXX          — compiler executables (injected from the active settings file)\n"
        "  $CFLAGS, $CXXFLAGS — compiler flags\n"
        "  $DP_PROJECT_ROOT_DIR — absolute path to the project root\n"
        "  $DOT_DISCOPOP      — absolute path to the .discopop directory\n"
        "\n"
        "IMPORTANT: The script body MUST use $CC/$CXX for compilers AND $CFLAGS/$CXXFLAGS "
        "for flags — never hardcode compiler names like g++ or clang++. "
        "The same script is reused for sequential builds, DiscoPoP instrumentation, "
        "hotspot detection, and parallel builds — the compiler and flags are selected "
        "by the settings file, not the script. "
        "The script must exit 0 on success. "
        "\n\n"
        "Examples:\n"
        "  Single C++ file:  $CXX $CXXFLAGS main.cpp -o myapp\n"
        "  Single C file:    $CC $CFLAGS main.c -o myapp\n"
        "  Mixed C/C++:      $CXX $CXXFLAGS src/main.cpp && $CC $CFLAGS src/util.c -o myapp\n"
        '  Make project:     make CC="$CC" CXX="$CXX" CFLAGS="$CFLAGS" CXXFLAGS="$CXXFLAGS"\n'
        "  CMake project:    mkdir -p build && cmake -B build "
        '-DCMAKE_C_COMPILER="$CC" -DCMAKE_CXX_COMPILER="$CXX" '
        '-DCMAKE_C_FLAGS="$CFLAGS" -DCMAKE_CXX_FLAGS="$CXXFLAGS" . && cmake --build build\n'
        "\n"
        "By default this sets the shared compile.sh, used by every execution configuration "
        "that does not define its own override. Pass config_name to instead set a per-"
        "configuration override that only applies to that one configuration (e.g. when a "
        "configuration needs different compile-time parameters). "
        "\n\n"
        "Pass purpose='validate' to set compile_validate.sh instead: the build used by a "
        "configuration's validate.sh when validation needs a differently compiled binary "
        "than the timed execute.sh run. It is compiled after execute.sh and before "
        "validate.sh, so it never affects the measured runtime, and it is ignored for "
        "configurations that have no validate.sh (see create_execution_configuration). "
        "Without it, validate.sh runs against the execute.sh build. "
        "\n\n"
        "After setting the compile script, call create_execution_configuration to define "
        "how to run the compiled binary."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": (
                    "Absolute path to the project root. Must already be initialized "
                    "via initialize_discopop_directory."
                ),
            },
            "script_body": {
                "type": "string",
                "description": (
                    "Full bash script body. Must use $CC/$CXX/$CFLAGS/$CXXFLAGS instead "
                    "of hardcoded compiler names. A #!/bin/bash shebang is "
                    "prepended automatically if not present."
                ),
            },
            "config_name": {
                "type": "string",
                "description": (
                    "Optional. If given, writes a per-configuration override to "
                    "configs/<config_name>/compile.sh instead of the shared script — used only "
                    "for that configuration, which must already exist (see "
                    "create_execution_configuration). Omit to write/replace the shared "
                    "compile.sh used by every configuration without its own override."
                ),
            },
            "purpose": {
                "type": "string",
                "enum": ["execute", "validate"],
                "description": (
                    "Which build this script defines. 'execute' (the default) writes "
                    "compile.sh, the build that execute.sh runs against. 'validate' writes "
                    "compile_validate.sh, an optional separate build for validate.sh. A "
                    "compile_validate.sh takes precedence over a per-configuration compile.sh "
                    "override, i.e. the shared one also applies to configurations that have "
                    "their own compile.sh."
                ),
            },
        },
        "required": ["project_path", "script_body"],
        "additionalProperties": False,
    },
)


def __describe_validation_scope(configs_dir: Path, config_name: Optional[str]) -> dict[str, Any]:
    """Which configurations a compile_validate.sh takes effect for.

    A validation build is only used by configurations that define a validate.sh,
    so reporting both lists makes an inert script obvious to the caller.
    """
    if config_name:
        candidates = [config_name]
    else:
        candidates = sorted(entry.name for entry in configs_dir.iterdir() if entry.is_dir())
    used_by = [name for name in candidates if (configs_dir / name / VALIDATE_SCRIPT_NAME).exists()]
    return {
        "used_by": used_by,
        "ignored_for": [name for name in candidates if name not in used_by],
    }


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path = arguments.get("project_path", "")
        script_body = arguments.get("script_body", "")
        config_name = arguments.get("config_name")
        purpose = arguments.get("purpose", "execute")

        if purpose not in ("execute", "validate"):
            return ctx.error(
                f"Invalid purpose '{purpose}'. Must be 'execute' or 'validate'.",
                project_path,
                "set_compile_script",
            )

        configs_dir = Path(project_path) / ".discopop" / "project" / "configs"
        if not configs_dir.exists():
            return ctx.error("DiscoPoP directory not initialized. Run initialize_discopop_directory first.")

        if config_name:
            if not (configs_dir / config_name).is_dir():
                return ctx.error(
                    f"Execution configuration '{config_name}' does not exist. "
                    "Call create_execution_configuration first.",
                    project_path,
                    "set_compile_script",
                )
            if purpose == "validate":
                compile_sh = Path(get_per_config_validation_compile_script_path(str(configs_dir), config_name))
            else:
                compile_sh = Path(get_per_config_compile_script_path(str(configs_dir), config_name))
        elif purpose == "validate":
            compile_sh = Path(get_shared_validation_compile_script_path(str(configs_dir)))
        else:
            compile_sh = Path(get_shared_compile_script_path(str(configs_dir)))

        write_script_file(str(compile_sh), script_body)
        ctx.log_action(project_path, "set_compile_script", f"Wrote {compile_sh.name} ({len(script_body)} bytes)")

        result: dict[str, Any] = {
            "status": "success",
            "project_path": project_path,
            "path": str(compile_sh),
            "purpose": purpose,
        }
        if config_name:
            result["config_name"] = config_name
        if purpose == "validate":
            result["applies_to"] = __describe_validation_scope(configs_dir, config_name)
        ctx.log_response("set_compile_script", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error writing compile script: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

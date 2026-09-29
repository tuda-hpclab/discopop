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

from discopop_library.ProjectManager.utilities.deriveSettingsFiles import derive_settings_files
from discopop_library.ProjectManager.utilities.reset import reset_project
from mcp_server.tools.helpers import ToolContext

logger = logging.getLogger("discopop-mcp")

TOOL = Tool(
    name="initialize_discopop_directory",
    annotations=ToolAnnotations(idempotentHint=True),
    description=(
        "Set up the DiscoPoP directory structure for a project. Call this as the very "
        "first step before any other DiscoPoP tool. "
        "\n\n"
        "NORMAL MODE (reset=false, the default):\n"
        "If the project is already initialized (.discopop/project/configs/ exists), "
        "this tool returns the current configuration status without modifying any files:\n"
        "  - already_initialized: true\n"
        "  - compile_script_configured: whether compile.sh has been customised\n"
        "  - settings_files: which of the seq/dp/hd/par settings JSON files are present\n"
        "  - configurations: list of named execution configurations with has_execute_sh flag\n"
        "  - num_configurations: total number of execution configurations\n"
        "\n"
        "If the project is not yet initialized, this tool creates:\n"
        "  - .discopop/project/configs/          — configuration directory\n"
        "  - seq_settings.json                   — base sequential build settings (CC, CXX, CFLAGS, CXXFLAGS)\n"
        "  - dp_settings.json                    — instrumentation settings (CC=discopop_cc, CXX=discopop_cxx)\n"
        "  - hd_settings.json                    — hotspot detection settings\n"
        "  - par_settings.json                   — parallel build settings\n"
        "  - compile.sh                          — placeholder that must be replaced via set_compile_script\n"
        "\n"
        "Two further scripts are optional and deliberately not created here: a "
        "compile_validate.sh (shared or per configuration, see set_compile_script) and a "
        "per-configuration validate.sh (see create_execution_configuration). Absent, "
        "correctness is decided by execute.sh's exit code alone.\n"
        "\n"
        "RESET MODE (reset=true):\n"
        "Removes all DiscoPoP analysis artefacts (profiler output, explorer results, "
        "patch files, hotspot data, execution results) while preserving the project "
        "configuration directory (.discopop/project/) so that compile.sh and execution "
        "configurations are kept intact. Use this to force a clean re-run of gather_data "
        "when the pipeline is in a broken or inconsistent state.\n"
        "\n"
        "After initializing, call set_compile_script to describe how to build the "
        "project, then create_execution_configuration to describe how to run it."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": (
                    "Absolute path to the project root directory (the directory containing "
                    "the source files). Example: /home/user/myproject"
                ),
            },
            "reset": {
                "type": "boolean",
                "description": (
                    "When true, delete all DiscoPoP analysis artefacts under .discopop/ "
                    "(profiler output, explorer results, patch files, hotspot data, "
                    "execution results) while keeping the project configuration "
                    "(.discopop/project/). Default: false."
                ),
            },
            "base_cc": {
                "type": "string",
                "description": (
                    "Base C compiler for sequential (non-instrumented) builds. " "Default: clang. Example: gcc"
                ),
            },
            "base_cxx": {
                "type": "string",
                "description": (
                    "Base C++ compiler for sequential (non-instrumented) builds. " "Default: clang++. Example: g++"
                ),
            },
            "cflags": {
                "type": "string",
                "description": (
                    "Initial CFLAGS shared across all build modes. " "Default: empty string. Example: -O2 -std=c11"
                ),
            },
            "cxxflags": {
                "type": "string",
                "description": (
                    "Initial CXXFLAGS shared across all build modes. " "Default: empty string. Example: -O2 -std=c++17"
                ),
            },
        },
        "required": ["project_path"],
        "additionalProperties": False,
    },
)


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path = arguments.get("project_path", "")
        reset: bool = arguments.get("reset", False)
        base_cc = arguments.get("base_cc", "clang")
        base_cxx = arguments.get("base_cxx", "clang++")
        cflags = arguments.get("cflags", "")
        cxxflags = arguments.get("cxxflags", "")

        p = Path(project_path)
        if not p.exists():
            return ctx.error(
                f"project_path does not exist: {project_path}", project_path, "initialize_discopop_directory"
            )

        # === Reset mode ===
        if reset:
            pm_args = ctx.make_pm_args(project_path)
            pm_args.reset = True
            pm_args.reset_execution_results = True
            reset_project(pm_args)
            ctx.log_action(project_path, "initialize_discopop_directory", "Reset: removed analysis artefacts")
            result: dict[str, Any] = {
                "status": "success",
                "project_path": project_path,
                "reset": True,
                "message": (
                    "Analysis artefacts removed (.discopop/profiler, .discopop/explorer, "
                    ".discopop/patch_generator, .discopop/hotspot_detection, execution_results.json). "
                    "Project configuration (.discopop/project/) was preserved."
                ),
            }
            ctx.log_response("initialize_discopop_directory", result)
            return [TextContent(type="text", text=json.dumps(result))]

        configs_dir = p / ".discopop" / "project" / "configs"

        if configs_dir.exists():
            compile_sh = configs_dir / "compile.sh"
            compile_script_configured = False
            if compile_sh.exists():
                content = compile_sh.read_text()
                compile_script_configured = "Use set_compile_script" not in content and "exit 1" not in content

            settings_files = {
                key: (configs_dir / filename).exists()
                for key, filename in [
                    ("seq", "seq_settings.json"),
                    ("dp", "dp_settings.json"),
                    ("hd", "hd_settings.json"),
                    ("par", "par_settings.json"),
                ]
            }

            configurations = [
                {"name": d.name, "has_execute_sh": (d / "execute.sh").exists()}
                for d in sorted(configs_dir.iterdir())
                if d.is_dir()
            ]

            result = {
                "status": "success",
                "project_path": project_path,
                "already_initialized": True,
                "compile_script_configured": compile_script_configured,
                "settings_files": settings_files,
                "configurations": configurations,
                "num_configurations": len(configurations),
            }
            ctx.log_response("initialize_discopop_directory", result)
            return [TextContent(type="text", text=json.dumps(result))]

        configs_dir.mkdir(parents=True, exist_ok=True)
        ctx.log_action(project_path, "initialize_discopop_directory", f"Ensured directory exists: {configs_dir}")

        created: list[str] = []
        skipped: list[str] = []

        seq_settings_path = configs_dir / "seq_settings.json"
        if not seq_settings_path.exists():
            seq_settings_path.write_text(
                json.dumps({"CC": base_cc, "CXX": base_cxx, "CFLAGS": cflags, "CXXFLAGS": cxxflags}, indent=2)
            )
            created.append(str(seq_settings_path.relative_to(p)))
            ctx.log_action(
                project_path,
                "initialize_discopop_directory",
                f"Created seq_settings.json (CC={base_cc}, CXX={base_cxx})",
            )
        else:
            skipped.append(str(seq_settings_path.relative_to(p)))

        derive_settings_files(str(configs_dir), overwrite=False)
        ctx.log_action(
            project_path, "initialize_discopop_directory", "Derived dp/hd/par settings files from seq_settings.json"
        )
        for name in ("dp_settings.json", "hd_settings.json", "par_settings.json"):
            f = configs_dir / name
            if str(f.relative_to(p)) not in skipped:
                if f.exists():
                    created.append(str(f.relative_to(p)))

        compile_sh = configs_dir / "compile.sh"
        if not compile_sh.exists():
            initial_content = (
                "#!/bin/bash\n"
                "# This script is executed from the project root directory.\n"
                "# Use $CC/$CXX/$CFLAGS/$CXXFLAGS — do NOT hardcode compiler names.\n"
                "# Replace this placeholder via the set_compile_script MCP tool.\n"
                "echo 'compile.sh has not been configured yet. Use set_compile_script.'\n"
                "exit 1\n"
            )
            compile_sh.write_text(initial_content)
            compile_sh.chmod(compile_sh.stat().st_mode | 0o111)
            created.append(str(compile_sh.relative_to(p)))
            ctx.log_action(project_path, "initialize_discopop_directory", "Created placeholder compile.sh")
        else:
            skipped.append(str(compile_sh.relative_to(p)))

        result = {
            "status": "success",
            "project_path": project_path,
            "created_files": created,
            "skipped_files": skipped,
        }
        ctx.log_response("initialize_discopop_directory", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error initializing DiscoPoP directory: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

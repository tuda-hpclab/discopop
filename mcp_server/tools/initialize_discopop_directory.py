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

from discopop_library.ProjectManager.utilities.deriveSettingsFiles import derive_settings_files
from discopop_library.ProjectManager.utilities.reset import reset_project
from mcp_server.tools.helpers import (
    COMPILE_SCRIPT_PLACEHOLDER_MARKER,
    ToolContext,
    applicator_failure_details,
    recorded_applied_suggestions,
    run_patch_applicator,
    setup_next_step,
)

logger = logging.getLogger("discopop-mcp")

TOOL = Tool(
    name="initialize_discopop_directory",
    # reset=true deletes every analysis artefact; idempotent nonetheless, since a second
    # call with the same arguments leaves the same state behind.
    annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True, openWorldHint=False),
    description=(
        "Set up the DiscoPoP directory structure for a project. Call this as the very "
        "first step before any other DiscoPoP tool. "
        "\n\n"
        "NORMAL MODE (reset=false, the default):\n"
        "If the project is already initialized, nothing is modified and the result only says "
        "so (already_initialized: true) and names the next setup step; a file missing from an "
        "initialized project is recreated. Use get_project_status to see what is set up and "
        "analysed.\n"
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
        "configurations are kept intact. Applied suggestions are rolled back first. Use this "
        "to force a clean re-run of gather_data when the pipeline is in a broken or "
        "inconsistent state.\n"
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


def _roll_back_applied(project_path: str, ctx: ToolContext) -> tuple[list[str], Optional[str]]:
    """Roll back the applied suggestions; the ids rolled back, and a warning if that failed."""
    applied, _ = recorded_applied_suggestions(project_path)
    if not applied:
        return [], None
    proc, run_error = run_patch_applicator(project_path, ["--clear"])
    # 3: nothing was applied after all; 2 (partly rolled back) leaves patches behind
    if proc is not None and proc.returncode in (0, 3):
        ctx.log_action(project_path, "initialize_discopop_directory", f"Reset: rolled back {applied}")
        return applied, None
    details = run_error if proc is None else applicator_failure_details(proc)[0]
    return [], (
        f"The applied suggestions {applied} could not be rolled back ({details}), and the reset deleted "
        "the record of them. The sources may still contain these patches; revert them by hand, e.g. "
        "with version control, before analysing the project again."
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
            # The reset deletes the applicator's record of what it applied; without it,
            # applied suggestions could no longer be rolled back.
            rolled_back, rollback_warning = _roll_back_applied(project_path, ctx)
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
                "next_step": setup_next_step(p / ".discopop" / "project" / "configs"),
            }
            if rolled_back:
                result["rolled_back_suggestions"] = rolled_back
            if rollback_warning is not None:
                result["warning"] = rollback_warning
            ctx.log_response("initialize_discopop_directory", result)
            return [TextContent(type="text", text=json.dumps(result))]

        configs_dir = p / ".discopop" / "project" / "configs"

        # An initialized project with a file missing (an initialization that was interrupted,
        # a file deleted by hand) falls through to the creation below, which only creates what
        # is missing: answering "already initialized" would leave every tool that needs the
        # file pointing back here.
        expected = ["seq_settings.json", "dp_settings.json", "hd_settings.json", "par_settings.json", "compile.sh"]
        if configs_dir.exists() and all((configs_dir / name).exists() for name in expected):
            result = {
                "status": "success",
                "project_path": project_path,
                "already_initialized": True,
                "next_step": setup_next_step(configs_dir),
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

        derived = [configs_dir / name for name in ("dp_settings.json", "hd_settings.json", "par_settings.json")]
        derived_before = {f for f in derived if f.exists()}
        derive_settings_files(str(configs_dir), overwrite=False)
        ctx.log_action(
            project_path, "initialize_discopop_directory", "Derived dp/hd/par settings files from seq_settings.json"
        )
        for f in derived:
            if f in derived_before:
                skipped.append(str(f.relative_to(p)))
            elif f.exists():
                created.append(str(f.relative_to(p)))

        compile_sh = configs_dir / "compile.sh"
        if not compile_sh.exists():
            initial_content = (
                "#!/bin/bash\n"
                "# This script is executed from the project root directory.\n"
                "# Use $CC/$CXX/$CFLAGS/$CXXFLAGS — do NOT hardcode compiler names.\n"
                "# Replace this placeholder via the set_compile_script MCP tool.\n"
                f"echo '{COMPILE_SCRIPT_PLACEHOLDER_MARKER}. Use set_compile_script.'\n"
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
            "next_step": setup_next_step(configs_dir),
        }
        ctx.log_response("initialize_discopop_directory", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error initializing DiscoPoP directory: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

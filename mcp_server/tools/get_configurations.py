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
    COMPILE_SCRIPT_NAME,
    VALIDATION_COMPILE_SCRIPT_NAME,
    get_shared_compile_script_path,
    get_shared_validation_compile_script_path,
)
from discopop_library.ProjectManager.configurations.validation import VALIDATE_SCRIPT_NAME
from mcp_server.tools.helpers import ToolContext

logger = logging.getLogger("discopop-mcp")


def __read_if_present(path: Path) -> Optional[str]:
    return path.read_text() if path.exists() else None


TOOL = Tool(
    name="get_configurations",
    annotations=ToolAnnotations(readOnlyHint=True),
    description=(
        "Retrieve all execution configurations defined for a DiscoPoP project, "
        "including the content of the shared compile.sh and each configuration's execute.sh. "
        "\n\n"
        "Call this to inspect what build and execution scripts are currently defined for a project, "
        "or to check whether a project has been initialized yet — an empty configurations list and "
        "null compile_script means initialize_discopop_directory has not been run. "
        "\n\n"
        "Returns:\n"
        "  - compile_script: content of .discopop/project/configs/compile.sh, or null if absent\n"
        "  - validation_compile_script: content of the shared compile_validate.sh, or null if "
        "absent (absent is the normal case: validate.sh then uses the compile.sh build)\n"
        "  - settings: contents of seq_settings.json and dp_settings.json, if present\n"
        "  - configurations: list of named configurations, each with its execute.sh content plus\n"
        "    any per-configuration overrides — compile_script_override, validate_script and\n"
        "    validation_compile_script, each null when the configuration does not define it\n"
        "\n"
        "Example output:\n"
        '  {"status":"success","compile_script":"#!/bin/bash\\n$CXX $CXXFLAGS main.cpp -o myapp\\n",'
        '"validation_compile_script":null,'
        '"configurations":[{"name":"default","execute_script":"#!/bin/bash\\n./myapp\\n",'
        '"compile_script_override":null,"validate_script":null,"validation_compile_script":null}]}'
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
        p = Path(project_path)
        configs_dir = p / ".discopop" / "project" / "configs"

        compile_script = __read_if_present(Path(get_shared_compile_script_path(str(configs_dir))))
        validation_compile_script = __read_if_present(Path(get_shared_validation_compile_script_path(str(configs_dir))))

        settings: dict[str, Any] = {}
        for key, filename in [("seq", "seq_settings.json"), ("dp", "dp_settings.json")]:
            settings_file = configs_dir / filename
            if settings_file.exists():
                settings[key] = json.loads(settings_file.read_text())

        configurations = []
        if configs_dir.exists() and configs_dir.is_dir():
            for config_dir in sorted(configs_dir.iterdir()):
                if not config_dir.is_dir():
                    continue
                configurations.append(
                    {
                        "name": config_dir.name,
                        "execute_script": __read_if_present(config_dir / "execute.sh"),
                        "compile_script_override": __read_if_present(config_dir / COMPILE_SCRIPT_NAME),
                        "validate_script": __read_if_present(config_dir / VALIDATE_SCRIPT_NAME),
                        "validation_compile_script": __read_if_present(config_dir / VALIDATION_COMPILE_SCRIPT_NAME),
                    }
                )

        result = {
            "status": "success",
            "project_path": project_path,
            "compile_script": compile_script,
            "validation_compile_script": validation_compile_script,
            "settings": settings,
            "configurations": configurations,
        }
        ctx.log_response("get_configurations", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error retrieving configurations: {str(e)}"
        logger.error(error_msg)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

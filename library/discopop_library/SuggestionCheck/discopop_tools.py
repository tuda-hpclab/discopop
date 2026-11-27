# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""DiscoPoP's own data for the agents: the MCP server, read-only and bound to the project, with only the tools the
prompts describe allowed (design/agent_checked_suggestions.md, §5.2).

The server runs with --tools readonly (nothing that profiles, builds, runs or sets up a project can even be listed),
--project (every call works on the project, whatever path the agent gives) and therefore never forwards to a daemon
the user may run for their own sessions."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

SERVER_NAME = "discopop"
# the tools the prompts describe; the server offers a few more read-only ones, which stay denied
TOOLS = ("get_side_effects", "explain_parallelization")
EXECUTABLE = "discopop_mcp_server"
# seconds the --help of the server may take (it imports the MCP SDK)
PROBE_TIMEOUT = 60


@dataclass(frozen=True)
class DiscoPoPTools:
    # how to start the server, without its arguments
    command: List[str]
    # the project whose .discopop the tools read
    project: str
    env: Dict[str, str] = field(default_factory=dict)

    @property
    def argv(self) -> List[str]:
        return self.command + ["--tools", "readonly", "--project", self.project]

    def claude_arguments(self) -> List[str]:
        """the server as the only MCP server of the agent (with --strict-mcp-config), and its tools allowed"""
        server: Dict[str, Any] = {"type": "stdio", "command": self.argv[0], "args": self.argv[1:]}
        if self.env:
            server["env"] = dict(self.env)
        return [
            "--mcp-config",
            json.dumps({"mcpServers": {SERVER_NAME: server}}),
            "--allowedTools",
            ",".join(claude_tool_name(t) for t in TOOLS),
        ]

    def opencode_config(self) -> Dict[str, Any]:
        """the part of OPENCODE_CONFIG_CONTENT for the server. Not yet verified against a real opencode run."""
        server: Dict[str, Any] = {"type": "local", "command": self.argv, "enabled": True}
        if self.env:
            server["environment"] = dict(self.env)
        # every tool of the server off, then the described ones on
        tools: Dict[str, bool] = {SERVER_NAME + "_*": False}
        tools.update({SERVER_NAME + "_" + t: True for t in TOOLS})
        return {"mcp": {SERVER_NAME: server}, "tools": tools}


def claude_tool_name(tool: str) -> str:
    return "mcp__" + SERVER_NAME + "__" + tool


def is_discopop_tool(name: str) -> bool:
    """whether a tool call of the agent went to the server (claude: mcp__discopop__x, opencode: discopop_x)"""
    return name.startswith("mcp__" + SERVER_NAME + "__") or name.startswith(SERVER_NAME + "_")


def supports_binding(command: List[str], env: Optional[Dict[str, str]] = None) -> bool:
    """whether the server started by command knows --tools readonly and --project (an older version exits on them,
    silently for the agent): its --help names both. A server that cannot be run, or does not answer in time, does
    not."""
    try:
        completed = subprocess.run(
            command + ["--help"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
            env={**os.environ, **env} if env else None,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0 and "readonly" in completed.stdout and "--project" in completed.stdout


def locate(project: str) -> Optional[DiscoPoPTools]:
    """the server, if it is installed or importable from this Python and supports being bound read-only to a
    project; None otherwise"""
    project = os.path.abspath(project)
    executable = shutil.which(EXECUTABLE)
    if executable and supports_binding([executable]):
        return DiscoPoPTools([executable], project)
    if importlib.util.find_spec("mcp_server") is not None and importlib.util.find_spec("mcp_server.server"):
        # e.g. run from a source checkout: the same interpreter, with the same module path
        env = {"PYTHONPATH": os.environ["PYTHONPATH"]} if os.environ.get("PYTHONPATH") else {}
        command = [sys.executable, "-m", "mcp_server.server"]
        if supports_binding(command, env):
            return DiscoPoPTools(command, project, env)
    return None

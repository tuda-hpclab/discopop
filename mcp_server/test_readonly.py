# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The read-only tool set and a server bound to one project, as the agents of discopop_blocker_resolution use them."""

import contextlib
import io
import json
import os
import tempfile
import unittest
import unittest.mock
from types import SimpleNamespace
from typing import Any, Dict, List

import anyio
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent, Tool, ToolAnnotations

from mcp_server import server as server_module
from mcp_server.server import TOOL_SETS, DiscoPopMCPServer, bound_schema
from mcp_server.tools.helpers import ToolContext

_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {"project_path": {"type": "string"}, "function": {"type": "string"}},
    "required": ["project_path", "function"],
    "additionalProperties": False,
}


class TestReadOnlyToolSet(unittest.TestCase):
    def test_only_tools_which_change_nothing(self) -> None:
        names = {mod.TOOL.name for mod in TOOL_SETS["readonly"]}
        self.assertIn("get_side_effects", names)
        self.assertIn("explain_parallelization", names)
        for changing in (
            "gather_data",
            "run_configuration",
            "initialize_discopop_directory",
            "set_compile_script",
            "create_execution_configuration",
            "delete_execution_configuration",
        ):
            self.assertNotIn(changing, names)
        for mod in TOOL_SETS["readonly"]:
            assert mod.TOOL.annotations is not None
            self.assertIs(mod.TOOL.annotations.readOnlyHint, True)


class TestBoundServer(unittest.TestCase):
    def test_the_schema_without_project_path(self) -> None:
        bound = bound_schema(_SCHEMA)
        self.assertEqual(list(bound["properties"]), ["function"])
        self.assertEqual(bound["required"], ["function"])
        # the original is unchanged
        self.assertIn("project_path", _SCHEMA["properties"])

    def test_every_call_works_on_the_bound_project(self) -> None:
        seen: List[Dict[str, Any]] = []

        def handle(arguments: Dict[str, Any], ctx: ToolContext) -> List[TextContent]:
            seen.append(dict(arguments))
            return [TextContent(type="text", text=json.dumps({"status": "success"}))]

        tool = SimpleNamespace(
            TOOL=Tool(name="t", inputSchema=_SCHEMA, annotations=ToolAnnotations(readOnlyHint=True)), handle=handle
        )
        with unittest.mock.patch.dict(server_module.TOOL_SETS, {"test": [tool]}):
            server = DiscoPopMCPServer(tool_set="test", project="/the/project")

        async def scenario() -> None:
            async with create_connected_server_and_client_session(server.server) as client:
                [listed] = (await client.list_tools()).tools
                self.assertNotIn("project_path", listed.inputSchema["properties"])
                self.assertFalse((await client.call_tool("t", {"function": "f"})).isError)
                # a project_path of the caller does not count
                self.assertFalse((await client.call_tool("t", {"function": "f", "project_path": "/elsewhere"})).isError)

        anyio.run(scenario)
        self.assertEqual([a["project_path"] for a in seen], ["/the/project", "/the/project"])

    def test_a_bound_or_read_only_server_writes_no_log_into_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            os.mkdir(os.path.join(project, ".discopop"))
            log = os.path.join(project, ".discopop", "mcp_server", "log.txt")
            for server in (
                DiscoPopMCPServer(tool_set="readonly", project=project),
                DiscoPopMCPServer(tool_set="all", project=project),
                DiscoPopMCPServer(tool_set="readonly"),
            ):
                ctx = server._ctx
                ctx.log_call("get_side_effects", {"project_path": project, "function": "f"})
                ctx.log_action(project, "get_side_effects", "described f")
                ctx.error("failed", project, "get_side_effects")
                self.assertFalse(os.path.exists(log))
            # an unbound server with every tool still logs
            DiscoPopMCPServer(tool_set="all")._ctx.log_action(project, "gather_data", "profiled")
            self.assertTrue(os.path.exists(log))

    def test_project_cannot_be_combined_with_daemon(self) -> None:
        argv = ["discopop_mcp_server", "--daemon", "--project", "/p"]
        with unittest.mock.patch("sys.argv", argv), unittest.mock.patch.object(server_module, "_run_daemon") as daemon:
            with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()) as stderr:
                server_module.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--project cannot be combined with --daemon", stderr.getvalue())
        daemon.assert_not_called()


if __name__ == "__main__":
    unittest.main()

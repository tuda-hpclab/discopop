# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The MCP server as a client sees it: a stdio subprocess spoken to over MCP.

No profiler is needed: these tests cover the protocol surface and the project setup
tools, which only write scripts and settings files.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from test.end_to_end.mcp_server.mcp_test_utils import mcp_session

SETUP_TOOLS = {
    "initialize_discopop_directory",
    "set_compile_script",
    "create_execution_configuration",
    "delete_execution_configuration",
}
ANALYSIS_TOOLS = {
    "get_project_status",
    "get_configurations",
    "get_execution_results",
    "get_data_dependencies",
    "get_side_effects",
    "gather_data",
    "get_hotspots",
    "get_parallelization_patches",
    "explain_parallelization",
    "run_auto_tuning",
    "manage_patches",
}


class TestStdioProtocol(unittest.IsolatedAsyncioTestCase):
    async def test_initialize_handshake_and_instructions(self) -> None:
        async with mcp_session() as server:
            init = server.init
            self.assertEqual(init.serverInfo.name, "discopop_mcp_server")
            self.assertIsNotNone(init.capabilities.tools)
            instructions = init.instructions or ""
            self.assertIn("DiscoPoP", instructions)
            for step in ("initialize_discopop_directory", "set_compile_script", "gather_data", "run_auto_tuning"):
                self.assertIn(step, instructions)
            # Claude Code cuts instructions off after 2048 characters
            self.assertLessEqual(len(instructions), 2048)

    async def test_list_tools(self) -> None:
        async with mcp_session() as server:
            tools = (await server.session.list_tools()).tools
            names = {tool.name for tool in tools}
            self.assertEqual(names, SETUP_TOOLS | ANALYSIS_TOOLS)
            for tool in tools:
                with self.subTest(tool=tool.name):
                    schema = tool.inputSchema
                    self.assertEqual(schema.get("type"), "object")
                    self.assertIn("project_path", schema.get("properties", {}))
                    self.assertIn("project_path", schema.get("required", []))
                    self.assertFalse(schema.get("additionalProperties", True))
                    self.assertTrue(tool.description)
                    self.assertIsNotNone(tool.annotations)
            by_name = {tool.name: tool for tool in tools}
            self.assertEqual(set(by_name["gather_data"].inputSchema["required"]), {"project_path", "config_name"})
            assert by_name["get_project_status"].annotations is not None
            self.assertTrue(by_name["get_project_status"].annotations.readOnlyHint)

    async def test_analysis_tool_set_hides_setup_tools(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            async with mcp_session("--tools", "analysis") as server:
                names = {tool.name for tool in (await server.session.list_tools()).tools}
                self.assertEqual(names, ANALYSIS_TOOLS)
                # not offered means not callable either, with a message that says why
                result = await server.call("initialize_discopop_directory", {"project_path": project})
                self.assertTrue(result.is_error)
                self.assertIn("not available in the 'analysis' tool set", result.text)
                self.assertFalse((Path(project) / ".discopop").exists())

    async def test_unknown_tool(self) -> None:
        async with mcp_session() as server:
            result = await server.call("no_such_tool", {})
            self.assertTrue(result.is_error)
            self.assertIn("Unknown tool: no_such_tool", result.text)


class TestArgumentValidation(unittest.IsolatedAsyncioTestCase):
    async def test_validation_errors_are_tool_errors(self) -> None:
        with tempfile.TemporaryDirectory() as project:
            async with mcp_session() as server:
                with self.subTest("missing required argument"):
                    result = await server.call("set_compile_script", {"project_path": project})
                    self.assertTrue(result.is_error)
                    self.assertIn("set_compile_script", result.text)
                    self.assertIn("script_body", result.text)
                with self.subTest("unknown argument"):
                    result = await server.call("get_configurations", {"project_path": project, "bogus": 1})
                    self.assertTrue(result.is_error)
                    self.assertIn("bogus", result.text)
                with self.subTest("wrong type"):
                    result = await server.call(
                        "gather_data", {"project_path": project, "config_name": "c", "force": [1]}
                    )
                    self.assertTrue(result.is_error)
                    self.assertIn("'force'", result.text)
                    self.assertIn("expected boolean", result.text)
                with self.subTest("enum violation"):
                    result = await server.call(
                        "set_compile_script", {"project_path": project, "script_body": "true", "purpose": "deploy"}
                    )
                    self.assertTrue(result.is_error)
                    self.assertIn("purpose", result.text)
                # nothing of the above may have touched the project
                self.assertFalse((Path(project) / ".discopop").exists())

    async def test_lenient_coercion(self) -> None:
        """A string "true" for a boolean is coerced rather than refused."""
        with tempfile.TemporaryDirectory() as project:
            async with mcp_session() as server:
                result = await server.call("initialize_discopop_directory", {"project_path": project, "reset": "false"})
                self.assertFalse(result.is_error, result)
                self.assertEqual(result.data["status"], "success")


class TestSetupWorkflow(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.project = tempfile.mkdtemp(prefix="dp_mcp_setup_")
        self.addCleanup(shutil.rmtree, self.project, True)

    async def test_setup_workflow(self) -> None:
        project = self.project
        configs = Path(project) / ".discopop" / "project" / "configs"
        async with mcp_session() as server:
            # --- before initialization
            result = await server.call("get_project_status", {"project_path": project})
            self.assertFalse(result.is_error, result)
            self.assertFalse(result.data["initialized"])
            self.assertIn("initialize_discopop_directory", result.data["next_step"])

            result = await server.call("get_configurations", {"project_path": project})
            self.assertFalse(result.is_error, result)
            self.assertIsNone(result.data["compile_script"])
            self.assertEqual(result.data["configurations"], [])

            for name, args in (
                ("set_compile_script", {"script_body": "$CXX $CXXFLAGS code.cpp -o prog"}),
                ("create_execution_configuration", {"config_name": "small", "script_body": "./prog"}),
                ("delete_execution_configuration", {"config_name": "small"}),
            ):
                with self.subTest(f"{name} on an uninitialized project"):
                    result = await server.call(name, {"project_path": project, **args})
                    self.assertTrue(result.is_error, result)
                    self.assertEqual(result.data.get("status"), "error")
                    self.assertIn("initialize_discopop_directory", result.data["message"])
            # (.discopop itself may exist: every call appends to .discopop/mcp_server/log.txt)
            self.assertFalse((Path(project) / ".discopop" / "project").exists())

            # --- initialize
            result = await server.call(
                "initialize_discopop_directory",
                {"project_path": project, "base_cc": "gcc", "base_cxx": "g++", "cxxflags": "-O2"},
            )
            self.assertFalse(result.is_error, result)
            self.assertEqual(result.data["status"], "success")
            created = {Path(f).name for f in result.data["created_files"]}
            self.assertEqual(
                created,
                {"seq_settings.json", "dp_settings.json", "hd_settings.json", "par_settings.json", "compile.sh"},
            )
            self.assertIn("set_compile_script", result.data["next_step"])

            result = await server.call("initialize_discopop_directory", {"project_path": project})
            self.assertFalse(result.is_error, result)
            self.assertTrue(result.data["already_initialized"])

            result = await server.call("get_project_status", {"project_path": project})
            self.assertTrue(result.data["initialized"])
            self.assertFalse(result.data["compile_script_configured"])
            self.assertEqual(result.data["configurations"], [])

            # --- compile script
            body = "$CXX $CXXFLAGS code.cpp -o prog\n"
            result = await server.call("set_compile_script", {"project_path": project, "script_body": body})
            self.assertFalse(result.is_error, result)
            self.assertEqual(result.data["purpose"], "execute")
            self.assertEqual(Path(result.data["path"]), configs / "compile.sh")
            self.assertIn("create_execution_configuration", result.data["next_step"])

            # --- configurations
            for name, script in (("small", "./prog 10\n"), ("large", "./prog 1000\n")):
                result = await server.call(
                    "create_execution_configuration",
                    {"project_path": project, "config_name": name, "script_body": script},
                )
                self.assertFalse(result.is_error, result)
                self.assertEqual(result.data["config_name"], name)
                self.assertTrue((configs / name / "execute.sh").is_file())
            self.assertIn("gather_data", result.data["next_step"])

            result = await server.call(
                "create_execution_configuration",
                {
                    "project_path": project,
                    "config_name": "checked",
                    "script_body": "./prog > out.txt\n",
                    "validate_script_body": "grep -q ok out.txt\n",
                },
            )
            self.assertFalse(result.is_error, result)
            self.assertTrue(Path(result.data["validate_script_path"]).is_file())

            result = await server.call(
                "set_compile_script",
                {
                    "project_path": project,
                    "script_body": "$CXX $CXXFLAGS -DCHECK code.cpp -o prog",
                    "purpose": "validate",
                },
            )
            self.assertFalse(result.is_error, result)
            self.assertEqual(result.data["applies_to"]["used_by"], ["checked"])
            self.assertEqual(set(result.data["applies_to"]["ignored_for"]), {"large", "small"})

            result = await server.call(
                "set_compile_script",
                {"project_path": project, "script_body": "$CXX $CXXFLAGS -O0 code.cpp -o prog", "config_name": "large"},
            )
            self.assertFalse(result.is_error, result)
            self.assertEqual(result.data["config_name"], "large")

            result = await server.call("get_configurations", {"project_path": project})
            self.assertFalse(result.is_error, result)
            data = result.data
            self.assertIn("$CXX $CXXFLAGS code.cpp -o prog", data["compile_script"])
            self.assertIn("-DCHECK", data["validation_compile_script"])
            self.assertEqual(data["settings"]["seq"]["CXX"], "g++")
            self.assertEqual(data["settings"]["seq"]["CXXFLAGS"], "-O2")
            self.assertEqual(data["settings"]["dp"]["CXX"], "discopop_cxx")
            by_name = {c["name"]: c for c in data["configurations"]}
            self.assertEqual(set(by_name), {"small", "large", "checked"})
            self.assertIn("./prog 10", by_name["small"]["execute_script"])
            self.assertIsNone(by_name["small"]["compile_script_override"])
            self.assertIn("-O0", by_name["large"]["compile_script_override"])
            self.assertIn("grep -q ok", by_name["checked"]["validate_script"])
            self.assertNotIn("next_step", data)  # the setup is complete

            result = await server.call("get_project_status", {"project_path": project})
            self.assertFalse(result.is_error, result)
            self.assertTrue(result.data["compile_script_configured"])
            self.assertEqual(set(result.data["configurations"]), {"small", "large", "checked"})
            self.assertEqual(result.data["pipeline"]["profiling"], {"done": False})
            self.assertIn("gather_data", result.data["next_step"])

            # --- error paths: unknown and invalid configuration names
            result = await server.call(
                "delete_execution_configuration", {"project_path": project, "config_name": "nope"}
            )
            self.assertTrue(result.is_error, result)
            self.assertIn("Configuration 'nope' not found", result.data["message"])
            self.assertIn("small", result.data["message"])  # the defined names are listed

            result = await server.call(
                "set_compile_script", {"project_path": project, "script_body": "true", "config_name": "nope"}
            )
            self.assertTrue(result.is_error, result)
            self.assertIn("not found", result.data["message"])

            result = await server.call("gather_data", {"project_path": project, "config_name": "nope"})
            self.assertTrue(result.is_error, result)
            self.assertIn("Configuration 'nope' not found", result.text)

            outside = Path(project) / ".discopop" / "project" / "x"
            for tool, args in (
                ("create_execution_configuration", {"config_name": "../x", "script_body": "true"}),
                ("delete_execution_configuration", {"config_name": "../configs"}),
                ("delete_execution_configuration", {"config_name": ".."}),
                ("set_compile_script", {"config_name": "../x", "script_body": "true"}),
                ("gather_data", {"config_name": "../x"}),
                ("run_auto_tuning", {"config_name": "/tmp"}),
            ):
                with self.subTest(f"{tool} with config_name {args['config_name']!r}"):
                    result = await server.call(tool, {"project_path": project, **args})
                    self.assertTrue(result.is_error, result)
                    self.assertIn("Invalid config_name", result.data["message"])
            self.assertFalse(outside.exists())
            self.assertTrue(configs.is_dir())

            # --- delete
            result = await server.call(
                "delete_execution_configuration", {"project_path": project, "config_name": "large"}
            )
            self.assertFalse(result.is_error, result)
            self.assertFalse((configs / "large").exists())
            result = await server.call(
                "delete_execution_configuration", {"project_path": project, "config_name": "large"}
            )
            self.assertTrue(result.is_error, result)
            self.assertIn("not found", result.data["message"])

            result = await server.call("get_configurations", {"project_path": project})
            self.assertEqual({c["name"] for c in result.data["configurations"]}, {"small", "checked"})

            # --- tools that need analysis results report so instead of failing obscurely
            before_analysis: list[tuple[str, dict[str, Any]]] = [
                ("get_parallelization_patches", {}),
                ("manage_patches", {"action": "list"}),
                ("explain_parallelization", {"file_path": str(Path(project) / "code.cpp"), "start_line": 1}),
                ("get_side_effects", {"function": "main"}),
            ]
            for tool, extra in before_analysis:
                with self.subTest(f"{tool} before gather_data"):
                    result = await server.call(tool, {"project_path": project, **extra})
                    self.assertTrue(result.is_error, result)
                    self.assertIn("gather_data", result.data["message"])

            # --- reset keeps the configuration
            result = await server.call("initialize_discopop_directory", {"project_path": project, "reset": True})
            self.assertFalse(result.is_error, result)
            self.assertTrue(result.data["reset"])
            self.assertTrue((configs / "small" / "execute.sh").is_file())

    # The call log is written before the handler runs; it must not create the project_path
    # it logs for, or a mistyped path would be created and then initialized.
    async def test_nonexistent_project_path(self) -> None:
        missing = str(Path(self.project) / "does" / "not" / "exist")
        async with mcp_session() as server:
            result = await server.call("initialize_discopop_directory", {"project_path": missing})
            self.assertTrue(result.is_error, result)
            self.assertIn("does not exist", result.data["message"])
            result = await server.call("get_project_status", {"project_path": missing})
            self.assertTrue(result.is_error, result)
            self.assertIn("not a directory", result.data["message"])
            self.assertFalse(Path(missing).exists())


if __name__ == "__main__":
    unittest.main()

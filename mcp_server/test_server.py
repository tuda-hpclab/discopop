#
# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

#!/usr/bin/env python3
"""
Test suite for the DiscoPoP MCP Server
"""

import json
import logging
import re
import unittest
from unittest.mock import patch

from mcp_server.server import (
    _ALL_TOOLS,
    _SERVER_INSTRUCTIONS,
    TOOL_SETS,
    DiscoPopMCPServer,
    unavailable_tool_message,
)
from mcp_server.tools import get_configurations, get_execution_results


class TestDiscoPopMCPServer(unittest.TestCase):
    def setUp(self) -> None:
        self.server = DiscoPopMCPServer(debug=True)

    def test_server_initialization(self) -> None:
        """Test that server initializes correctly"""
        self.assertIsNotNone(self.server.server)
        self.assertTrue(self.server.debug)

    def test_logging_call_info(self) -> None:
        """Test that call logging works"""
        with patch("logging.Logger.info") as mock_info:
            self.server._ctx.log_call("test_tool", {"arg": "value"})
            # Just verify the method doesn't raise

    def test_tool_registration(self) -> None:
        """Test that tools are properly registered"""
        tools = self.server.server.list_tools()
        # Should be registered but tools list is from the handler
        # Just verify no errors occur
        self.assertIsNotNone(tools)

    def test_get_configurations_handler(self) -> None:
        """Test get_configurations tool"""
        result = get_configurations.handle({"project_path": "/test/project"}, self.server._ctx)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        text_content = result[0].text
        data = json.loads(text_content)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["project_path"], "/test/project")
        self.assertIn("configurations", data)

    def test_get_execution_results_handler(self) -> None:
        """Test get_execution_results tool"""
        result = get_execution_results.handle({"project_path": "/test/project"}, self.server._ctx)
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        text_content = result[0].text
        data = json.loads(text_content)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["project_path"], "/test/project")
        self.assertIn("execution_results", data)
        self.assertIn("gather_data", data["next_step"])


class TestToolSets(unittest.TestCase):
    """The --tools selection: what a client is offered, and what it may call."""

    _SETUP_TOOL_NAMES = {
        "initialize_discopop_directory",
        "set_compile_script",
        "create_execution_configuration",
        "delete_execution_configuration",
    }

    def __names(self, tool_set: str) -> set[str]:
        return {mod.TOOL.name for mod in TOOL_SETS[tool_set]}

    def test_the_default_set_offers_every_tool(self) -> None:
        self.assertTrue(self._SETUP_TOOL_NAMES <= self.__names("all"))
        self.assertEqual(DiscoPopMCPServer().tool_set, "all")

    def test_the_analysis_set_leaves_out_the_project_setup_tools(self) -> None:
        names = self.__names("analysis")
        self.assertFalse(names & self._SETUP_TOOL_NAMES)
        # everything the analysis route needs is still there
        for expected in ("gather_data", "get_parallelization_patches", "run_auto_tuning", "manage_patches"):
            self.assertIn(expected, names)

    def test_a_hidden_tool_is_not_dispatchable_and_says_why(self) -> None:
        server = DiscoPopMCPServer(tool_set="analysis")
        self.assertNotIn("initialize_discopop_directory", {mod.TOOL.name for mod in server._tools})
        message = unavailable_tool_message("initialize_discopop_directory", "analysis")
        self.assertIn("not available in the 'analysis' tool set", message)

    def test_an_unknown_name_is_still_an_unknown_tool(self) -> None:
        self.assertEqual(unavailable_tool_message("no_such_tool", "analysis"), "Unknown tool: no_such_tool")


class TestToolDefinitions(unittest.TestCase):
    """What every tool definition promises a client, checked across all tools at once."""

    # Executables a description may name in call syntax although they are not tools.
    _NON_TOOL_NAMES = {"discopop_patch_applicator"}

    def test_every_tool_spells_out_its_annotations(self) -> None:
        # MCP defaults an absent hint to the cautious reading -- destructive and
        # open-world -- so leaving one out is a claim as well, and for openWorldHint
        # a wrong one: no tool here reaches beyond the local project.
        for mod in _ALL_TOOLS:
            with self.subTest(tool=mod.TOOL.name):
                annotations = mod.TOOL.annotations
                self.assertIsNotNone(annotations)
                assert annotations is not None
                self.assertIs(annotations.openWorldHint, False)
                if not annotations.readOnlyHint:
                    self.assertIsNotNone(annotations.destructiveHint)
                    self.assertIsNotNone(annotations.idempotentHint)

    def test_the_server_instructions_fit_before_the_client_cuts_them_off(self) -> None:
        # Claude Code shows only the first 2048 characters; whatever follows is never
        # read, which is how the reset=true recovery hint used to go unseen.
        self.assertLessEqual(len(_SERVER_INSTRUCTIONS), 2048)

    def test_the_server_instructions_say_when_to_use_it_before_how(self) -> None:
        # Whether the server fits the task decides whether any of the rest matters,
        # so it leads; the usage rules come last.
        when = _SERVER_INSTRUCTIONS.index("Use it when")
        when_not = _SERVER_INSTRUCTIONS.index("Not suitable")
        workflow = _SERVER_INSTRUCTIONS.index("Workflow:")
        rules = _SERVER_INSTRUCTIONS.index("Rules:")
        self.assertLess(when, 600)
        self.assertLess(when, when_not)
        self.assertLess(when_not, workflow)
        self.assertLess(workflow, rules)

    def test_descriptions_only_point_at_tools_that_exist(self) -> None:
        # "call instrument_project" outlived the tool it named; a caller told to use
        # a tool that is not there concludes the step cannot be done.
        names = {mod.TOOL.name for mod in _ALL_TOOLS}
        reference = re.compile(r"\b(?:call|run|use|via|re-run)\s+([a-z]+(?:_[a-z]+)+)\b|\b([a-z]+(?:_[a-z]+)+)\(")
        texts = [("server instructions", _SERVER_INSTRUCTIONS)] + [
            (mod.TOOL.name, json.dumps(mod.TOOL.model_dump())) for mod in _ALL_TOOLS
        ]
        for source, text in texts:
            for groups in reference.findall(text):
                referenced = groups[0] or groups[1]
                with self.subTest(source=source, referenced=referenced):
                    self.assertIn(referenced, names | self._NON_TOOL_NAMES)


class TestServerIntegration(unittest.TestCase):
    """Integration tests for the MCP Server"""

    def test_debug_mode(self) -> None:
        """Test that debug mode sets correct logging level"""
        server = DiscoPopMCPServer(debug=True)
        self.assertTrue(server.debug)

        server_no_debug = DiscoPopMCPServer(debug=False)
        self.assertFalse(server_no_debug.debug)


if __name__ == "__main__":
    unittest.main()

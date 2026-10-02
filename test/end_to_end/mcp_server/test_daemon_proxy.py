# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The stdio proxy forwarding to a separately started ``--daemon``."""

import shutil
import tempfile
import unittest
from pathlib import Path

from test.end_to_end.mcp_server.mcp_test_utils import Daemon, free_port, mcp_session, wait_until


class TestDaemonProxy(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.project = tempfile.mkdtemp(prefix="dp_mcp_daemon_")
        self.addCleanup(shutil.rmtree, self.project, True)
        self.daemon = Daemon(free_port())
        # registered right away, so the daemon is stopped whatever happens below
        self.addCleanup(self.daemon.stop)
        if not self.daemon.wait_listening(timeout=60):
            self.fail(f"The daemon did not start listening on port {self.daemon.port}:\n{self.daemon.output()}")

    async def test_calls_are_forwarded_to_the_daemon(self) -> None:
        async with mcp_session(daemon_port=self.daemon.port) as server:
            # tools/list is answered by the proxy itself
            names = {tool.name for tool in (await server.session.list_tools()).tools}
            self.assertIn("initialize_discopop_directory", names)

            result = await server.call("initialize_discopop_directory", {"project_path": self.project})
            self.assertFalse(result.is_error, result)
            self.assertEqual(result.data["status"], "success")
            self.assertTrue((Path(self.project) / ".discopop" / "project" / "configs" / "compile.sh").is_file())

            # an error result keeps its payload across the hop (its isError flag: see below)
            result = await server.call(
                "delete_execution_configuration", {"project_path": self.project, "config_name": "nope"}
            )
            self.assertEqual(result.data.get("status"), "error", result)
            self.assertIn("Configuration 'nope' not found", result.text)

            # the calls ran in the daemon, not inline in the proxy
            self.assertTrue(
                wait_until(lambda: "Completed: initialize_discopop_directory" in self.daemon.output(), timeout=10),
                self.daemon.output(),
            )
            self.assertIn("Connected to DiscoPoP MCP daemon", server.stderr())
            self.assertNotIn("Incoming call: initialize_discopop_directory", server.stderr())

    # A tool error the inline path reports with isError=true must not reach the client as a
    # successful call when the daemon ran it.
    async def test_tool_error_keeps_is_error_through_the_daemon(self) -> None:
        async with mcp_session(daemon_port=self.daemon.port) as server:
            result = await server.call(
                "delete_execution_configuration", {"project_path": self.project, "config_name": "nope"}
            )
            self.assertEqual(result.data.get("status"), "error", result)
            self.assertTrue(result.is_error, result)

    async def test_proxy_validates_before_forwarding(self) -> None:
        async with mcp_session(daemon_port=self.daemon.port) as server:
            result = await server.call("set_compile_script", {"project_path": self.project})
            self.assertTrue(result.is_error, result)
            self.assertIn("script_body", result.text)
        self.assertNotIn("set_compile_script", self.daemon.output())


if __name__ == "__main__":
    unittest.main()

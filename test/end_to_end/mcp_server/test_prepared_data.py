# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Data prepared without the MCP server is reused by gather_data.

The project manager's command line, the hotspot analyzer and the explorer write the same analysis record
as gather_data, so a project whose analysis was prepared with them needs no second profiling run: every
step of gather_data is skipped. Two configurations with a compile script of their own each are profiled,
as in benchmark suites, where the record has to accumulate them rather than restart on every build.
"""

import shutil
import subprocess
import sys
import unittest
from pathlib import Path

from test.end_to_end.mcp_server.mcp_test_utils import find_discopop_tool, mcp_session, server_env
from test.end_to_end.mcp_server.test_workflows import (
    COMPILE_SCRIPT,
    gather_data,
    make_project,
    requires_profiler,
    set_up_project,
)

CONFIGS = ("small", "tiny")
TOOL_TIMEOUT = 300


@requires_profiler
class TestPreparedData(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.project = make_project("dp_mcp_prepared_")
        self.addCleanup(shutil.rmtree, self.project, True)
        self.dot = Path(self.project) / ".discopop"

    def run_tool(self, command: list[str], cwd: Path) -> None:
        proc = subprocess.run(command, cwd=cwd, env=server_env(), capture_output=True, text=True, timeout=TOOL_TIMEOUT)
        self.assertEqual(proc.returncode, 0, f"{command} failed:\n{proc.stdout}\n{proc.stderr}")

    def tool(self, name: str) -> str:
        path = find_discopop_tool(name)
        assert path is not None, name
        return path

    def prepare_with_the_command_line(self) -> None:
        manager = [sys.executable, "-m", "discopop_library.ProjectManager"]
        hd = ",".join(f"{c}:hd" for c in CONFIGS)
        self.run_tool(manager + ["-x", hd, "--inplace"], Path(self.project))
        self.run_tool([self.tool("discopop_hotspot_analyzer")], self.dot)
        self.run_tool(manager + ["-x", "small:dp", "--inplace"], Path(self.project))
        self.run_tool([self.tool("discopop_explorer")], self.dot)

    async def test_gather_data_skips_every_step_of_prepared_data(self) -> None:
        async with mcp_session() as server:
            await set_up_project(server, self, self.project, "./prog\n")
            result = await server.call(
                "create_execution_configuration",
                {"project_path": self.project, "config_name": "tiny", "script_body": "./prog\n"},
            )
            self.assertFalse(result.is_error, result)
            # a compile script of its own, as benchmark configurations commonly have
            tiny_compile = self.dot / "project" / "configs" / "tiny" / "compile.sh"
            tiny_compile.write_text("#!/bin/bash\n" + COMPILE_SCRIPT)
            tiny_compile.chmod(0o755)

            self.prepare_with_the_command_line()

            result = await server.call("get_project_status", {"project_path": self.project})
            self.assertFalse(result.is_error, result)
            for step, state in result.data["pipeline"].items():
                self.assertFalse(state.get("stale"), (step, state))
                self.assertEqual(state.get("basis"), "fingerprint", (step, state))

            result = await gather_data(server, self.project, hotspot_config_names=list(CONFIGS))
            self.assertFalse(result.is_error, result)
            steps = result.data["steps"]
            for step in ("hotspot_instrumentation", "hotspot_analysis", "instrumentation", "profiling"):
                self.assertEqual(steps[step]["status"], "skipped", (step, steps[step]))
            self.assertEqual(steps["pattern_detection"]["status"], "skipped", steps["pattern_detection"])
            for run in steps.get("hotspot_profiling", []):
                self.assertEqual(run["status"], "skipped", run)
            self.assertNotIn("build_restore", steps)
            self.assertGreaterEqual(result.data["suggestions_found"], 1)

            # an edit of the sources makes the prepared data stale again
            source = Path(self.project) / "code.cpp"
            source.write_text(source.read_text() + "// edited\n")
            result = await server.call("get_project_status", {"project_path": self.project})
            self.assertFalse(result.is_error, result)
            self.assertTrue(result.data["pipeline"]["profiling"]["stale"], result.data["pipeline"])
            self.assertIn("code.cpp", result.data["pipeline"]["profiling"].get("changed_files", []))

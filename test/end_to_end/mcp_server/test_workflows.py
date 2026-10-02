# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""End-to-end workflows through the MCP server on a tiny C++ program.

These run the real pipeline (instrumentation with discopop_cxx, profiling, the explorer,
the autotuner and the patch applicator) and are skipped where the profiler is not
installed.
"""

import os
import shutil
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from typing import Any, Optional

import anyio
from mcp.types import CancelledNotification, CancelledNotificationParams, ClientNotification

from test.end_to_end.mcp_server.mcp_test_utils import (
    PROFILER_AVAILABLE,
    SRC_DIR,
    ServerHandle,
    ToolResult,
    base_compilers,
    describe,
    descendants,
    mcp_session,
    processes_matching,
)

# Bounds for the calls that do real work; generous, since a loaded CI machine is slow,
# but finite, so that a hang fails the test instead of blocking the run.
PIPELINE_TIMEOUT = 600.0
STEP_TIMEOUT_SECONDS = 300
# the do-all loop in src/code.cpp
LOOP_LINE = 14
LOOP_END_LINE = 17

COMPILE_SCRIPT = "$CXX $CXXFLAGS code.cpp -o prog\n"

requires_profiler = unittest.skipUnless(
    PROFILER_AVAILABLE and base_compilers() is not None,
    "discopop_cc/discopop_cxx or a plain C/C++ compiler not found",
)


def make_project(prefix: str) -> str:
    project = tempfile.mkdtemp(prefix=prefix)
    shutil.copy(SRC_DIR / "code.cpp", Path(project) / "code.cpp")
    return project


async def set_up_project(server: ServerHandle, test: unittest.TestCase, project: str, execute_script: str) -> None:
    compilers = base_compilers()
    assert compilers is not None
    result = await server.call(
        "initialize_discopop_directory",
        {"project_path": project, "base_cc": compilers[0], "base_cxx": compilers[1]},
    )
    test.assertFalse(result.is_error, result)
    result = await server.call("set_compile_script", {"project_path": project, "script_body": COMPILE_SCRIPT})
    test.assertFalse(result.is_error, result)
    result = await server.call(
        "create_execution_configuration",
        {"project_path": project, "config_name": "small", "script_body": execute_script},
    )
    test.assertFalse(result.is_error, result)


async def gather_data(server: ServerHandle, project: str, **extra: Any) -> ToolResult:
    return await server.call(
        "gather_data",
        {"project_path": project, "config_name": "small", "timeout_seconds": STEP_TIMEOUT_SECONDS, **extra},
        timeout=PIPELINE_TIMEOUT,
    )


@requires_profiler
class TestHappyPath(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.project = make_project("dp_mcp_happy_")
        self.addCleanup(shutil.rmtree, self.project, True)
        self.source = Path(self.project) / "code.cpp"
        self.original_source = self.source.read_text()

    async def test_full_workflow(self) -> None:
        project = self.project
        source = str(self.source)
        async with mcp_session() as server:
            await set_up_project(server, self, project, "./prog\n")

            # --- gather_data: instrument, profile, detect
            result = await gather_data(server, project)
            self.assertFalse(result.is_error, result)
            data = result.data
            self.assertEqual(data["status"], "success")
            self.assertFalse(data["hotspot_detection_enabled"])
            for step in ("instrumentation", "profiling", "pattern_detection", "build_restore"):
                self.assertEqual(data["steps"][step]["status"], "success", (step, data["steps"][step]))
            self.assertGreaterEqual(data["suggestions_found"], 1)
            self.assertIn("run_auto_tuning", data["next_step"])
            self.assertNotIn("warning", data)

            result = await server.call("get_project_status", {"project_path": project})
            self.assertFalse(result.is_error, result)
            status = result.data
            for step in ("instrumentation", "profiling", "pattern_detection", "patch_generation"):
                self.assertFalse(status["pipeline"][step]["stale"], (step, status["pipeline"]))
            self.assertEqual(status["pipeline"]["hotspot_detection"], {"done": False})
            self.assertGreaterEqual(status["suggestions"], 1)
            self.assertEqual(status["applied_suggestions"], [])
            self.assertIn("run_auto_tuning", status["next_step"])

            # a repeated call finds every result current
            result = await gather_data(server, project)
            self.assertFalse(result.is_error, result)
            for step in ("instrumentation", "profiling", "pattern_detection"):
                self.assertEqual(result.data["steps"][step]["status"], "skipped", (step, result.data["steps"]))
            self.assertNotIn("build_restore", result.data["steps"])

            # --- the suggestion for the loop
            result = await server.call("get_parallelization_patches", {"project_path": project})
            self.assertFalse(result.is_error, result)
            patches = result.data["patches"]
            self.assertGreaterEqual(result.data["num_suggestions"], 1)
            loop_patches = [p for p in patches if p.get("line") == LOOP_LINE]
            self.assertTrue(loop_patches, patches)
            patch = loop_patches[0]
            pattern_id = patch["pattern_id"]
            self.assertEqual(Path(patch["source_file"]).resolve(), self.source.resolve())
            self.assertEqual(patch["type"], "doall")
            self.assertIn("#pragma omp parallel for", patch["patch_content"])

            result = await server.call(
                "get_parallelization_patches", {"project_path": project, "detail": "summary", "pattern_id": pattern_id}
            )
            self.assertFalse(result.is_error, result)
            self.assertEqual(result.data["num_suggestions"], 1)
            [entry] = result.data["files"]
            [summary] = entry["suggestions"]
            self.assertEqual(summary["pattern_id"], pattern_id)
            self.assertIn("#pragma omp parallel for", summary["pragma"])
            self.assertNotIn("patch_content", summary)

            # --- why: the decision for the loop, and its data dependencies
            result = await server.call(
                "explain_parallelization", {"project_path": project, "file_path": source, "start_line": LOOP_LINE}
            )
            self.assertFalse(result.is_error, result)
            accepted = [r for r in result.data["regions"] if r["outcome"] == "accepted"]
            self.assertTrue(accepted, result.data)
            self.assertIn(pattern_id, [s["pattern_id"] for r in accepted for s in r.get("suggestions", [])])

            result = await server.call(
                "get_data_dependencies",
                {"project_path": project, "file_path": source, "start_line": LOOP_LINE, "end_line": LOOP_END_LINE},
            )
            self.assertFalse(result.is_error, result)
            deps = result.data["dependencies"]
            self.assertEqual(set(deps), {"incoming", "outgoing", "intra_region"})
            self.assertGreater(result.data["num_dependencies"], 0)
            self.assertEqual(result.data["num_dependencies"], sum(len(v) for v in deps.values()))
            for entry in (e for bucket in deps.values() for e in bucket):
                self.assertIn(entry["dep_type"], ("RAW", "WAR", "WAW"))

            result = await server.call(
                "get_data_dependencies",
                {
                    "project_path": project,
                    "file_path": str(Path(project) / "elsewhere.cpp"),
                    "start_line": 1,
                    "end_line": 2,
                },
            )
            self.assertTrue(result.is_error, result)
            self.assertIn("not found in FileMapping", result.data["message"])

            # --- measure the suggestion; without apply=true the sources stay as they were
            result = await server.call(
                "run_auto_tuning",
                {
                    "project_path": project,
                    "config_name": "small",
                    "suggestion_ids": [pattern_id],
                    "timeout_seconds": STEP_TIMEOUT_SECONDS,
                },
                timeout=PIPELINE_TIMEOUT,
            )
            self.assertFalse(result.is_error, result)
            self.assertEqual(result.data["mode"], "selection")
            self.assertEqual(result.data["suggestion_ids"], [pattern_id])
            self.assertEqual(result.data["outcome"], "valid", result.data)
            self.assertIsInstance(result.data["baseline_runtime"], (int, float))
            self.assertFalse(result.data["applied"])
            self.assertEqual(self.source.read_text(), self.original_source)

            result = await server.call(
                "run_auto_tuning",
                {"project_path": project, "config_name": "small", "suggestion_ids": ["999999"]},
            )
            self.assertTrue(result.is_error, result)
            self.assertIn("Unknown suggestion IDs: 999999", result.data["message"])

            # --- apply and roll back
            result = await server.call(
                "manage_patches", {"project_path": project, "action": "apply", "suggestion_ids": [pattern_id]}
            )
            self.assertFalse(result.is_error, result)
            self.assertEqual(result.data["status"], "success", result.data)
            self.assertEqual(result.data["applied_now"], [pattern_id])
            self.assertIn("#pragma omp parallel for", self.source.read_text())

            result = await server.call("manage_patches", {"project_path": project, "action": "list"})
            self.assertFalse(result.is_error, result)
            self.assertEqual(result.data["applied_suggestions"], [pattern_id])

            result = await server.call("get_project_status", {"project_path": project})
            self.assertEqual(result.data["applied_suggestions"], [pattern_id])
            self.assertIn("rollback", result.data["next_step"])

            result = await server.call(
                "manage_patches", {"project_path": project, "action": "rollback", "suggestion_ids": [pattern_id]}
            )
            self.assertFalse(result.is_error, result)
            self.assertEqual(self.source.read_text(), self.original_source)
            result = await server.call("manage_patches", {"project_path": project, "action": "list"})
            self.assertEqual(result.data["applied_suggestions"], [])

            result = await server.call("manage_patches", {"project_path": project, "action": "apply"})
            self.assertTrue(result.is_error, result)
            self.assertIn("suggestion_ids", result.data["message"])

            # --- a later failing build must not leave the old results looking current
            result = await server.call(
                "set_compile_script", {"project_path": project, "script_body": "$CXX $CXXFLAGS missing.cpp -o prog\n"}
            )
            self.assertFalse(result.is_error, result)
            future = time.time() + 5
            os.utime(self.source, (future, future))
            result = await gather_data(server, project)
            self.assertTrue(result.is_error, result)
            self.assertIn("Instrumentation failed", result.data["message"])

            result = await server.call("get_project_status", {"project_path": project})
            self.assertFalse(result.is_error, result)
            pipeline = result.data["pipeline"]
            self.assertEqual(pipeline["instrumentation"], {"done": False}, pipeline)
            self.assertEqual(pipeline["profiling"], {"done": False}, pipeline)
            self.assertTrue(pipeline["pattern_detection"]["stale"], pipeline)
            self.assertIn("No analysis results exist yet", result.data["next_step"])


def _effects(data: dict[str, Any]) -> set[tuple[str, str, str]]:
    """(access, kind, name) of every listed effect of a get_side_effects result."""
    found: set[tuple[str, str, str]] = set()
    for access, bucket in (("write", "writes"), ("read", "reads"), ("unknown", "unknown_access")):
        for effect in data.get(bucket, []):
            found.add((access, effect["kind"], effect["name"]))
    return found


@requires_profiler
class TestSideEffects(unittest.IsolatedAsyncioTestCase):
    """get_side_effects on src/side_effects/code.cpp, whose functions document their ground truth
    (DESIGN_get_side_effects.md, section 5). Only the rows the design expects to hold are asserted;
    rows marked as limitations (stack reuse) are not."""

    def setUp(self) -> None:
        self.project = tempfile.mkdtemp(prefix="dp_mcp_side_effects_")
        self.addCleanup(shutil.rmtree, self.project, True)
        shutil.copy(SRC_DIR / "side_effects" / "code.cpp", Path(self.project) / "code.cpp")

    async def test_ground_truth(self) -> None:
        project = self.project
        async with mcp_session() as server:
            result = await server.call("get_side_effects", {"project_path": project, "function": "main"})
            self.assertTrue(result.is_error, result)

            await set_up_project(server, self, project, "./prog\n")
            result = await gather_data(server, project)
            self.assertFalse(result.is_error, result)

            async def query(function: str, **extra: Any) -> dict[str, Any]:
                result = await server.call("get_side_effects", {"project_path": project, "function": function, **extra})
                self.assertFalse(result.is_error, result)
                self.assertEqual(result.data["status"], "success", result)
                return result.data

            expected: dict[str, set[tuple[str, str, str]]] = {
                "pure_add": set(),
                "read_global": {("read", "global", "g_counter")},
                "write_global": {("write", "global", "g_counter")},
                "write_only_global": {("write", "global", "g_sink")},
                "write_through_param": {("write", "parameter", "p")},
                "wrapper": {("write", "parameter", "p")},
                "local_buffer": set(),
                "address_taken": set(),
                # recorded as GEPRESULT_s by the profiler, i.e. through the parameter s
                "set_member": {("write", "parameter", "s")},
                "shadow": set(),
                "count_calls": {("read", "global", "calls"), ("write", "global", "calls")},
                "recurse": {("read", "global", "g_counter"), ("write", "global", "g_counter")},
            }
            for function, effects in expected.items():
                with self.subTest(function=function):
                    data = await query(function)
                    self.assertEqual(_effects(data), effects, data)

            data = await query("pure_add")
            self.assertEqual(data["coverage"], "executed")
            self.assertIs(data["pure_on_observed_inputs"], True)

            data = await query("wrapper")
            (write,) = data["writes"]
            self.assertEqual(write["sites"][0]["via"], ["write_through_param(int*, int)"])

            data = await query("next_value")
            self.assertIn(("write", "global", "g_seq"), _effects(data))

            data = await query("read_const_table")
            (read,) = data["reads"]
            self.assertEqual((read["name"], read["source"]), ("g_table", "static"))

            data = await query("clear")
            self.assertIn("memset", data["unprofiled_calls"])
            self.assertIsNone(data["pure_on_observed_inputs"])

            data = await query("log_value")
            self.assertTrue(data["performs_file_io"])
            self.assertIs(data["pure_on_observed_inputs"], False)

            data = await query("never_called")
            self.assertEqual(data["coverage"], "not_executed")
            self.assertEqual({(e["name"], e["source"]) for e in data["writes"]}, {("g_unused", "static")})

            self.assertEqual((await query("recurse"))["coverage"], "partial")
            self.assertEqual((await query("chain1"))["coverage"], "partial")
            self.assertEqual((await query("chain7"))["coverage"], "untracked")
            self.assertEqual((await query("pointer_target"))["coverage"], "untracked")

            result = await server.call("get_side_effects", {"project_path": project, "function": "no_such_function"})
            self.assertTrue(result.is_error, result)


@requires_profiler
class TestFailurePaths(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.project = make_project("dp_mcp_fail_")
        self.addCleanup(shutil.rmtree, self.project, True)

    async def test_failing_compile_script(self) -> None:
        project = self.project
        async with mcp_session() as server:
            await set_up_project(server, self, project, "./prog\n")
            result = await server.call(
                "set_compile_script",
                {"project_path": project, "script_body": "$CXX $CXXFLAGS no_such_file.cpp -o prog\n"},
            )
            self.assertFalse(result.is_error, result)

            result = await gather_data(server, project)
            self.assertTrue(result.is_error, result)
            data = result.data
            self.assertEqual(data["status"], "error")
            self.assertIn("Instrumentation failed", data["message"])
            instrumentation = data["steps"]["instrumentation"]
            self.assertNotEqual(instrumentation["returncode"], 0)
            self.assertIn("no_such_file.cpp", instrumentation["stderr"])
            # the hint points at the build script and the tool that fixes it
            self.assertIn("compile.sh", data["next_step"])
            self.assertIn("set_compile_script", data["next_step"])
            self.assertNotIn("profiling", data["steps"])

            result = await server.call("get_project_status", {"project_path": project})
            self.assertFalse(result.is_error, result)
            for step in ("instrumentation", "profiling", "pattern_detection", "patch_generation"):
                self.assertEqual(result.data["pipeline"][step], {"done": False}, result.data["pipeline"])
            self.assertNotIn("suggestions", result.data)

            result = await server.call("get_parallelization_patches", {"project_path": project})
            self.assertTrue(result.is_error, result)

            result = await server.call(
                "get_execution_results",
                {"project_path": project, "script": "compile.sh", "failed_only": True, "include_output": True},
            )
            self.assertFalse(result.is_error, result)
            # the hint names this call as the place to see the failed build's output
            self.assertGreaterEqual(result.data["num_failed"], 1, result.data)
            rows = [
                row
                for scripts in result.data["execution_results"].values()
                for settings in scripts.values()
                for runs in settings.values()
                for row in runs
            ]
            self.assertTrue(
                any("no_such_file.cpp" in (row.get("stderr") or "") + (row.get("stdout") or "") for row in rows),
                rows,
            )

    async def test_failing_execute_script(self) -> None:
        project = self.project
        async with mcp_session() as server:
            await set_up_project(server, self, project, "./prog\necho 'program reported a failure' >&2\nexit 3\n")
            result = await gather_data(server, project)
            self.assertTrue(result.is_error, result)
            data = result.data
            self.assertIn("Profiling failed", data["message"])
            self.assertEqual(data["steps"]["instrumentation"]["status"], "success")
            self.assertEqual(data["steps"]["profiling"]["returncode"], 3)
            self.assertIn("program reported a failure", data["steps"]["profiling"]["stderr"])
            self.assertIn("create_execution_configuration", data["next_step"])

            result = await server.call("get_project_status", {"project_path": project})
            pipeline = result.data["pipeline"]
            # the run wrote its dependencies before failing; they must not count as a result
            self.assertEqual(pipeline["profiling"], {"done": False}, pipeline)
            self.assertEqual(pipeline["pattern_detection"], {"done": False}, pipeline)


@requires_profiler
class TestCancellation(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.project = make_project("dp_mcp_cancel_")
        self.addCleanup(shutil.rmtree, self.project, True)
        # a sleep argument no other process has, to find exactly this run's process
        self.marker = f"300.{uuid.uuid4().int % 10**9:09d}"
        self.addCleanup(self._kill_leftovers)

    def _kill_leftovers(self) -> None:
        for pid in processes_matching(["sleep", self.marker]):
            try:
                os.kill(pid, 9)
            except ProcessLookupError:
                pass

    async def _wait_for_marker(self, timeout: float) -> list[int]:
        with anyio.fail_after(timeout):
            while True:
                pids = processes_matching(["sleep", self.marker])
                if pids:
                    return pids
                await anyio.sleep(0.2)

    async def test_cancel_gather_data(self) -> None:
        project = self.project
        async with mcp_session() as server:
            await set_up_project(server, self, project, f"./prog\nsleep {self.marker}\n")
            server_pid = server.server_pid()
            self.assertIsNotNone(server_pid)
            assert server_pid is not None

            outcome: dict[str, Any] = {}
            async with anyio.create_task_group() as tg:
                # the id the next request gets; the SDK assigns it without awaiting first
                request_id = server.session._request_id

                async def call() -> None:
                    try:
                        outcome["result"] = await gather_data(server, project)
                    except BaseException as error:  # cancelled below
                        outcome["error"] = error
                        raise

                tg.start_soon(call)
                # profiling is running once execute.sh has reached the sleep
                await self._wait_for_marker(PIPELINE_TIMEOUT)
                self.assertIn(
                    server_pid,
                    _ancestors(processes_matching(["sleep", self.marker])[0]),
                    "the sleep should be a descendant of the server",
                )
                # what a client sends when the user aborts a call: the SDK's ClientSession
                # does not send it on its own when the awaiting task is cancelled
                await server.session.send_notification(
                    ClientNotification(
                        CancelledNotification(
                            params=CancelledNotificationParams(requestId=request_id, reason="test cancels the call")
                        )
                    )
                )
                cancelled_at = time.monotonic()
                # no response comes for a cancelled request, so the waiting call is dropped
                tg.cancel_scope.cancel()
            self.assertNotIn("result", outcome)

            # the server answers the next call once the cancelled one has cleaned up
            result = await server.call("get_project_status", {"project_path": project}, timeout=PIPELINE_TIMEOUT)
            self.assertFalse(result.is_error, result)
            # well within the 300s sleep: the process was stopped, not waited for
            self.assertLess(time.monotonic() - cancelled_at, 120)
            pipeline = result.data["pipeline"]
            self.assertEqual(pipeline["profiling"], {"done": False}, pipeline)
            self.assertEqual(pipeline["pattern_detection"], {"done": False}, pipeline)

            self.assertEqual(processes_matching(["sleep", self.marker]), [], "the profiling run survived the cancel")
            leftovers = descendants(server_pid)
            self.assertEqual(leftovers, [], describe(leftovers))

            # and it is still fully usable
            result = await server.call("get_configurations", {"project_path": project})
            self.assertFalse(result.is_error, result)


def _ancestors(pid: int) -> list[int]:
    chain: list[int] = []
    current: Optional[int] = pid
    while current is not None and current > 1:
        try:
            stat = Path(f"/proc/{current}/stat").read_text()
        except OSError:
            break
        current = int(stat.rsplit(")", 1)[1].split()[1])
        chain.append(current)
    return chain


if __name__ == "__main__":
    unittest.main()

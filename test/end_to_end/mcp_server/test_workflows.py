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
import re
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
# the loop after it, which carries a dependency from one iteration to the next
CARRIED_LOOP_LINE = 19

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
            self.assertNotIn("status", data)
            for step in (
                "hotspot_instrumentation",
                "hotspot_analysis",
                "instrumentation",
                "profiling",
                "pattern_detection",
                "build_restore",
            ):
                self.assertEqual(data["steps"][step]["status"], "success", (step, data["steps"][step]))
            self.assertGreaterEqual(data["suggestions_found"], 1)
            self.assertIn("get_parallelization_suggestions", data["next_step"])
            self.assertNotIn("warning", data)

            result = await server.call("get_project_status", {"project_path": project})
            self.assertFalse(result.is_error, result)
            status = result.data
            for step in ("hotspot_detection", "instrumentation", "profiling", "pattern_detection", "patch_generation"):
                self.assertFalse(status["pipeline"][step]["stale"], (step, status["pipeline"]))
            self.assertGreaterEqual(status["suggestions"], 1)
            self.assertIn("get_parallelization_suggestions", status["next_step"])

            # a repeated call finds every result current
            result = await gather_data(server, project)
            self.assertFalse(result.is_error, result)
            for step in ("instrumentation", "profiling", "pattern_detection"):
                self.assertEqual(result.data["steps"][step]["status"], "skipped", (step, result.data["steps"]))
            self.assertNotIn("build_restore", result.data["steps"])

            # --- the suggestion for the loop
            result = await server.call("get_parallelization_suggestions", {"project_path": project})
            self.assertFalse(result.is_error, result)
            self.assertRegex(result.text, r"^\d+ parallelization suggestions, hottest first:")
            [line] = [
                text
                for text in result.text.splitlines()
                if re.search(rf"Loop code\.cpp:{LOOP_LINE}(-\d+)? ", text) and ": doall," in text
            ]
            match = re.match(
                r"Suggestion (\d+): (Potential )?(Hotspot )?Loop \S+ \(.* s, \d+% of runtime\): doall, (.*)", line
            )
            self.assertIsNotNone(match, line)
            assert match is not None
            pattern_id = match.group(1)
            self.assertIn("#pragma omp parallel for", match.group(4))

            # --- why: the decision for the loop, and its data dependencies
            result = await server.call(
                "explain_parallelization", {"project_path": project, "file_path": source, "start_line": LOOP_LINE}
            )
            self.assertFalse(result.is_error, result)
            self.assertIn(f"suggestion {pattern_id} (doall)", result.text)

            result = await server.call(
                "explain_parallelization",
                {"project_path": project, "file_path": source, "start_line": CARRIED_LOOP_LINE + 1},
            )
            self.assertFalse(result.is_error, result)
            self.assertIn(f"Loop code.cpp:{CARRIED_LOOP_LINE}-", result.text)
            self.assertIn("not parallelizable.", result.text)
            self.assertRegex(
                result.text,
                rf"- RAW dependency to code\.cpp:{CARRIED_LOOP_LINE + 1} via elements of variable x "
                rf"from code\.cpp:{CARRIED_LOOP_LINE + 1} prevents parallelization \(observed during profiling\)\.",
            )

            # --- build and run the program as it is; the sources stay as they are
            result = await server.call(
                "run_configuration",
                {"project_path": project, "config_name": "small", "threads": 2, "repetitions": 2},
                timeout=PIPELINE_TIMEOUT,
            )
            self.assertFalse(result.is_error, result)
            self.assertRegex(
                result.text,
                r"^Configuration 'small' with 2 threads: built and ran successfully in [\d.]+ s \(median of 2 runs\)\.",
            )
            self.assertIn("There is no validate.sh", result.text)
            self.assertIn("The program printed nothing.", result.text)

            result = await server.call(
                "run_configuration", {"project_path": project, "config_name": "small", "rebuild": False, "threads": 1}
            )
            self.assertIn("with 1 thread: built and ran successfully", result.text)

            # DiscoPoP only reads the sources: nothing above has modified them
            self.assertEqual(self.source.read_text(), self.original_source)

            # --- a later failing build must not leave the old results looking current
            result = await server.call(
                "set_compile_script", {"project_path": project, "script_body": "$CXX $CXXFLAGS missing.cpp -o prog\n"}
            )
            self.assertFalse(result.is_error, result)
            future = time.time() + 5
            os.utime(self.source, (future, future))
            result = await gather_data(server, project)
            self.assertTrue(result.is_error, result)
            self.assertIn("Hotspot detection failed", result.data["message"])

            result = await server.call("get_project_status", {"project_path": project})
            self.assertFalse(result.is_error, result)
            pipeline = result.data["pipeline"]
            self.assertEqual(pipeline["hotspot_detection"], {"done": False}, pipeline)
            self.assertTrue(pipeline["instrumentation"]["stale"], pipeline)
            self.assertTrue(pipeline["pattern_detection"]["stale"], pipeline)
            self.assertIn("sources changed after the last analysis", result.data["next_step"])


def _effects(text: str) -> set[tuple[str, str, str]]:
    """(access, kind, name) of every effect listed in the text of a get_side_effects result."""
    sections = {"Writes:": "write", "Reads:": "read", "Referenced in the code, access unknown:": "unknown"}
    found: set[tuple[str, str, str]] = set()
    access = ""
    for line in text.splitlines():
        if line in sections:
            access = sections[line]
        elif line.startswith("- ") and access:
            match = re.match(r"- (\S+) \((global|parameter|other memory)[,)]", line)
            assert match is not None, line
            found.add((access, match.group(2).split()[0], match.group(1)))
        else:
            access = "" if not line.startswith("- ") else access
    return found


@requires_profiler
class TestSideEffects(unittest.IsolatedAsyncioTestCase):
    """get_side_effects on src/side_effects/code.cpp, whose functions document their ground truth
    (design/get_side_effects.md, section 5). Only the rows the design expects to hold are asserted;
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

            async def query(function: str, **extra: Any) -> str:
                result = await server.call("get_side_effects", {"project_path": project, "function": function, **extra})
                self.assertFalse(result.is_error, result)
                return result.text

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
                # ++g_seq: the read is not observed separately, the static fallback adds it
                "next_value": {("read", "global", "g_seq"), ("write", "global", "g_seq")},
                "bump": {("read", "parameter", "x"), ("write", "parameter", "x")},
                "sibling_a": set(),
                "sibling_b": set(),
                "read_const_table": {("read", "global", "g_table")},
                "chain1": {("read", "global", "g_chain"), ("write", "global", "g_chain")},
            }
            for function, effects in expected.items():
                with self.subTest(function=function):
                    text = await query(function)
                    self.assertEqual(_effects(text), effects, text)

            text = await query("pure_add")
            self.assertIn("Pure on the profiled inputs", text)
            self.assertNotIn("Caveat", text)

            text = await query("wrapper")
            self.assertRegex(text, r"- p \(parameter.*: line \d+ via write_through_param\(int\*, int\)")

            text = await query("read_const_table")
            self.assertIn("- g_table (global, referenced in the code, not observed)", text)
            self.assertIn("Pure on the profiled inputs", text)

            # main aggregates the effects of everything it calls, also beyond the inlining depth
            text = await query("main", limit=100)
            self.assertLessEqual(
                {
                    ("write", "global", "g_counter"),
                    ("write", "global", "g_sink"),
                    ("write", "global", "g_chain"),
                    ("write", "global", "g_seq"),
                    ("read", "global", "g_seq"),
                    ("write", "global", "calls"),
                },
                _effects(text),
                text,
            )
            self.assertIn("Not pure: it writes", text)

            text = await query("clear")
            self.assertIn("calls whose accesses were not observed (library code):", text)
            self.assertIn("memset", text)
            self.assertIn("Purity is undecided.", text)

            text = await query("log_value")
            self.assertIn("Not pure: it performs file I/O.", text)

            text = await query("never_called")
            self.assertIn("Caveat: Never executed during profiling", text)
            self.assertEqual(_effects(text), {("write", "global", "g_unused")})
            self.assertIn("- g_unused (global, referenced in the code, not observed)", text)

            self.assertIn("Caveat: Some calls could not be followed", await query("recurse"))
            self.assertIn("Caveat: Some calls could not be followed", await query("chain1"))
            self.assertIn("Caveat: Executed, but none of its calls", await query("chain7"))
            self.assertIn("Caveat: Executed, but none of its calls", await query("pointer_target"))

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
            self.assertIn("Hotspot detection failed", data["message"])
            instrumentation = data["steps"]["hotspot_instrumentation"]
            self.assertNotEqual(instrumentation["returncode"], 0)
            self.assertIn("no_such_file.cpp", instrumentation["stderr"])
            # the hint points at the build script and the tool that fixes it
            self.assertIn("compile.sh", data["next_step"])
            self.assertIn("set_compile_script", data["next_step"])
            self.assertNotIn("instrumentation", data["steps"])

            result = await server.call("get_project_status", {"project_path": project})
            self.assertFalse(result.is_error, result)
            for step in ("hotspot_detection", "instrumentation", "profiling", "pattern_detection", "patch_generation"):
                self.assertEqual(result.data["pipeline"][step], {"done": False}, result.data["pipeline"])
            self.assertNotIn("suggestions", result.data)

            result = await server.call("get_parallelization_suggestions", {"project_path": project})
            self.assertTrue(result.is_error, result)

            # the build error reaches the agent that runs the program, too
            result = await server.call("run_configuration", {"project_path": project, "config_name": "small"})
            self.assertFalse(result.is_error, result)
            self.assertIn("the build failed", result.text)
            self.assertIn("no_such_file.cpp", result.text)
            self.assertIn("the program was not run", result.text)

    async def test_failing_execute_script(self) -> None:
        project = self.project
        async with mcp_session() as server:
            await set_up_project(server, self, project, "./prog\necho 'program reported a failure' >&2\nexit 3\n")
            result = await gather_data(server, project)
            self.assertTrue(result.is_error, result)
            data = result.data
            self.assertIn("Hotspot detection failed", data["message"])
            self.assertEqual(data["steps"]["hotspot_instrumentation"]["status"], "success")
            (hotspot_run,) = data["steps"]["hotspot_profiling"]
            self.assertEqual(hotspot_run["returncode"], 3)
            self.assertIn("program reported a failure", hotspot_run["stderr"])
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

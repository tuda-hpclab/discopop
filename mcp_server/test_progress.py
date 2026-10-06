# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Progress reporting, and handlers that run without blocking the server."""

import asyncio
import json
import os
import shutil
import signal
import subprocess
import threading
import time
import unittest
from types import SimpleNamespace
from typing import Any, Optional
from unittest import mock

import anyio
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import CancelledNotification, CancelledNotificationParams, ClientNotification, TextContent, Tool

from mcp_server import server as server_module
from mcp_server.tools import helpers
from mcp_server.tools.helpers import ToolContext


class TestReportProgress(unittest.TestCase):
    def setUp(self) -> None:
        self.ctx = ToolContext(debug=False)
        self.reports: list[tuple[float, Optional[float], Optional[str]]] = []

    def __record(self, progress: float, total: Optional[float], message: Optional[str]) -> None:
        self.reports.append((progress, total, message))

    def test_nothing_is_reported_when_the_client_did_not_ask(self) -> None:
        self.ctx.report_progress(1, 2, "step")  # must not raise either
        with self.ctx.heartbeat(interval=0.01):
            time.sleep(0.05)
        self.assertEqual(self.reports, [])

    def test_progress_always_increases(self) -> None:
        # MCP requires it; a repeated step would otherwise be a protocol violation.
        with self.ctx.reporting_progress(self.__record):
            self.ctx.report_progress(1, 3, "step 2")
            self.ctx.report_progress(1, 3, "step 2 again")
            self.ctx.report_progress(0, None, "rebuild")
        values = [progress for progress, _total, _message in self.reports]
        self.assertEqual(values, sorted(values))
        self.assertEqual(len(set(values)), 3)

    def test_a_missing_total_keeps_the_one_reported_before(self) -> None:
        with self.ctx.reporting_progress(self.__record):
            self.ctx.report_progress(1, 3, "step 2")
            self.ctx.report_progress(2, None, "rebuild")
        self.assertEqual(self.reports[-1][1], 3)

    def test_a_heartbeat_repeats_the_last_state_as_still_running(self) -> None:
        with self.ctx.reporting_progress(self.__record):
            self.ctx.report_progress(1, 3, "[2/3] Profiling")
            with self.ctx.heartbeat(interval=0.01):
                time.sleep(0.1)
        beats = self.reports[1:]
        self.assertTrue(beats)
        self.assertTrue(all("[2/3] Profiling (still running" in str(message) for _p, _t, message in beats))
        self.assertTrue(all(total == 3 for _p, total, _m in beats))

    def test_the_reporter_is_gone_after_the_call(self) -> None:
        with self.ctx.reporting_progress(self.__record):
            pass
        self.ctx.report_progress(1, 2, "late")
        self.assertEqual(self.reports, [])


def _tool(name: str, handle: Any) -> Any:
    return SimpleNamespace(
        TOOL=Tool(name=name, inputSchema={"type": "object", "properties": {}, "additionalProperties": False}),
        handle=handle,
    )


def _success(_arguments: dict[str, Any], _ctx: ToolContext) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps({"status": "success"}))]


class TestServerRunsHandlersOffTheEventLoop(unittest.TestCase):
    """Over a real (in-memory) MCP connection."""

    def __server(self, *tools: Any) -> server_module.DiscoPopMCPServer:
        with mock.patch.dict(server_module.TOOL_SETS, {"test": list(tools)}):
            return server_module.DiscoPopMCPServer(tool_set="test")

    def test_progress_reaches_the_client(self) -> None:
        def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
            ctx.report_progress(0, 2, "[1/2] Build")
            ctx.report_progress(1, 2, "[2/2] Run")
            return _success(arguments, ctx)

        received: list[tuple[float, Optional[float], Optional[str]]] = []

        async def on_progress(progress: float, total: Optional[float], message: Optional[str]) -> None:
            received.append((progress, total, message))

        async def scenario() -> None:
            async with create_connected_server_and_client_session(self.__server(_tool("t", handle)).server) as client:
                result = await client.call_tool("t", {}, progress_callback=on_progress)
                self.assertFalse(result.isError)

        anyio.run(scenario)
        self.assertEqual(received, [(0, 2, "[1/2] Build"), (1, 2, "[2/2] Run")])

    def test_heartbeats_from_their_own_thread_reach_the_client(self) -> None:
        # A heartbeat runs in a plain thread, not in the handler's worker thread, so
        # it relies on the event loop token to get its notification sent.
        def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
            ctx.report_progress(0, 1, "[1/1] Profiling")
            with ctx.heartbeat(interval=0.02):
                time.sleep(0.2)
            return _success(arguments, ctx)

        received: list[Optional[str]] = []

        async def on_progress(progress: float, total: Optional[float], message: Optional[str]) -> None:
            received.append(message)

        async def scenario() -> None:
            async with create_connected_server_and_client_session(self.__server(_tool("t", handle)).server) as client:
                await client.call_tool("t", {}, progress_callback=on_progress)

        anyio.run(scenario)
        self.assertGreater(len(received), 1)
        self.assertTrue(all("still running" in str(message) for message in received[1:]))

    def test_the_server_answers_while_a_tool_runs(self) -> None:
        # Run on the event loop, a handler made the server unresponsive for as long
        # as the tool ran -- hours for gather_data or run_auto_tuning.
        # Client and server share one event loop here, so a handler blocking it would
        # block the client too; what tells the cases apart is whether the client got
        # its ping answered and released the handler before the handler gave up.
        started, release = threading.Event(), threading.Event()
        released_by_client: list[bool] = []

        def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
            started.set()
            released_by_client.append(release.wait(timeout=2))
            return _success(arguments, ctx)

        async def scenario() -> None:
            async with create_connected_server_and_client_session(self.__server(_tool("t", handle)).server) as client:
                async with anyio.create_task_group() as tg:
                    tg.start_soon(client.call_tool, "t", {})
                    await anyio.to_thread.run_sync(started.wait, 5)
                    await client.send_ping()
                    release.set()

        anyio.run(scenario)
        self.assertEqual(released_by_client, [True])

    def test_the_proxy_reports_progress_when_running_inline(self) -> None:
        # The default entry point; without a daemon it runs the handler itself.
        def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
            ctx.report_progress(0, 1, "working")
            return _success(arguments, ctx)

        with mock.patch.dict(server_module.TOOL_SETS, {"test": [_tool("t", handle)]}):
            # Port 1: nothing listens there, so a daemon running on this machine is not used.
            proxy = server_module.DiscoPopMCPProxy(daemon_port=1, tool_set="test")
        received: list[Optional[str]] = []

        async def on_progress(progress: float, total: Optional[float], message: Optional[str]) -> None:
            received.append(message)

        async def scenario() -> None:
            async with create_connected_server_and_client_session(proxy.server) as client:
                result = await client.call_tool("t", {}, progress_callback=on_progress)
                self.assertFalse(result.isError)

        anyio.run(scenario)
        self.assertEqual(received, ["working"])

    def test_tool_calls_still_run_one_at_a_time(self) -> None:
        # Handlers change the working directory and share the ToolContext.
        running = 0
        peak = 0
        lock = threading.Lock()

        def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
            nonlocal running, peak
            with lock:
                running += 1
                peak = max(peak, running)
            time.sleep(0.05)
            with lock:
                running -= 1
            return _success(arguments, ctx)

        async def scenario() -> None:
            async with create_connected_server_and_client_session(self.__server(_tool("t", handle)).server) as client:
                async with anyio.create_task_group() as tg:
                    for _ in range(3):
                        tg.start_soon(client.call_tool, "t", {})

        anyio.run(scenario)
        self.assertEqual(peak, 1)


class TestCancellation(unittest.TestCase):
    def test_cancel_stops_the_registered_process_and_its_children(self) -> None:
        ctx = ToolContext(debug=False)
        with ctx.cancellable():
            # a shell that waits for a child: stopping only the shell would leave the child
            proc = subprocess.Popen(["/bin/sh", "-c", "sleep 30; true"])
            ctx.track_process(proc)
            time.sleep(0.2)
            children = helpers._descendants(proc.pid)
            self.assertTrue(children)
            ctx.cancel()
            proc.wait(timeout=5)
            self.assertTrue(ctx.cancelled)
            deadline = time.monotonic() + 5
            while any(os.path.exists(f"/proc/{pid}") and _state(pid) != "Z" for pid in children):
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.05)
        self.assertFalse(ctx.cancelled)

    def test_a_tree_in_its_own_session_is_stopped_where_a_child_left_the_group(self) -> None:
        # the auto-tuner's shape: started in its own session, its scripts run under GNU
        # timeout, which moves itself and the script into a group of their own
        if not shutil.which("timeout"):
            self.skipTest("GNU timeout not available")
        proc = subprocess.Popen(["/bin/sh", "-c", "timeout 30 sleep 30; true"], start_new_session=True)
        deadline = time.monotonic() + 5
        while len(helpers._descendants(proc.pid)) < 2:
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)
        tree = helpers._descendants(proc.pid)
        self.assertTrue(any(os.getpgid(pid) != proc.pid for pid in tree))

        helpers.terminate_process_tree(proc, grace_seconds=5)

        self.assertIsNotNone(proc.poll())
        self.assertFalse([pid for pid in tree if os.path.exists(f"/proc/{pid}") and _state(pid) != "Z"])

    def test_a_session_whose_leader_exited_is_stopped(self) -> None:
        # the leader is gone and reaped, so its orphaned child is no longer its descendant
        proc = subprocess.Popen(
            ["/bin/sh", "-c", "sleep 30 >/dev/null 2>&1 & echo $!"],
            stdout=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        stdout, _ = proc.communicate(timeout=5)
        orphan = int(stdout.strip())
        self.assertTrue(helpers._alive(orphan))

        def kill_orphan() -> None:
            if helpers._alive(orphan):
                os.kill(orphan, signal.SIGKILL)

        self.addCleanup(kill_orphan)

        helpers.terminate_process_tree(proc, grace_seconds=5)

        deadline = time.monotonic() + 5
        while helpers._alive(orphan):
            self.assertLess(time.monotonic(), deadline)
            time.sleep(0.05)

    def test_a_pid_counts_as_alive_only_for_the_process_found_under_it(self) -> None:
        start_time = helpers._stat(os.getpid())[helpers._START_TIME]  # type: ignore[index]
        self.assertTrue(helpers._alive(os.getpid(), start_time))
        # the same pid with another start time is a later process that reused it
        self.assertFalse(helpers._alive(os.getpid(), str(int(start_time) + 1)))

    def test_a_process_started_after_the_cancel_is_stopped(self) -> None:
        # the handler started it between its last look at ctx.cancelled and the cancel
        ctx = ToolContext(debug=False)
        with ctx.cancellable():
            ctx.cancel()
            started = time.monotonic()
            result = ctx.run_process(["/bin/sh", "-c", "sleep 30; echo done"], timeout=60)
        self.assertLess(time.monotonic() - started, 15)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "")

    def test_a_cleanup_process_started_after_the_cancel_runs_to_its_end(self) -> None:
        # e.g. the plain rebuild of gather_data
        ctx = ToolContext(debug=False)
        with ctx.cancellable():
            ctx.cancel()
            result = ctx.run_process(["/bin/sh", "-c", "sleep 0.2; echo done"], timeout=5, cleanup=True)
        self.assertEqual(result.stdout.strip(), "done")

    def test_a_cancelled_call_is_told_and_the_next_call_waits_for_its_cleanup(self) -> None:
        started = threading.Event()
        order: list[str] = []

        def slow(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
            started.set()
            deadline = time.monotonic() + 5
            while not ctx.cancelled and time.monotonic() < deadline:
                time.sleep(0.01)
            order.append("cancel seen" if ctx.cancelled else "never cancelled")
            time.sleep(0.2)  # cleaning up
            order.append("cleanup done")
            return _success(arguments, ctx)

        def quick(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
            order.append("next call")
            return _success(arguments, ctx)

        with mock.patch.dict(server_module.TOOL_SETS, {"test": [_tool("slow", slow), _tool("quick", quick)]}):
            server = server_module.DiscoPopMCPServer(tool_set="test")

        async def scenario() -> None:
            async with create_connected_server_and_client_session(server.server) as client:
                async with anyio.create_task_group() as tg:

                    async def call_slow() -> None:
                        try:
                            await client.call_tool("slow", {})
                        except Exception:
                            pass  # the server answers a cancelled request with an error

                    tg.start_soon(call_slow)
                    await anyio.to_thread.run_sync(started.wait, 5)
                    # the id of the slow call: initialize was request 0
                    await client.send_notification(
                        ClientNotification(
                            CancelledNotification(params=CancelledNotificationParams(requestId=1, reason="test"))
                        )
                    )
                    await client.call_tool("quick", {})

        anyio.run(scenario)
        self.assertEqual(order, ["cancel seen", "cleanup done", "next call"])

    def test_the_proxy_passes_a_cancel_on_to_the_daemon(self) -> None:
        started = threading.Event()
        finished = threading.Event()
        seen: list[str] = []

        def slow(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
            started.set()
            deadline = time.monotonic() + 5
            while not ctx.cancelled and time.monotonic() < deadline:
                time.sleep(0.01)
            seen.append("cancel seen" if ctx.cancelled else "never cancelled")
            finished.set()
            return _success(arguments, ctx)

        with mock.patch.dict(server_module.TOOL_SETS, {"test": [_tool("slow", slow)]}):
            daemon = server_module.DiscoPopMCPServer(tool_set="test")
            proxy = server_module.DiscoPopMCPProxy(daemon_port=1, tool_set="test")

        async def scenario() -> None:
            async with create_connected_server_and_client_session(daemon.server) as daemon_session:
                # what _ensure_daemon leaves behind once it connected to a daemon
                proxy._session = daemon_session
                proxy._daemon_init_started = True
                proxy._daemon_session_ready = asyncio.Event()
                proxy._daemon_session_ready.set()
                # move the daemon session's request ids away from the client's, so that only a
                # cancel carrying the id the proxy used reaches the slow call
                for _ in range(3):
                    await daemon_session.list_tools()
                async with create_connected_server_and_client_session(proxy.server) as client:
                    async with anyio.create_task_group() as tg:

                        async def call_slow() -> None:
                            try:
                                await client.call_tool("slow", {})
                            except Exception:
                                pass

                        tg.start_soon(call_slow)
                        await anyio.to_thread.run_sync(started.wait, 5)
                        # the client's id of the slow call; the proxy sent it to the daemon as 4
                        await client.send_notification(
                            ClientNotification(
                                CancelledNotification(params=CancelledNotificationParams(requestId=1, reason="test"))
                            )
                        )
                        await anyio.to_thread.run_sync(finished.wait, 10)

        anyio.run(scenario)
        self.assertEqual(seen, ["cancel seen"])


def _state(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().rsplit(")", 1)[1].split()[0]
    except OSError:
        return "Z"


if __name__ == "__main__":
    unittest.main()

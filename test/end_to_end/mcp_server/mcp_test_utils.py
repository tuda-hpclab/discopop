# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Helpers for driving the DiscoPoP MCP server the way a real client does.

The server is started as a subprocess (``python -m mcp_server.server``) from the
repository root, so the tests exercise the server code of this checkout rather than
a copy installed in site-packages, and talked to over stdio with the MCP SDK client.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import IO, Any, AsyncIterator, Optional

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult, TextContent

REPO_ROOT = Path(__file__).resolve().parents[3]
# A tiny C++ program with one parallelizable loop (the do-all loop at line 14).
SRC_DIR = Path(__file__).resolve().parent / "src"

# Upper bound for a call that does no real work; a hang fails the test instead of blocking it.
QUICK_CALL_TIMEOUT = 60.0


def free_port() -> int:
    """A TCP port nothing listens on right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def server_env() -> dict[str, str]:
    """The environment of the server: this checkout first on the import path, and the
    venv's bin directory (discopop_cxx, discopop_explorer, ...) first on PATH."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PATH"] = os.path.dirname(sys.executable) + os.pathsep + env.get("PATH", "")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def server_command(*args: str) -> list[str]:
    return [sys.executable, "-m", "mcp_server.server", *args]


def find_discopop_tool(name: str) -> Optional[str]:
    """A DiscoPoP executable next to the interpreter, or on PATH."""
    candidate = Path(sys.executable).parent / name
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return str(candidate)
    return shutil.which(name)


PROFILER_AVAILABLE = find_discopop_tool("discopop_cc") is not None and find_discopop_tool("discopop_cxx") is not None


def base_compilers() -> Optional[tuple[str, str]]:
    """A plain C/C++ compiler pair for the sequential and parallel builds."""
    for cc, cxx in (("clang", "clang++"), ("gcc", "g++")):
        if shutil.which(cc) and shutil.which(cxx):
            return cc, cxx
    return None


@asynccontextmanager
async def mcp_session(*server_args: str, daemon_port: Optional[int] = None) -> AsyncIterator["ServerHandle"]:
    """Start the server over stdio and yield an initialized session.

    The default entry point is a proxy that forwards to a daemon if one listens on its
    daemon port. Unless a daemon port is given, a free port is passed, so the calls are
    guaranteed to run inline -- a developer's daemon on the default port must not take
    over the test.
    """
    port = daemon_port if daemon_port is not None else free_port()
    args = ["--daemon-port", str(port), *server_args]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server.server", *args],
        env=server_env(),
        cwd=str(REPO_ROOT),
    )
    # A failure in the test body is held until the session is closed and then raised as it
    # is: raised inside, the SDK's task groups would wrap it in an ExceptionGroup, which
    # unittest reports as an error rather than as the assertion that failed.
    failure: Optional[Exception] = None
    with tempfile.TemporaryFile(mode="w+") as errlog:
        async with stdio_client(params, errlog=errlog) as (read, write):
            async with ClientSession(read, write) as session:
                with anyio.fail_after(QUICK_CALL_TIMEOUT):
                    init = await session.initialize()
                handle = ServerHandle(session, init, errlog, port)
                try:
                    yield handle
                except Exception as error:
                    failure = error
                    sys.stderr.write("---- server stderr ----\n" + handle.stderr() + "\n-----------------------\n")
    if failure is not None:
        raise failure


class ToolResult:
    """A tools/call result, with its JSON payload decoded."""

    def __init__(self, raw: CallToolResult) -> None:
        self.raw = raw
        self.is_error = bool(raw.isError)
        texts = [c.text for c in raw.content if isinstance(c, TextContent)]
        self.text = texts[0] if texts else ""
        try:
            decoded = json.loads(self.text)
        except ValueError:
            decoded = None
        self.data: dict[str, Any] = decoded if isinstance(decoded, dict) else {}

    def __repr__(self) -> str:
        return f"ToolResult(is_error={self.is_error}, text={self.text[:2000]!r})"


class ServerHandle:
    def __init__(self, session: ClientSession, init: Any, errlog: IO[str], daemon_port: int) -> None:
        self.session = session
        self.init = init
        self.errlog = errlog
        self.daemon_port = daemon_port

    async def call(self, name: str, arguments: dict[str, Any], timeout: float = QUICK_CALL_TIMEOUT) -> ToolResult:
        with anyio.fail_after(timeout):
            return ToolResult(await self.session.call_tool(name, arguments))

    def stderr(self) -> str:
        self.errlog.flush()
        self.errlog.seek(0)
        return self.errlog.read()

    def server_pid(self) -> Optional[int]:
        """The pid of the server process, found by its unique --daemon-port argument."""
        matches = processes_matching(["mcp_server.server", "--daemon-port", str(self.daemon_port)])
        return matches[0] if matches else None


# --- process inspection via /proc ---------------------------------------------------


def _cmdline(pid: int) -> list[str]:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [part.decode(errors="replace") for part in raw.split(b"\0") if part]


def _all_pids() -> list[int]:
    return [int(entry) for entry in os.listdir("/proc") if entry.isdigit()]


def processes_matching(arguments: list[str]) -> list[int]:
    """Pids of live processes whose command line contains every one of `arguments`."""
    found = []
    for pid in _all_pids():
        if pid == os.getpid():
            continue
        cmdline = _cmdline(pid)
        if cmdline and all(arg in cmdline for arg in arguments) and not _is_zombie(pid):
            found.append(pid)
    return found


def _is_zombie(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return True
    return stat.rsplit(")", 1)[1].split()[0] == "Z"


def descendants(pid: int) -> list[int]:
    """Live (non-zombie) descendants of `pid`."""
    children: dict[int, list[int]] = {}
    for candidate in _all_pids():
        try:
            stat = Path(f"/proc/{candidate}/stat").read_text()
        except OSError:
            continue
        fields = stat.rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            continue
        children.setdefault(int(fields[1]), []).append(candidate)
    result: list[int] = []
    pending = [pid]
    while pending:
        current = pending.pop()
        for child in children.get(current, []):
            result.append(child)
            pending.append(child)
    return result


def describe(pids: list[int]) -> str:
    return "; ".join(f"{pid}: {' '.join(_cmdline(pid))}" for pid in pids)


def wait_until(predicate: Any, timeout: float, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


# --- daemon ---------------------------------------------------------------------------


class Daemon:
    """``discopop_mcp_server --daemon`` as a subprocess; always stopped by stop()."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.log = tempfile.TemporaryFile(mode="w+")
        self.proc = subprocess.Popen(
            server_command("--daemon", "--daemon-port", str(port)),
            cwd=str(REPO_ROOT),
            env=server_env(),
            stdin=subprocess.DEVNULL,
            stdout=self.log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    def wait_listening(self, timeout: float = 60.0) -> bool:
        def listening() -> bool:
            if self.proc.poll() is not None:
                return True  # exited; reported by the caller
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                    return True
            except OSError:
                return False

        return wait_until(listening, timeout) and self.proc.poll() is None

    def output(self) -> str:
        self.log.flush()
        self.log.seek(0)
        return self.log.read()

    def stop(self) -> None:
        if self.proc.poll() is None:
            try:
                os.killpg(self.proc.pid, 15)
            except ProcessLookupError:
                pass
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.proc.pid, 9)
                except ProcessLookupError:
                    pass
                self.proc.wait(timeout=10)
        self.log.close()

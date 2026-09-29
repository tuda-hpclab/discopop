#!/usr/bin/env python3
#
# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""DiscoPoP MCP Server

A Model Context Protocol server that exposes DiscoPoP functionality to LLM Agents.
Allows an LLM to drive the full instrumentation pipeline — compile, profile,
detect patterns, and retrieve patches — without human intervention.

Primary use cases:
  - Parallelism detection: instrument a project, run profiling, detect parallel patterns,
    and retrieve OpenMP patches ready for application.
  - Data dependency analysis: query the combined static and dynamic data dependencies for
    arbitrary code regions to support general code understanding, refactoring, and
    correctness checks.
"""

import asyncio
import json
import logging
import sys
import time
from typing import Any, Callable, Optional

from mcp.server import Server
from mcp.types import TextContent, Tool
from termcolor import colored

from mcp_server.argument_coercion import coerce_arguments, validation_error
from mcp_server.setup_mcp import MCPSetup

from mcp_server.tools import (
    create_execution_configuration,
    gather_data,
    get_configurations,
    get_data_dependencies,
    get_execution_results,
    get_parallelization_patches,
    initialize_discopop_directory,
    manage_patches,
    run_auto_tuning,
    set_compile_script,
)
from mcp_server.tools.helpers import ToolContext

_LOG_FORMAT = "%(asctime)s  %(levelname)-8s  %(message)s"
_LOG_DATEFMT = "%H:%M:%S"


class _ColoredFormatter(logging.Formatter):
    """Applies ANSI colours to the prefix portion of each log line.

    For INFO lines with a semantic marker (▶ ✓ ✗ → ←) the coloured region
    is:  timestamp  LEVEL  <marker> <label>:
    Everything after the colon (the tool name, arguments, …) is left plain.

    For WARNING / ERROR / DEBUG the coloured region is the timestamp + level
    prefix only; the message body is always plain.
    """

    _MARKER: dict[str, tuple[str, list[str]]] = {
        "▶": ("cyan", ["bold"]),  # ▶ Executing:
        "✓": ("green", ["bold"]),  # ✓ Completed:
        "✗": ("red", ["bold"]),  # ✗ Failed:
        "→": ("cyan", []),  # → Incoming call:
        "←": ("magenta", []),  # ← Outgoing response:
    }
    _LEVEL: dict[int, tuple[str, list[str]]] = {
        logging.DEBUG: ("white", ["dark"]),
        logging.WARNING: ("yellow", []),
        logging.ERROR: ("red", ["bold"]),
        logging.CRITICAL: ("red", ["bold", "underline"]),
    }

    def format(self, record: logging.LogRecord) -> str:
        timestamp = self.formatTime(record, self.datefmt)
        prefix = f"{timestamp}  {record.levelname:<8}  "
        msg = record.getMessage()

        # Level-based lines: colour prefix only, message body stays plain.
        if record.levelno in self._LEVEL:
            c, attrs = self._LEVEL[record.levelno]
            result = str(colored(prefix, c, attrs=attrs or None)) + msg
        # INFO with semantic marker: colour prefix + label up to the first colon.
        elif msg.lstrip()[:1] in self._MARKER:
            c, attrs = self._MARKER[msg.lstrip()[:1]]
            colon = msg.find(":")
            if colon >= 0:
                result = str(colored(prefix + msg[: colon + 1], c, attrs=attrs or None)) + msg[colon + 1 :]
            else:
                result = str(colored(prefix + msg, c, attrs=attrs or None))
        else:
            result = prefix + msg

        # Append exception / stack info verbatim (never coloured).
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            result += "\n" + record.exc_text
        if record.stack_info:
            result += "\n" + self.formatStack(record.stack_info)

        return result


def _setup_logging(debug: bool = False) -> None:
    handler = logging.StreamHandler(sys.stderr)
    if sys.stderr.isatty():
        handler.setFormatter(_ColoredFormatter(fmt=_LOG_FORMAT, datefmt=_LOG_DATEFMT))
    else:
        handler.setFormatter(logging.Formatter(fmt=_LOG_FORMAT, datefmt=_LOG_DATEFMT))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if debug else logging.INFO)


_setup_logging()
logger = logging.getLogger("discopop-mcp")

_SERVER_INSTRUCTIONS = (
    "This server exposes DiscoPoP functionality for two primary use cases: "
    "(1) parallelism detection — instrument a project, run profiling, detect parallel patterns, "
    "retrieve OpenMP patches, and apply or roll back patches via manage_patches; "
    "(2) data dependency analysis — query the combined static and dynamic data dependencies "
    "for arbitrary code regions to support code understanding, refactoring, and correctness checks. "
    "All DiscoPoP data must be accessed exclusively through the tool calls provided by this server. "
    "Do not read, list, or inspect .discopop directories or their contents directly via file reads, "
    "directory listings, or shell commands. "
    "Those directories contain large binary files, intermediate artefacts, and serialised objects "
    "that are expensive to parse and consume a large number of tokens. "
    "The MCP tools return pre-processed, structured summaries at a fraction of the token cost. "
    "If information appears to be missing, use the tool that produces it "
    "(e.g. run gather_data before calling get_parallelization_patches or get_data_dependencies) "
    "rather than reading the underlying files directly. "
    "The route from an initialized project to parallelized code is: gather_data to profile "
    "and detect patterns, then run_auto_tuning to measure which combination of the resulting "
    "suggestions is actually fastest, then manage_patches to apply that combination — or "
    "run_auto_tuning(apply=true), which does the last two in one call. "
    "Never decide which patches to apply by reading them: that choice is what run_auto_tuning "
    "measures, and picking from the diffs by hand throws away the one thing DiscoPoP can "
    "establish and a reader cannot. Call it BEFORE applying anything — it needs an un-patched "
    "project, and clears and restores an existing selection to get one. "
    "IMPORTANT: Always use manage_patches to apply suggested patches — never read patch content "
    "and apply changes manually. manage_patches delegates all patching work to the "
    "discopop_patch_applicator binary, which is orders of magnitude faster and consumes far "
    "fewer tokens than reading patch files and editing source files by hand. "
    "Use initialize_discopop_directory with reset=true to clear stale analysis artefacts "
    "when the pipeline is in a broken or inconsistent state."
)

_ALL_TOOLS = [
    get_configurations,
    get_execution_results,
    get_data_dependencies,
    initialize_discopop_directory,
    set_compile_script,
    create_execution_configuration,
    gather_data,
    get_parallelization_patches,
    run_auto_tuning,
    manage_patches,
]

# The three tools that *define* a project rather than analyse one. Together they are
# roughly a third of the tool definitions this server sends a client, and a caller
# working on a project that is already set up -- an unattended run against a prepared
# project, most of all -- never wants them: at best they are unused context, at worst
# initialize_discopop_directory(reset=true) removes the very configurations the caller
# was pointed at. --tools analysis leaves them out, of the listing and of dispatch
# alike, so "not offered" and "not available" mean the same thing.
_SETUP_TOOLS = [
    initialize_discopop_directory,
    set_compile_script,
    create_execution_configuration,
]

TOOL_SETS = {
    "all": _ALL_TOOLS,
    "analysis": [tool for tool in _ALL_TOOLS if tool not in _SETUP_TOOLS],
}
DEFAULT_TOOL_SET = "all"

DEFAULT_DAEMON_PORT = 7777


def unavailable_tool_message(name: str, tool_set: str) -> str:
    """Why a tool a client asked for is not here.

    A name this server knows but does not offer is not the same as a typo, and saying
    so is what keeps a caller from concluding the functionality does not exist.
    """
    if any(mod.TOOL.name == name for mod in _ALL_TOOLS):
        return (
            f"Tool '{name}' is not available in the '{tool_set}' tool set. "
            "Restart the server without '--tools " + tool_set + "' to enable it."
        )
    return f"Unknown tool: {name}"


def _is_daemon_running(port: int) -> bool:
    import socket

    try:
        with socket.create_connection(("localhost", port), timeout=0.5):
            return True
    except OSError:
        return False


class DiscoPopMCPServer:
    def __init__(self, debug: bool = False, tool_set: str = DEFAULT_TOOL_SET):
        self.server = Server("discopop_mcp_server", instructions=_SERVER_INSTRUCTIONS)
        self.debug = debug
        self.tool_set = tool_set
        self._tools = TOOL_SETS[tool_set]
        _setup_logging(debug=debug)
        self._ctx = ToolContext(debug=debug)
        self._register_tools()

    def _register_tools(self) -> None:
        _dispatch: dict[str, Callable[[dict[str, Any], ToolContext], list[TextContent]]] = {
            mod.TOOL.name: mod.handle for mod in self._tools
        }

        _schemas: dict[str, dict[str, Any]] = {mod.TOOL.name: mod.TOOL.inputSchema for mod in self._tools}

        # validate_input=False, because the SDK's validation is stricter than
        # this server needs to be: a model that sends apply="true" instead of
        # apply=true means the same thing, and rejecting it costs the whole
        # interaction (see mcp_server/argument_coercion.py). The arguments are
        # coerced towards the declared schema and *then* validated here, so a
        # call that is genuinely wrong is still refused -- with a message naming
        # the argument and the type expected, which the SDK's does not.
        @self.server.call_tool(validate_input=False)  # type: ignore[misc, untyped-decorator]
        async def handle_tool_call(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            handler = _dispatch.get(name)
            if not handler:
                self._ctx.log_call(name, arguments)
                error_msg = unavailable_tool_message(name, self.tool_set)
                logger.error(error_msg)
                raise Exception(error_msg)

            schema = _schemas.get(name)
            arguments, coerced = coerce_arguments(arguments, schema)
            if coerced:
                logger.info(
                    "↳ Coerced argument(s) of %s to the declared types: %s",
                    name,
                    ", ".join(f"{k} ({v})" for k, v in sorted(coerced.items())),
                )
            # Logged after coercion, so the record shows the call as it ran.
            self._ctx.log_call(name, arguments)
            invalid = validation_error(name, arguments, schema)
            if invalid:
                logger.error(invalid)
                raise Exception(invalid)

            params_summary = "".join(f"\n\t{k}={v!r}" for k, v in (arguments or {}).items() if k != "script_body")
            logger.info(f"▶ Executing: {name}({params_summary})")
            start_time = time.time()
            try:
                result = handler(arguments, self._ctx)
                elapsed = time.time() - start_time
                # Raise on tool errors so the MCP client receives isError=true.
                # The exception message is the JSON payload, preserving all error detail.
                if result:
                    try:
                        data = json.loads(result[0].text)
                        if isinstance(data, dict) and data.get("status") == "error":
                            logger.info(f"✗ Failed: {name} ({elapsed:.2f}s)")
                            raise Exception(result[0].text)
                    except json.JSONDecodeError:
                        pass
                logger.info(f"✓ Completed: {name} ({elapsed:.2f}s)")
                return result
            except Exception:
                elapsed = time.time() - start_time
                logger.info(f"✗ Failed: {name} ({elapsed:.2f}s)")
                raise

        @self.server.list_tools()  # type: ignore[misc, untyped-decorator]
        async def list_tools() -> list[Tool]:
            tools = [mod.TOOL for mod in self._tools]
            logger.debug(f"Listed {len(tools)} available tools (tool set: {self.tool_set})")
            return tools

    async def run(self) -> None:
        """Run the server using stdio transport."""
        from mcp.server.stdio import stdio_server

        logger.info("Starting DiscoPoP MCP Server (stdio mode)")
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(read_stream, write_stream, self.server.create_initialization_options())


class DiscoPopMCPProxy:
    """Default stdio entry point.

    On the first tool call the proxy checks whether a daemon is already
    listening on ``daemon_port``. If one is found, a single ClientSession is
    kept open for the lifetime of this process and all subsequent tool calls
    are forwarded through it — giving the daemon's ToolContext a chance to
    keep expensive data structures (e.g. DetectionResult) in memory between
    calls and across sessions.

    The proxy never spawns a daemon on its own. To use the daemon, start it
    manually before launching the MCP client::

        discopop_mcp_server --daemon [--daemon-port PORT] [--debug]

    If no daemon is reachable, every tool call runs inline inside this process.
    The server is fully functional in both modes.
    """

    def __init__(self, daemon_port: int = DEFAULT_DAEMON_PORT, debug: bool = False, tool_set: str = DEFAULT_TOOL_SET):
        self.daemon_port = daemon_port
        self.debug = debug
        self.tool_set = tool_set
        self._tools = TOOL_SETS[tool_set]
        _setup_logging(debug=debug)
        self._session: Optional[Any] = None  # mcp.client.session.ClientSession when connected
        # Inline fallback components (used when daemon is unavailable)
        self._ctx = ToolContext(debug=debug)
        self._dispatch: dict[str, Callable[[dict[str, Any], ToolContext], list[TextContent]]] = {
            mod.TOOL.name: mod.handle for mod in self._tools
        }
        self.server = Server("discopop_mcp_server", instructions=_SERVER_INSTRUCTIONS)
        # Lazy daemon connection state
        self._tg: Optional[Any] = None  # anyio task group set by run()
        self._daemon_init_started: bool = False
        self._daemon_session_ready: Optional[asyncio.Event] = None
        self._register_tools()

    def _register_tools(self) -> None:
        @self.server.list_tools()  # type: ignore[misc, untyped-decorator]
        async def list_tools() -> list[Tool]:
            # Tool list is static — no daemon connection needed for discovery. The proxy
            # filters it itself: the daemon it forwards to may have been started with a
            # different tool set, and what this client may call is decided here.
            return [mod.TOOL for mod in self._tools]

        _schemas: dict[str, dict[str, Any]] = {mod.TOOL.name: mod.TOOL.inputSchema for mod in self._tools}

        # The proxy is the default entry point, so this is where a client's
        # arguments are first seen and where strict validation used to reject
        # them. Coercing here rather than only in DiscoPopMCPServer matters: the
        # daemon is never reached for a call the proxy has already refused.
        @self.server.call_tool(validate_input=False)  # type: ignore[misc, untyped-decorator]
        async def handle_tool_call(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            if name not in self._dispatch:
                error_msg = unavailable_tool_message(name, self.tool_set)
                logger.error(error_msg)
                raise Exception(error_msg)
            schema = _schemas.get(name)
            arguments, coerced = coerce_arguments(arguments, schema)
            if coerced:
                logger.info(
                    "↳ Coerced argument(s) of %s to the declared types: %s",
                    name,
                    ", ".join(f"{k} ({v})" for k, v in sorted(coerced.items())),
                )
            invalid = validation_error(name, arguments, schema)
            if invalid:
                logger.error(invalid)
                raise Exception(invalid)
            await self._ensure_daemon()
            if self._session is not None:
                try:
                    result = await self._session.call_tool(name, arguments)
                    return result.content  # type: ignore[no-any-return]
                except Exception:
                    logger.warning(f"Daemon disconnected during {name}, switching to inline execution")
                    self._session = None
            # Inline fallback — identical error-handling to DiscoPopMCPServer
            self._ctx.log_call(name, arguments)
            handler = self._dispatch.get(name)
            if not handler:
                error_msg = unavailable_tool_message(name, self.tool_set)
                logger.error(error_msg)
                raise Exception(error_msg)
            inline_result = handler(arguments, self._ctx)
            if inline_result:
                try:
                    data = json.loads(inline_result[0].text)
                    if isinstance(data, dict) and data.get("status") == "error":
                        raise Exception(inline_result[0].text)
                except json.JSONDecodeError:
                    pass
            return inline_result

    async def _ensure_daemon(self) -> None:
        """Connect to a manually-started daemon on the first tool call. Idempotent.

        Safe to call concurrently: no await between the flag check and the flag
        set, so at most one caller proceeds to initialisation.
        """
        if self._daemon_init_started:
            if self._daemon_session_ready is not None:
                await self._daemon_session_ready.wait()
            return

        self._daemon_init_started = True
        self._daemon_session_ready = asyncio.Event()

        if _is_daemon_running(self.daemon_port) and self._tg is not None:
            self._tg.start_soon(self._daemon_conn)
            await self._daemon_session_ready.wait()
        else:
            logger.debug(f"No daemon on port {self.daemon_port}; using inline execution")
            self._daemon_session_ready.set()

    async def _daemon_conn(self) -> None:
        """Background task that holds the SSE connection to the daemon alive."""
        import anyio
        from mcp.client.session import ClientSession
        from mcp.client.sse import sse_client

        daemon_url = f"http://localhost:{self.daemon_port}/sse"
        try:
            async with sse_client(daemon_url) as (r, w):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    self._session = session
                    logger.info(f"Connected to DiscoPoP MCP daemon on port {self.daemon_port}")
                    if self._daemon_session_ready is not None:
                        self._daemon_session_ready.set()
                    # Keep the session open until cancelled by the stdio loop finishing.
                    await anyio.Event().wait()
        except Exception as e:
            logger.warning(f"Daemon connection error: {e}; remaining calls will use inline execution")
            self._session = None
            if self._daemon_session_ready is not None and not self._daemon_session_ready.is_set():
                self._daemon_session_ready.set()

    async def run(self) -> None:
        import anyio
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read, write):
            async with anyio.create_task_group() as tg:
                self._tg = tg

                async def _stdio_loop() -> None:
                    try:
                        await self.server.run(read, write, self.server.create_initialization_options())
                    finally:
                        tg.cancel_scope.cancel()

                tg.start_soon(_stdio_loop)


def _run_daemon(port: int, debug: bool, tool_set: str = DEFAULT_TOOL_SET) -> None:
    """Run as a persistent SSE daemon that keeps ToolContext (and its caches) alive."""
    import uvicorn
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.routing import Mount, Route

    from mcp.server.sse import SseServerTransport

    mcp_instance = DiscoPopMCPServer(debug=debug, tool_set=tool_set)
    sse = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await mcp_instance.server.run(
                streams[0],
                streams[1],
                mcp_instance.server.create_initialization_options(),
            )
        return Response()

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    logger.info(f"Starting DiscoPoP MCP daemon on port {port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def main() -> None:
    import argparse

    agent_choices = list(MCPSetup.AGENTS.keys())

    parser = argparse.ArgumentParser(
        description="DiscoPoP MCP Server - Exposes DiscoPoP functionality to Claude",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  %(prog)s                             # Start server (inline execution, no daemon)
  %(prog)s --debug                     # Start with debug logging
  %(prog)s --daemon                    # Start a persistent daemon for a live console
  %(prog)s --daemon --daemon-port 8888 # Daemon on a custom port
  %(prog)s --tools analysis            # Hide the project setup tools
  %(prog)s --setup <agent>             # Configure a specific agent
  %(prog)s --setup <agent> --debug     # Configure with debug logging enabled
  %(prog)s --setup-all                 # Configure all agents
  %(prog)s --verify <agent>            # Verify agent setup
  %(prog)s --status                    # Show current setup status

Optional daemon workflow (for a live request console):
  Run the daemon in a terminal of your choice before starting the MCP client:
    %(prog)s --daemon
  The server will forward all tool calls to the daemon automatically.
  Stop the daemon at any time by pressing Ctrl+C in that terminal.

Available agents: {', '.join(agent_choices)}
        """,
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as a persistent SSE daemon (keeps ToolContext alive; connect via --daemon-port)",
    )
    parser.add_argument(
        "--tools",
        choices=sorted(TOOL_SETS),
        default=DEFAULT_TOOL_SET,
        help=(
            "Which tools to expose. 'all' (default) offers every tool; 'analysis' leaves out "
            "the project setup tools (initialize_discopop_directory, set_compile_script, "
            "create_execution_configuration) — use it against a project that is already "
            "configured, so those tools can neither be listed nor called"
        ),
    )
    parser.add_argument(
        "--daemon-port",
        type=int,
        default=DEFAULT_DAEMON_PORT,
        metavar="PORT",
        help=f"Port used by the daemon (and checked by the proxy). Default: {DEFAULT_DAEMON_PORT}",
    )

    setup_group = parser.add_argument_group("setup")
    setup_group.add_argument(
        "--setup",
        choices=agent_choices,
        metavar="AGENT",
        help=f"Configure MCP server for a specific agent (choices: {', '.join(agent_choices)})",
    )
    setup_group.add_argument(
        "--setup-all",
        action="store_true",
        help="Configure MCP server for all available agents",
    )
    setup_group.add_argument(
        "--verify",
        choices=agent_choices,
        metavar="AGENT",
        help="Verify MCP server setup for a specific agent",
    )
    setup_group.add_argument(
        "--status",
        action="store_true",
        help="Show current setup status",
    )
    setup_group.add_argument(
        "--full-path",
        action="store_true",
        help="Use full path to discopop_mcp_server instead of just the command name",
    )
    setup_group.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output during setup",
    )

    args = parser.parse_args()

    is_setup_mode = any([args.setup, args.setup_all, args.verify, args.status])

    if is_setup_mode:
        setup = MCPSetup(verbose=args.verbose)
        try:
            if args.status:
                setup.show_status()
                sys.exit(0)

            if args.setup:
                success = setup.setup_agent(args.setup, use_debug=args.debug, use_full_path=args.full_path)
                sys.exit(0 if success else 1)

            if args.setup_all:
                all_success = all(
                    setup.setup_agent(
                        agent, use_debug=args.debug, use_full_path=args.full_path, skip_if_not_installed=True
                    )
                    for agent in MCPSetup.AGENTS
                )
                sys.exit(0 if all_success else 1)

            if args.verify:
                success = setup.verify_setup(args.verify)
                sys.exit(0 if success else 1)

        except KeyboardInterrupt:
            print("Setup cancelled by user")
            sys.exit(130)
        except Exception as e:
            print(f"Setup failed: {e}", file=sys.stderr)
            if args.verbose:
                import traceback

                traceback.print_exc()
            sys.exit(1)
    elif args.daemon:
        try:
            _run_daemon(args.daemon_port, args.debug, args.tools)
        except KeyboardInterrupt:
            logger.info("Daemon shutting down...")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Daemon fatal error: {e}", exc_info=True)
            sys.exit(1)
    else:
        proxy = DiscoPopMCPProxy(daemon_port=args.daemon_port, debug=args.debug, tool_set=args.tools)
        try:
            asyncio.run(proxy.run())
        except KeyboardInterrupt:
            logger.info("Server shutting down...")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            sys.exit(1)


if __name__ == "__main__":
    main()

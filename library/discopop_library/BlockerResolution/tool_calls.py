# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The tool calls of an agent, from the event stream of its backend: which files it read, what it searched for and
what it changed. Recorded with the transcripts, so that a claim like "I read the declaration" can be checked."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from discopop_library.PatchRepair.llm_backends.base import iter_json_objects

# the argument which says the most about a call, in this order
_KEY_ARGUMENTS = ("file_path", "filePath", "function", "path", "pattern", "command", "url", "query")
# the arguments which name a file
_PATH_ARGUMENTS = ("file_path", "filePath", "path")
# tools which show the agent the content of a file: they count as having opened it. An edit needs the file read
# before (claude refuses it otherwise), so it counts, too. Not counted: searches (they show lines, not the file),
# Write (it replaces a file without showing it) and DiscoPoP's MCP tools (they answer about a file, they do not show
# it; available and recorded all the same)
_OPENING_TOOLS = ("read", "view", "edit", "multiedit")


@dataclass(frozen=True)
class ToolCall:
    name: str
    argument: str
    # the files (or directories) the call names
    paths: Tuple[str, ...] = field(default=(), compare=False)
    # the backend reported the call as failed (e.g. a Read of a file that does not exist)
    failed: bool = field(default=False, compare=False)

    def opens_files(self) -> bool:
        """whether the call showed the content of the files it names"""
        return not self.failed and self.name.lower() in _OPENING_TOOLS

    def __str__(self) -> str:
        return self.name + (" " + self.argument if self.argument else "")


def _walk(node: Any) -> Iterator[Dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def _argument(arguments: Any) -> str:
    if not isinstance(arguments, dict):
        return ""
    values = {k: v for k in _KEY_ARGUMENTS if isinstance(v := arguments.get(k), str) and v}
    if "pattern" in values:
        # a search: what, and where
        return values["pattern"] + (" in " + values["path"] if "path" in values else "")
    return next(iter(values.values()), "")


def _paths(arguments: Any) -> Tuple[str, ...]:
    if not isinstance(arguments, dict):
        return ()
    return tuple(v for k in _PATH_ARGUMENTS if isinstance(v := arguments.get(k), str) and v)


def _is_opencode_call(node: Dict[str, Any]) -> bool:
    return isinstance(node.get("tool"), str) and ("state" in node or "callID" in node)


def _call(node: Dict[str, Any]) -> Optional[ToolCall]:
    # claude: {"type": "tool_use", "name": "Read", "input": {"file_path": ...}}
    if node.get("type") == "tool_use" and isinstance(node.get("name"), str):
        return ToolCall(node["name"], _argument(node.get("input")), _paths(node.get("input")))
    # opencode: {"type": "tool", "tool": "read", "callID": ..., "state": {"input": {"filePath": ...}}}; written
    # against no promised schema, like the backend's own parser, and not yet checked against a real run
    if _is_opencode_call(node):
        state = node.get("state")
        arguments = state.get("input") if isinstance(state, dict) else None
        return ToolCall(node["tool"], _argument(arguments), _paths(arguments))
    return None


def _key(node: Dict[str, Any]) -> str:
    return str(node.get("id") or node.get("callID") or node.get("callId") or "")


def _failed_calls(objects: List[Any]) -> Set[str]:
    """the ids of the calls the stream reports as failed: claude answers a call with a tool_result of the call's id
    and is_error true; opencode repeats the call with state.status "error" """
    failed: Set[str] = set()
    for obj in objects:
        for node in _walk(obj):
            if node.get("type") == "tool_result" and node.get("is_error") is True and node.get("tool_use_id"):
                failed.add(str(node["tool_use_id"]))
            elif _is_opencode_call(node):
                state = node.get("state")
                if isinstance(state, dict) and state.get("status") == "error" and _key(node):
                    failed.add(_key(node))
    return failed


def tool_calls(raw: str) -> List[ToolCall]:
    """the tool calls in the stream, in their order, each once (streams repeat a call while it progresses), marked
    as failed where the stream says so"""
    objects = list(iter_json_objects(raw))
    failed = _failed_calls(objects)
    calls: List[ToolCall] = []
    seen: set[str] = set()
    for obj in objects:
        for node in _walk(obj):
            call = _call(node)
            if call is None:
                continue
            key = _key(node)
            if key:
                if key in seen:
                    continue
                seen.add(key)
                if key in failed:
                    call = ToolCall(call.name, call.argument, call.paths, failed=True)
            calls.append(call)
    return calls


def mcp_server_failed(raw: str, server: str) -> bool:
    """whether the stream reports that the MCP server of this name failed to start (claude's init event:
    {"type": "system", "subtype": "init", "mcp_servers": [{"name": ..., "status": "failed"}]}). Only an explicit
    failure counts: a pending or unknown status does not."""
    for obj in iter_json_objects(raw):
        for node in _walk(obj):
            servers = node.get("mcp_servers")
            if node.get("type") != "system" or not isinstance(servers, list):
                continue
            for entry in servers:
                if isinstance(entry, dict) and entry.get("name") == server and entry.get("status") == "failed":
                    return True
    return False


def opened_files(calls: List[ToolCall], workdir: str) -> Set[str]:
    """the files the calls showed the content of, relative to the copy the agent worked in (paths outside it are
    left out; relative paths are taken as relative to it)"""
    root = os.path.realpath(workdir)
    opened: Set[str] = set()
    for call in calls:
        if not call.opens_files():
            continue
        for path in call.paths:
            absolute = os.path.realpath(path if os.path.isabs(path) else os.path.join(root, path))
            relative = os.path.relpath(absolute, root)
            if relative != ".." and not relative.startswith(".." + os.sep):
                opened.add(relative)
    return opened

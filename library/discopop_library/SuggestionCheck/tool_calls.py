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

from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Optional

from discopop_library.PatchRepair.llm_backends.base import iter_json_objects

# the argument which says the most about a call, in this order
_KEY_ARGUMENTS = ("file_path", "filePath", "path", "pattern", "command", "url", "query")


@dataclass(frozen=True)
class ToolCall:
    name: str
    argument: str

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


def _call(node: Dict[str, Any]) -> Optional[ToolCall]:
    # claude: {"type": "tool_use", "name": "Read", "input": {"file_path": ...}}
    if node.get("type") == "tool_use" and isinstance(node.get("name"), str):
        return ToolCall(node["name"], _argument(node.get("input")))
    # opencode: {"type": "tool", "tool": "read", "callID": ..., "state": {"input": {"filePath": ...}}}; written
    # against no promised schema, like the backend's own parser, and not yet checked against a real run
    if isinstance(node.get("tool"), str) and ("state" in node or "callID" in node):
        state = node.get("state")
        return ToolCall(node["tool"], _argument(state.get("input") if isinstance(state, dict) else None))
    return None


def tool_calls(raw: str) -> List[ToolCall]:
    """the tool calls in the stream, in their order, each once (streams repeat a call while it progresses)"""
    calls: List[ToolCall] = []
    seen: set[str] = set()
    for obj in iter_json_objects(raw):
        for node in _walk(obj):
            call = _call(node)
            if call is None:
                continue
            key = str(node.get("id") or node.get("callID") or node.get("callId") or "")
            if key:
                if key in seen:
                    continue
                seen.add(key)
            calls.append(call)
    return calls

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The tool calls of an agent, from its event stream, and their record in the transcripts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from discopop_library.BlockerResolution.check import AgentReply, Budget, check_suggestion
from discopop_library.BlockerResolution.conftest import Project, json_answer
from discopop_library.BlockerResolution.tool_calls import ToolCall, tool_calls


def _claude_events(workdir: str, answer: str) -> str:
    events: List[Dict[str, Any]] = [
        {"type": "system", "subtype": "init", "session_id": "s1"},
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "text", "text": "Let me look."},
                    {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": workdir + "/code.cpp"}},
                    {"type": "tool_use", "id": "t2", "name": "Grep", "input": {"pattern": "state", "path": "."}},
                ]
            },
        },
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "..."}]}},
        {"type": "result", "result": answer, "session_id": "s1"},
    ]
    return "\n".join(json.dumps(e) for e in events)


def test_the_tool_calls_of_claude() -> None:
    assert tool_calls(_claude_events("/w", "done")) == [ToolCall("Read", "/w/code.cpp"), ToolCall("Grep", "state in .")]


def test_the_tool_calls_of_opencode_once_each() -> None:
    part = {"type": "tool", "tool": "read", "callID": "c1", "state": {"input": {"filePath": "/w/a.cpp"}}}
    running = dict(part, state={"status": "running", "input": {"filePath": "/w/a.cpp"}})
    raw = "\n".join(json.dumps({"type": "tool_use", "part": p}) for p in (part, running))
    # the "tool_use" event envelope carries no name: only the part counts, once
    assert tool_calls(raw) == [ToolCall("read", "/w/a.cpp")]


def test_no_events_no_tool_calls() -> None:
    assert tool_calls("") == []
    assert tool_calls("plain text answer") == []


def test_the_transcripts_list_the_tool_calls(project: Project, tmp_path: Path) -> None:
    def agent(prompt: str, session: Optional[str], workdir: str) -> AgentReply:
        answer = json_answer(verdict="unsure", reason="?")
        return AgentReply(answer, True, session="s1", events=_claude_events(workdir, answer))

    artifacts = tmp_path / "transcripts"
    outcome = check_suggestion(
        project.suggestion, project.files, str(project.root), agent, None, Budget(), str(artifacts)
    )
    assert outcome.tool_calls == 2
    assert outcome.to_dict()["tool_calls"] == 2
    # relative to the copy, which is gone by now
    assert (artifacts / "check_1_0_tools.txt").read_text() == "Read code.cpp\nGrep state in .\n"
    assert '"tool_use"' in (artifacts / "check_1_0_events.jsonl").read_text()


def test_without_events_nothing_extra_is_written(project: Project, tmp_path: Path) -> None:
    def agent(prompt: str, session: Optional[str], workdir: str) -> AgentReply:
        return AgentReply(json_answer(verdict="unsure", reason="?"), True)

    artifacts = tmp_path / "transcripts"
    outcome = check_suggestion(
        project.suggestion, project.files, str(project.root), agent, None, Budget(), str(artifacts)
    )
    assert outcome.tool_calls == 0
    assert sorted(p.name for p in artifacts.iterdir()) == ["check_1_0_answer.txt", "check_1_0_prompt.txt"]

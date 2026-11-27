# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""DiscoPoP's data for the agents, and the check that they opened the files of the blockers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from discopop_library.SuggestionCheck import discopop_tools
from discopop_library.SuggestionCheck.check import (
    STATE_APPROVED,
    STATE_REJECTED,
    AgentReply,
    Budget,
    CheckOptions,
    check_suggestion,
)
from discopop_library.SuggestionCheck.conftest import (
    AGREE,
    APPROVAL,
    APPROVED_SOURCE,
    Project,
    ScriptedAgent,
    json_answer,
)
from discopop_library.SuggestionCheck.discopop_tools import DiscoPoPTools, is_discopop_tool

# the real probe, before conftest's autouse fixture replaces it
from discopop_library.SuggestionCheck.discopop_tools import supports_binding as real_supports_binding
from discopop_library.SuggestionCheck.prompts import DISCOPOP_TOOLS_OFF, DISCOPOP_TOOLS_ON
from discopop_library.SuggestionCheck.run import EDIT, READ, restricted
from discopop_library.SuggestionCheck.tool_calls import ToolCall, mcp_server_failed, opened_files, tool_calls

TOOLS = DiscoPoPTools(["/bin/discopop_mcp_server"], "/the/project")


def test_claude_gets_only_the_server_and_only_the_described_tools() -> None:
    arguments = restricted({"backend": "claude"}, READ, TOOLS)["extra_args"]
    assert "--strict-mcp-config" in arguments
    config = json.loads(arguments[arguments.index("--mcp-config") + 1])
    assert config == {
        "mcpServers": {
            "discopop": {
                "type": "stdio",
                "command": "/bin/discopop_mcp_server",
                "args": ["--tools", "readonly", "--project", "/the/project"],
            }
        }
    }
    allowed = arguments[arguments.index("--allowedTools") + 1].split(",")
    assert allowed == ["mcp__discopop__get_side_effects", "mcp__discopop__explain_parallelization"]
    # the file tools stay restricted as before
    assert arguments[:2] == ["--tools", "Read,Grep,Glob"]


def test_without_the_server_nothing_is_added() -> None:
    assert "--mcp-config" not in restricted({"backend": "claude"}, EDIT)["extra_args"]


def test_opencode_gets_the_server_with_its_other_tools_off() -> None:
    profile = restricted({"backend": "opencode"}, EDIT, TOOLS)
    config = json.loads(profile["env"]["OPENCODE_CONFIG_CONTENT"])
    assert config["mcp"]["discopop"]["command"] == [
        "/bin/discopop_mcp_server",
        "--tools",
        "readonly",
        "--project",
        "/the/project",
    ]
    assert config["tools"] == {
        "discopop_*": False,
        "discopop_get_side_effects": True,
        "discopop_explain_parallelization": True,
    }
    assert config["permission"]["bash"] == "deny"


def test_the_server_is_found_as_a_command_or_as_a_module(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    found = discopop_tools.locate("/p")
    assert found is not None and found.command == ["/usr/bin/discopop_mcp_server"]
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert discopop_tools.locate("/p") is None


def test_an_installed_server_too_old_to_be_bound_is_not_used(monkeypatch: pytest.MonkeyPatch) -> None:
    probed: List[List[str]] = []

    def supports(command: List[str], env: Optional[Dict[str, str]] = None) -> bool:
        probed.append(command)
        return command[0] != "/usr/bin/discopop_mcp_server"

    monkeypatch.setattr(discopop_tools, "supports_binding", supports)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    found = discopop_tools.locate("/p")
    # the module of this Python instead
    assert found is not None and found.command[1:] == ["-m", "mcp_server.server"]
    assert [c[0] for c in probed] == ["/usr/bin/discopop_mcp_server", found.command[0]]
    # neither knows the options: unavailable
    monkeypatch.setattr(discopop_tools, "supports_binding", lambda command, env=None: False)
    assert discopop_tools.locate("/p") is None


def test_the_probe_reads_the_help_of_the_server(tmp_path: Path) -> None:
    def server(name: str, help_text: str) -> List[str]:
        script = tmp_path / name
        script.write_text("#!/bin/sh\necho '" + help_text + "'\n")
        script.chmod(0o755)
        return [str(script)]

    assert real_supports_binding(server("new", "--tools {all,analysis,readonly} --project PATH"))
    assert not real_supports_binding(server("old", "--tools {all,analysis} --daemon"))
    assert not real_supports_binding([str(tmp_path / "missing")])


def test_tool_names_of_the_server() -> None:
    assert is_discopop_tool("mcp__discopop__get_side_effects")
    assert is_discopop_tool("discopop_get_side_effects")
    assert not is_discopop_tool("Read")


def test_the_prompt_says_whether_the_data_can_be_queried(project: Project) -> None:
    for enabled, text in ((True, DISCOPOP_TOOLS_ON), (False, DISCOPOP_TOOLS_OFF)):
        agent = ScriptedAgent([json_answer(verdict="unsure", reason="?")])
        check_suggestion(
            project.suggestion,
            project.files,
            str(project.root),
            agent,
            None,
            Budget(),
            options=CheckOptions(discopop_tools=enabled),
        )
        assert text in agent.prompts[0]


def test_opened_files_are_those_shown_relative_to_the_copy(tmp_path: Path) -> None:
    calls = [
        ToolCall("Read", "", (str(tmp_path / "src" / "a.cpp"),)),
        ToolCall("Read", "", ("b.h",)),
        ToolCall("Edit", "", ("f.cpp",)),  # an edit needs the file read before
        ToolCall("Grep", "", (str(tmp_path / "c.cpp"),)),  # a search shows lines, not the file
        # DiscoPoP's tools answer about a file, they do not show it
        ToolCall("mcp__discopop__explain_parallelization", "", ("d.cpp",)),
        ToolCall("Write", "", ("g.cpp",)),  # replaces a file without showing it
        ToolCall("Read", "", ("h.cpp",), failed=True),  # e.g. no such file
        ToolCall("Read", "", ("/elsewhere/e.cpp",)),
    ]
    assert opened_files(calls, str(tmp_path)) == {"src/a.cpp", "b.h", "f.cpp"}


def test_failed_calls_are_marked_from_the_stream() -> None:
    claude = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "1", "name": "Read", "input": {}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "1", "is_error": True}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "2", "name": "Read", "input": {}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "2", "is_error": False}]}},
    ]
    assert [c.failed for c in tool_calls("\n".join(json.dumps(e) for e in claude))] == [True, False]
    # opencode repeats a call while it progresses: the failure comes with a later repeat
    opencode = [
        {"type": "tool", "tool": "read", "callID": "a", "state": {"status": "running", "input": {"filePath": "x"}}},
        {"type": "tool", "tool": "read", "callID": "a", "state": {"status": "error", "input": {"filePath": "x"}}},
        {"type": "tool", "tool": "read", "callID": "b", "state": {"status": "completed", "input": {"filePath": "y"}}},
    ]
    calls = tool_calls("\n".join(json.dumps(e) for e in opencode))
    assert [(c.paths, c.failed) for c in calls] == [(("x",), True), (("y",), False)]


def test_a_failed_read_of_the_blocker_file_does_not_count(project: Project) -> None:
    events = [
        {"type": "tool_use", "id": "1", "name": "Read", "input": {"file_path": "code.cpp"}},
        {"type": "tool_result", "tool_use_id": "1", "is_error": True},
        {"type": "tool_use", "id": "2", "name": "mcp__discopop__get_side_effects", "input": {"file_path": "code.cpp"}},
    ]

    def agent(prompt: str, session: Optional[str], workdir: str) -> AgentReply:
        (Path(workdir) / "code.cpp").write_text(APPROVED_SOURCE)
        return AgentReply(APPROVAL, True, session="s", events=json.dumps({"content": events}))

    outcome = check_suggestion(
        project.suggestion, project.files, str(project.root), agent, None, Budget(prompts=1, retries=0)
    )
    assert outcome.state != STATE_APPROVED
    assert "Not opened: code.cpp" in outcome.gates[0]["detail"]


def _events(*paths: str) -> str:
    content = [
        {"type": "tool_use", "id": str(i), "name": "Read", "input": {"file_path": p}} for i, p in enumerate(paths)
    ]
    return json.dumps({"type": "assistant", "message": {"content": content}})


def _agent(steps: List[Any]) -> Any:
    """steps: (paths read, answer, code written or None) per call"""
    remaining = list(steps)
    prompts: List[str] = []

    def agent(prompt: str, session: Optional[str], workdir: str) -> AgentReply:
        prompts.append(prompt)
        paths, answer, code = remaining.pop(0)
        if code is not None:
            (Path(workdir) / "code.cpp").write_text(code)
        return AgentReply(answer, True, session="s", events=_events(*[str(Path(workdir) / p) for p in paths]))

    agent.prompts = prompts  # type: ignore[attr-defined]
    return agent


def _check(project: Project, agent: Any, reviewer: Any = None) -> Any:
    return check_suggestion(project.suggestion, project.files, str(project.root), agent, reviewer, Budget())


def test_an_approval_without_opening_the_blocker_files_is_sent_back(project: Project) -> None:
    agent = _agent([([], APPROVAL, APPROVED_SOURCE), (["code.cpp"], APPROVAL, None)])
    outcome = _check(project, agent, ScriptedAgent([AGREE]))
    assert outcome.state == STATE_APPROVED
    assert outcome.read_blocker_files is True
    assert "Not opened: code.cpp" in outcome.gates[0]["detail"]
    assert "Not opened: code.cpp" in agent.prompts[1]


def test_a_rejection_records_whether_the_blocker_files_were_opened(project: Project) -> None:
    outcome = _check(project, _agent([([], json_answer(verdict="rejected", reason="no"), None)]))
    assert (outcome.state, outcome.read_blocker_files) == (STATE_REJECTED, False)
    assert outcome.to_dict()["read_blocker_files"] is False


def test_without_tool_calls_reported_the_reading_cannot_be_told(project: Project) -> None:
    def agent(prompt: str, session: Optional[str], workdir: str) -> AgentReply:
        (Path(workdir) / "code.cpp").write_text(APPROVED_SOURCE)
        return AgentReply(APPROVAL, True, session="s")

    outcome = _check(project, agent, ScriptedAgent([AGREE]))
    assert (outcome.state, outcome.read_blocker_files) == (STATE_APPROVED, None)


def test_the_run_records_whether_the_data_was_available(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    from discopop_library.SuggestionCheck import run as run_module
    from discopop_library.SuggestionCheck.test_run import _arguments, _dot_discopop, _factory

    dot = _dot_discopop(project, [5])
    monkeypatch.setattr(run_module, "locate_discopop_tools", lambda project: None)
    factory = _factory({EDIT: [json_answer(verdict="rejected", reason="no")], READ: []})
    assert run_module.run(_arguments(dot), factory) == 0
    results: Dict[str, Any] = json.loads((dot / "suggestion_check" / "results.json").read_text())
    assert results["discopop_tools"] == "unavailable"


def test_a_server_which_failed_to_start_is_recorded(project: Project, monkeypatch: pytest.MonkeyPatch) -> None:
    from discopop_library.SuggestionCheck import run as run_module
    from discopop_library.SuggestionCheck.test_run import _arguments, _dot_discopop

    init = {"type": "system", "subtype": "init", "mcp_servers": [{"name": "discopop", "status": "failed"}]}
    assert mcp_server_failed(json.dumps(init), "discopop")
    assert not mcp_server_failed(
        json.dumps({**init, "mcp_servers": [{"name": "discopop", "status": "pending"}]}), "discopop"
    )
    dot = _dot_discopop(project, [5])
    monkeypatch.setattr(run_module, "locate_discopop_tools", lambda project: TOOLS)

    def factory(mode: str) -> Any:
        def agent(prompt: str, session: Optional[str], workdir: str) -> AgentReply:
            return AgentReply(json_answer(verdict="rejected", reason="no"), True, events=json.dumps(init))

        return agent

    assert run_module.run(_arguments(dot), factory) == 0
    results: Dict[str, Any] = json.loads((dot / "suggestion_check" / "results.json").read_text())
    assert results["discopop_tools"] == "failed"
    assert results["suggestions"][0]["discopop_tools"] == "failed"


def test_the_server_is_bound_to_the_project_root_which_holds_the_data(
    project: Project, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from discopop_library.SuggestionCheck import run as run_module
    from discopop_library.SuggestionCheck.test_run import _arguments, _dot_discopop

    dot = _dot_discopop(project, [5])
    located: List[str] = []

    def locate(root: str) -> DiscoPoPTools:
        located.append(root)
        return TOOLS

    monkeypatch.setattr(run_module, "locate_discopop_tools", locate)
    factory = lambda mode: ScriptedAgent([json_answer(verdict="rejected", reason="no")])  # noqa: E731
    # the .discopop of the project root: bound to the root
    assert run_module.run(_arguments(dot, project_root=str(project.root)), factory) == 0
    assert located == [str(project.root)]
    # data elsewhere than <root>/.discopop: the server would read other data, so it is not used
    other = tmp_path / "other_root"
    other.mkdir()
    assert run_module.run(_arguments(dot, project_root=str(other)), factory) == 0
    assert located == [str(project.root)]
    results: Dict[str, Any] = json.loads((dot / "suggestion_check" / "results.json").read_text())
    assert results["discopop_tools"] == "unavailable"

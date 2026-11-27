# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""A tiny project with one unsure loop and a scripted agent which may change its workspace, for testing the check
without a model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Union

import pytest

from discopop_library.SuggestionCheck.check import AgentReply
from discopop_library.SuggestionCheck.facts import SourceFiles
from discopop_library.SuggestionCheck.unsure import Access, Blocker, Location, UnsureSuggestion

SOURCE = """#include <vector>

static unsigned state = 1u;

int main() {
  std::vector<unsigned> drawn(100);
  for (int i = 0; i < 100; i++) {
    state = state * 3u + 1u;
    drawn[i] = state;
  }
  return 0;
}
"""
LOOP_LINE = 7
PARALLEL = "  #pragma omp parallel for\n"


def with_line_before(text: str, line: int, inserted: str) -> str:
    lines = text.splitlines(keepends=True)
    return "".join(lines[: line - 1] + [inserted] + lines[line - 1 :])


# the code of an approval: the loop's directive and a change elsewhere
APPROVED_SOURCE = with_line_before(
    with_line_before(SOURCE, LOOP_LINE, PARALLEL), 3, "// each thread has its own state\n"
)


@pytest.fixture(autouse=True)
def _no_server_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """locate() does not start the MCP server to probe it (tests of the probe use the function directly)"""
    from discopop_library.SuggestionCheck import discopop_tools

    monkeypatch.setattr(discopop_tools, "supports_binding", lambda command, env=None: True)


@dataclass
class Project:
    root: Path
    files: SourceFiles
    suggestion: UnsureSuggestion


@pytest.fixture
def project(tmp_path: Path) -> Project:
    root = tmp_path / "project"
    root.mkdir()
    source = root / "code.cpp"
    source.write_text(SOURCE)
    (root / "README").write_text("not a source file\n")
    files = SourceFiles({1: source}, str(root))
    blocker = Blocker("RAW", Location(1, 8), Location(1, 8), "dynamic", (Access("_ZL5state", "42"),))
    suggestion = UnsureSuggestion(
        pattern_id=5,
        type="do_all",
        start=Location(1, LOOP_LINE),
        end=Location(1, 10),
        pragma="#pragma omp parallel for",
        blockers=[blocker],
        data={"first_private": ["drawn"], "shared": [], "reduction": []},
    )
    return Project(root, files, suggestion)


# what a scripted turn does: answer with a text, change the workspace and answer, or not answer at all (None)
Step = Union[str, Callable[[Path], str], None]


def edits(code: str, answer: str, name: str = "code.cpp") -> Callable[[Path], str]:
    """a turn which writes code to the file name of its workspace and answers"""

    def step(workdir: Path) -> str:
        (workdir / name).write_text(code)
        return answer

    return step


class ScriptedAgent:
    """takes the given turns in order"""

    def __init__(self, steps: List[Step], sessions: bool = True) -> None:
        self.steps = list(steps)
        # without, the agent reports no session, so a conversation cannot be continued
        self.with_sessions = sessions
        self.prompts: List[str] = []
        self.sessions: List[Optional[str]] = []
        self.workdirs: List[str] = []
        # the code of code.cpp in the workspace, when the turn began
        self.seen_code: List[str] = []

    def __call__(self, prompt: str, session: Optional[str], workdir: str) -> AgentReply:
        self.prompts.append(prompt)
        self.sessions.append(session)
        self.workdirs.append(workdir)
        source = Path(workdir) / "code.cpp"
        self.seen_code.append(source.read_text() if source.exists() else "")
        if not self.steps:
            raise AssertionError("the agent was asked more often than scripted")
        step = self.steps.pop(0)
        if step is None:
            return AgentReply(text="", answered=False, failure="unreachable")
        text = step(Path(workdir)) if callable(step) else step
        session_id = "s" + str(len(self.prompts)) if self.with_sessions else None
        return AgentReply(text=text, answered=True, session=session_id)


def json_answer(**fields: object) -> str:
    return "```json\n" + json.dumps(fields) + "\n```"


def approval(
    evidence: Optional[List[str]] = None,
    assumption: str = "the values only need to be random",
    result_differences: str = "none",
) -> Dict[str, object]:
    return {
        "verdict": "approved",
        "assumption": assumption,
        "result_differences": result_differences,
        "blockers": [
            {
                "index": 1,
                "justification": "each thread may use its own sequence",
                "evidence": evidence or ["code.cpp:8"],
            }
        ],
    }


APPROVAL = json_answer(**approval())
AGREE = json_answer(verdict="agree", reason="holds")

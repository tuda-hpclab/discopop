# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""A tiny project with one unsure loop, its plain patch and a scripted agent, for testing the check without a
model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pytest

from discopop_library.PatchGenerator.diffs import get_diffs_from_modified_code
from discopop_library.PatchRepair.patching import _diff_arguments
from discopop_library.PatchRepair.patchset import PatchEntry, PatchSet
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


def diff(files: SourceFiles, file_id: int, modified: str) -> str:
    return get_diffs_from_modified_code(files.file_mapping, {file_id: modified}, _diff_arguments())[file_id]


def with_line_before(text: str, line: int, inserted: str) -> str:
    lines = text.splitlines(keepends=True)
    return "".join(lines[: line - 1] + [inserted] + lines[line - 1 :])


@dataclass
class Project:
    files: SourceFiles
    suggestion: UnsureSuggestion
    plain: PatchSet

    def patch_block(self, modified: str) -> str:
        return "===BEGIN PATCH 1===\n" + diff(self.files, 1, modified) + "\n===END PATCH 1==="


@pytest.fixture
def project(tmp_path: Path) -> Project:
    source = tmp_path / "code.cpp"
    source.write_text(SOURCE)
    files = SourceFiles({1: source}, str(tmp_path))
    blocker = Blocker("RAW", Location(1, 8), Location(1, 8), "dynamic", (Access("_ZL5state", "42"),))
    suggestion = UnsureSuggestion(
        pattern_id=5,
        type="do_all",
        start=Location(1, LOOP_LINE),
        end=Location(1, 10),
        pragma="#pragma omp parallel for",
        blockers=[blocker],
    )
    plain = PatchSet(suggestion_id=5)
    plain.entries[1] = PatchEntry(1, diff(files, 1, with_line_before(SOURCE, LOOP_LINE, PARALLEL)), source)
    return Project(files, suggestion, plain)


class ScriptedAgent:
    """answers with the given texts in turn; None stands for a call without an answer"""

    def __init__(self, answers: List[Optional[str]], sessions: bool = True) -> None:
        self.answers = list(answers)
        # without, the agent reports no session, so a conversation cannot be continued
        self.with_sessions = sessions
        self.prompts: List[str] = []
        self.sessions: List[Optional[str]] = []

    def __call__(self, prompt: str, session: Optional[str]) -> AgentReply:
        self.prompts.append(prompt)
        self.sessions.append(session)
        if not self.answers:
            raise AssertionError("the agent was asked more often than scripted")
        answer = self.answers.pop(0)
        if answer is None:
            return AgentReply(text="", answered=False, failure="unreachable")
        return AgentReply(
            text=answer, answered=True, session="s" + str(len(self.prompts)) if self.with_sessions else None
        )


def json_answer(**fields: object) -> str:
    import json

    return "```json\n" + json.dumps(fields) + "\n```"


def approval(
    evidence: Optional[List[str]] = None, assumption: str = "the values only need to be random"
) -> Dict[str, object]:
    return {
        "verdict": "approved",
        "assumption": assumption,
        "blockers": [
            {
                "index": 1,
                "justification": "each thread may use its own sequence",
                "evidence": evidence or ["code.cpp:8"],
            }
        ],
    }

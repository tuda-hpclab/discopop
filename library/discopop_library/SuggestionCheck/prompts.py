# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The prompts of the check, the review and the follow-up turns (templates in prompts/)."""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from discopop_library.PatchRepair.patchset import PatchSet
from discopop_library.SuggestionCheck.answers import Justification
from discopop_library.SuggestionCheck.facts import SourceFiles, code_excerpts, describe_blockers, describe_suggestion
from discopop_library.SuggestionCheck.prompt_store import PLACEHOLDER, effective_template
from discopop_library.SuggestionCheck.unsure import UnsureSuggestion

_PLACEHOLDER: "re.Pattern[str]" = PLACEHOLDER


def load_template(name: str, prompt_dir: Optional[str] = None) -> str:
    """the template, the project's own version if prompt_dir holds one (see prompt_store)"""
    return effective_template(name, prompt_dir)


def substitute(template: str, values: Dict[str, str]) -> str:
    """fills the {placeholders} of the template in one pass, so braces in the inserted code stay as they are"""
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def patch_text(patch: PatchSet, files: SourceFiles) -> str:
    """the patch with the paths the agent sees, instead of the paths it was computed with"""
    blocks: List[str] = []
    for file_id, entry in sorted(patch.entries.items()):
        name = files.display_path(file_id)
        lines = []
        for line in entry.text.splitlines():
            if line.startswith("--- "):
                line = "--- a/" + name
            elif line.startswith("+++ "):
                line = "+++ b/" + name
            lines.append(line)
        blocks.append("```diff\n" + "\n".join(lines) + "\n```")
    return "\n\n".join(blocks)


DISCOPOP_TOOLS_ON = """DiscoPoP's profiling data of this project can be queried with two tools. They only
read, and always work on this project:

- `get_side_effects` (a function name; a file and a line inside its definition to
  pick one of several): the data the function was observed to read and write
  outside of itself, including through the functions it calls, with the kind of
  each (global, parameter, other) and the lines of the accesses. Use it for the
  functions called on the blocker lines.
- `explain_parallelization` (a file and lines): why DiscoPoP did or did not
  suggest a parallelization for these lines, with the dependencies.

Give `file_path` relative to the project root, like the paths in this prompt (e.g.
`src/a.cpp`): the tools do not know the path of your copy.

Their answers describe the profiled runs: they are evidence, not proof, and do not
replace reading the code. Justifications still cite code (path:line)."""

DISCOPOP_TOOLS_OFF = "DiscoPoP's profiling data is not available in this run: rely on the code."


def discopop_tools_text(enabled: bool) -> str:
    return DISCOPOP_TOOLS_ON if enabled else DISCOPOP_TOOLS_OFF


def check_prompt(
    suggestion: UnsureSuggestion, files: SourceFiles, prompt_dir: Optional[str] = None, discopop_tools: bool = False
) -> str:
    return substitute(
        load_template("check", prompt_dir),
        {
            "description": describe_suggestion(suggestion, files),
            "blockers": describe_blockers(suggestion, files),
            "code": code_excerpts(suggestion, files),
            "discopop_tools": discopop_tools_text(discopop_tools),
        },
    )


def review_prompt(
    suggestion: UnsureSuggestion,
    approved: PatchSet,
    files: SourceFiles,
    assumption: str,
    justifications: List[Justification],
    result_differences: str = "",
    prompt_dir: Optional[str] = None,
    discopop_tools: bool = False,
) -> str:
    return substitute(
        load_template("review", prompt_dir),
        {
            "description": describe_suggestion(suggestion, files),
            "blockers": describe_blockers(suggestion, files),
            "code": code_excerpts(suggestion, files),
            "patch": patch_text(approved, files),
            "assumption": assumption,
            "result_differences": result_differences,
            "discopop_tools": discopop_tools_text(discopop_tools),
            "justifications": "\n\n".join(
                "Blocker " + str(j.index) + ": " + j.text + "\nEvidence: " + ", ".join(j.evidence)
                for j in justifications
            ),
        },
    )


def retry_prompt(failure: str, prompt_dir: Optional[str] = None) -> str:
    return substitute(load_template("retry", prompt_dir), {"failure": failure})

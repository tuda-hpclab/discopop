# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The prompts of the check, the review and the follow-up turns (templates in prompts/)."""

from __future__ import annotations

import os
import re
from typing import Dict, List

from discopop_library.PatchRepair.patchset import PatchSet
from discopop_library.PatchRepair.prompts import strip_license_header
from discopop_library.SuggestionCheck.answers import Justification
from discopop_library.SuggestionCheck.facts import (
    SourceFiles,
    code_excerpts,
    describe_blockers,
    file_list,
    patch_blocks,
)
from discopop_library.SuggestionCheck.unsure import UnsureSuggestion

PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


def load_template(name: str) -> str:
    with open(os.path.join(PROMPT_DIR, name + ".md")) as f:
        return strip_license_header(f.read())


def substitute(template: str, values: Dict[str, str]) -> str:
    """fills the {placeholders} of the template in one pass, so braces in the inserted code stay as they are"""
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), template)


def identity(suggestion: UnsureSuggestion, files: SourceFiles) -> str:
    return (
        "The loop: `"
        + files.display_path(suggestion.start.file_id)
        + "` lines "
        + str(suggestion.start.line)
        + "-"
        + str(suggestion.end.line)
        + " (DiscoPoP suggestion "
        + str(suggestion.pattern_id)
        + ", "
        + str(len(suggestion.blockers))
        + " blocker"
        + ("" if len(suggestion.blockers) == 1 else "s")
        + ")."
    )


def check_prompt(suggestion: UnsureSuggestion, plain: PatchSet, files: SourceFiles) -> str:
    return substitute(
        load_template("check"),
        {
            "identity": identity(suggestion, files),
            "blockers": describe_blockers(suggestion, files),
            "code": code_excerpts(suggestion, files),
            "patch": patch_blocks(plain, files),
            "files": file_list(files),
        },
    )


def review_prompt(
    suggestion: UnsureSuggestion,
    approved: PatchSet,
    files: SourceFiles,
    assumption: str,
    justifications: List[Justification],
) -> str:
    return substitute(
        load_template("review"),
        {
            "identity": identity(suggestion, files),
            "blockers": describe_blockers(suggestion, files),
            "code": code_excerpts(suggestion, files),
            "patch": patch_blocks(approved, files),
            "assumption": assumption,
            "justifications": "\n\n".join(
                "Blocker " + str(j.index) + ": " + j.text + "\nEvidence: " + ", ".join(j.evidence)
                for j in justifications
            ),
        },
    )


def retry_prompt(failure: str) -> str:
    return substitute(load_template("retry"), {"failure": failure})

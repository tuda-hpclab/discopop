# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional

from discopop_library.ArgumentClasses.GeneralArguments import GeneralArguments

VERIFY_NONE = "none"
VERIFY_BUILD = "build"
VERIFY_RUN = "run"
VERIFY_CHOICES = (VERIFY_NONE, VERIFY_BUILD, VERIFY_RUN)


@dataclass
class SuggestionCheckArguments(GeneralArguments):
    """the arguments of discopop_suggestion_check"""

    dot_dp_path: str
    # explicit pattern ids, comma separated; all unsure suggestions without
    suggestions: Optional[str] = None
    # stop after checking this many suggestions; 0: no limit
    max_suggestions: int = 0
    prompts: int = 2
    retries: int = 2
    agent_error_retries: int = 2
    review: bool = True
    # verification of an approval by building / running it; only "none" is implemented so far
    verify: str = VERIFY_NONE
    connection: Optional[str] = None
    backend: Optional[str] = None
    model: Optional[str] = None
    agent_timeout: float = 600.0
    llm_config: Optional[str] = None

    def __post_init__(self) -> None:
        problems: List[str] = []
        if not os.path.isdir(self.dot_dp_path):
            problems.append("no .discopop directory at " + self.dot_dp_path)
        if self.prompts < 1:
            problems.append("--prompts must be at least 1")
        if self.retries < 0 or self.agent_error_retries < 0 or self.max_suggestions < 0:
            problems.append("--retries, --agent-error-retries and --max-suggestions must not be negative")
        if self.verify not in VERIFY_CHOICES:
            problems.append("--verify must be one of " + ", ".join(VERIFY_CHOICES))
        elif self.verify != VERIFY_NONE:
            problems.append("--verify " + self.verify + " is not implemented yet; use --verify none")
        if problems:
            raise ValueError("; ".join(problems))

    @property
    def suggestion_check_path(self) -> str:
        return os.path.join(self.dot_dp_path, "suggestion_check")

    @property
    def patch_repair_path(self) -> str:
        """the LLM configuration is shared with patch repair"""
        return os.path.join(self.dot_dp_path, "patch_repair")

    def suggestion_ids(self) -> Optional[List[int]]:
        if self.suggestions is None or not self.suggestions.strip():
            return None
        return [int(s) for s in self.suggestions.split(",") if s.strip()]

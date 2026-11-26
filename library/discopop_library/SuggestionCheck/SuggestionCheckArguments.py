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
from discopop_library.SuggestionCheck.prompt_store import custom_prompt_dir

VERIFY_NONE = "none"
VERIFY_BUILD = "build"
VERIFY_RUN = "run"
VERIFY_CHOICES = (VERIFY_NONE, VERIFY_BUILD, VERIFY_RUN)


@dataclass
class SuggestionCheckArguments(GeneralArguments):
    """the arguments of discopop_suggestion_check"""

    dot_dp_path: str
    # the project whose copy the agent works in; default: the directory holding .discopop
    project_root: Optional[str] = None
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
    # whether approvals whose results may differ by rounding count (floating-point operations in another order)
    accept_rounding: bool = True
    # DiscoPoP's data for the agents, through its MCP server (read-only, bound to the project); on if it is found
    discopop_tools: bool = True
    # the project's own prompt templates; default: .discopop/project/prompts/suggestion_check (see prompt_store)
    prompt_dir: Optional[str] = None

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

    @property
    def effective_prompt_dir(self) -> str:
        return self.prompt_dir or custom_prompt_dir(self.dot_dp_path)

    def suggestion_ids(self) -> Optional[List[int]]:
        if self.suggestions is None or not self.suggestions.strip():
            return None
        return [int(s) for s in self.suggestions.split(",") if s.strip()]

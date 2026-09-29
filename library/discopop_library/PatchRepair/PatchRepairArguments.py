# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import List, Optional

from discopop_library.ArgumentClasses.GeneralArguments import GeneralArguments
from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path

logger = logging.getLogger("PatchRepairArguments")

# Hotspot buckets considered by default. Suggestions classified NO contribute
# negligibly to the runtime, so repairing them spends agent tokens and build time on
# code that will never be worth parallelizing. Where no hotspot information exists
# every suggestion is classified YES, so nothing is skipped by this default.
DEFAULT_HOTSPOT_TYPES = "yes,maybe"

VALID_HOTSPOT_TYPES = ("yes", "no", "maybe")


@dataclass
class PatchRepairArguments(GeneralArguments):
    """Container class for the arguments passed to discopop_patch_repair."""

    dot_dp_path: str
    configuration: str

    # -- what to repair ----------------------------------------------------------
    hotspot_types: str = DEFAULT_HOTSPOT_TYPES
    # Explicit ids, comma separated. Overrides the hotspot filter: an id named here is
    # considered even when its hotspot type says it is not worth the effort.
    suggestions: Optional[str] = None

    # -- attempt budget ----------------------------------------------------------
    # Independent attempts with a fresh context, each using the next template of the
    # prompt ladder.
    prompts: int = 2
    # Follow-up turns within one attempt: the previous failure is appended to the same
    # conversation. An attempt therefore costs at most 1 + retries agent calls.
    retries: int = 2
    # Hard ceiling on *charged* agent calls per suggestion, independent of
    # prompts x retries.
    max_attempts: int = 6
    # Extra agent calls allowed when a call never produces an answer from the model --
    # an unreachable provider, a server error, no response within the timeout. Such a
    # call costs no tokens and gives the model no chance to fix anything, so charging
    # it to prompts x retries would let a flaky endpoint spend the whole budget
    # without the model ever seeing the prompt, and the suggestion would then be
    # recorded as one a model failed to repair. It gets its own small allowance
    # instead, which also keeps the loop terminating when the agent is simply down.
    agent_error_retries: int = 2
    # Stop after this many repaired suggestions. 0 disables the limit.
    max_repairs: int = 0

    # -- agent -------------------------------------------------------------------
    # A stored connection from the LLM configuration, or None to use the only one
    # defined / an implicit connection through the first installed agent.
    connection: Optional[str] = None
    # Ad hoc overrides of whatever the connection says, so a one-off run never has to
    # edit the configuration file.
    backend: Optional[str] = None
    model: Optional[str] = None
    agent_timeout: float = 300.0
    llm_config: Optional[str] = None
    prompt_dir: Optional[str] = None

    # -- prompt shaping ----------------------------------------------------------
    context_lines: int = 60
    max_error_chars: int = 8000
    max_prompt_chars: int = 60000

    # -- modes -------------------------------------------------------------------
    # Run the whole pipeline but write nothing to patch_generator/. The intended way to
    # see what a backend would do before letting it near the patches.
    dry_run: bool = False
    # Restore the patches backed up by an earlier run and do nothing else.
    restore: bool = False
    thread_count: int = 1

    # -- derived -----------------------------------------------------------------
    project_path: str = ""
    configuration_path: str = ""
    patch_generator_path: str = ""
    patch_repair_path: str = ""

    def __post_init__(self) -> None:
        self.project_path = str(Path(self.dot_dp_path).parent.absolute())
        self.configuration_path = os.path.join(self.dot_dp_path, "project", "configs", self.configuration)
        self.patch_generator_path = os.path.join(self.dot_dp_path, "patch_generator")
        self.patch_repair_path = os.path.join(self.dot_dp_path, "patch_repair")
        self.__validate()

    def log(self) -> None:
        logger.debug("Arguments:")
        for entry in self.__dict__:
            logger.debug("-- " + str(entry) + ": " + str(self.__dict__[entry]))

    def selected_hotspot_types(self) -> List[str]:
        return [t.strip().lower() for t in self.hotspot_types.split(",") if t.strip()]

    def explicit_suggestion_ids(self) -> Optional[List[int]]:
        """The ids named by --suggestions, or None when the hotspot filter decides."""
        if self.suggestions is None:
            return None
        return [int(s.strip()) for s in self.suggestions.split(",") if s.strip()]

    def __validate(self) -> None:
        """Check the arguments, e.g. whether the files the run depends on exist."""
        for hotspot_type in self.selected_hotspot_types():
            if hotspot_type not in VALID_HOTSPOT_TYPES:
                raise ValueError(
                    "Unknown hotspot type: " + hotspot_type + ". Options: " + ", ".join(VALID_HOTSPOT_TYPES)
                )
        if self.suggestions is not None:
            try:
                self.explicit_suggestion_ids()
            except ValueError:
                raise ValueError("--suggestions expects a comma separated list of integer ids: " + self.suggestions)
        for value, name in (
            (self.prompts, "--prompts"),
            (self.retries, "--retries"),
            (self.agent_error_retries, "--agent-error-retries"),
        ):
            if value < 0:
                raise ValueError(name + " must not be negative.")
        if self.prompts < 1:
            raise ValueError("--prompts must be at least 1; use --dry-run to inspect without repairing.")

        # The same prerequisites the autotuner checks, since every compile check runs
        # through it. Failing here names the missing file instead of letting the first
        # subprocess fail with a stack trace.
        required_files = [
            self.project_path,
            self.dot_dp_path,
            os.path.join(self.dot_dp_path, "FileMapping.txt"),
            os.path.join(self.dot_dp_path, "explorer"),
            self.patch_generator_path,
            os.path.join(self.dot_dp_path, "line_mapping.json"),
            os.path.join(self.dot_dp_path, "project", "configs", self.configuration),
            os.path.join(self.dot_dp_path, "project", "configs", "seq_settings.json"),
            resolve_compile_script_path(os.path.join(self.dot_dp_path, "project", "configs"), self.configuration),
            os.path.join(self.dot_dp_path, "project", "configs", self.configuration, "execute.sh"),
        ]
        for file in required_files:
            if not os.path.exists(file):
                raise FileNotFoundError(file)

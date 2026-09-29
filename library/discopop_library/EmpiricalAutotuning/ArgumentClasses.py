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
from typing import Optional
from discopop_library.ArgumentClasses.GeneralArguments import GeneralArguments
from discopop_library.ProjectManager.configurations.compile_script import resolve_compile_script_path
from discopop_library.ProjectManager.configurations.repetitions import DEFAULT_TUNING_REPETITIONS

logger = logging.getLogger("AutotunerArguments")


@dataclass
class AutotunerArguments(GeneralArguments):
    """Container Class for the arguments passed to the discopop autotuner"""

    dot_dp_path: str
    skip_cleanup: bool
    sanitize: bool
    configuration: str
    suggestions: Optional[str]
    allow_plots: bool
    thread_count: int
    project_path: str = ""
    configuration_path: str = ""
    hotspot_types: str = ""
    algorithm: int = 0
    search_space: Optional[str] = None
    # Build every candidate but run none of them: the search then answers "does this
    # configuration compile?" instead of "how fast is it?". Nothing is measured, so no
    # candidate can be ranked -- the mode exists for callers that only care about
    # compilability, above all discopop_patch_repair, which needs the compiler's
    # diagnostics for a single suggestion and would otherwise pay a full program run
    # per invocation.
    compile_only: bool = False
    # Tuning knobs of the hotspot-guided region descent (-A 6). Defaults are chosen so
    # the algorithm can be run without any of them.
    noise_threshold: float = 0.02
    hs_min_share: float = 0.01
    max_measurements: int = 0
    skip_removal_pass: bool = False
    # Overrides every configuration's stored "read the execution time from the
    # program's output" setting; see
    # discopop_library.ProjectManager.configurations.execution_time. The tuner
    # ranks candidates by measured runtime, so which of the two times is measured
    # decides what it optimizes for.
    execution_time_regex: Optional[str] = None
    # How often each candidate's execute.sh is run before its time is decided; the
    # median of the repetitions is what the candidate is ranked by. Separate from
    # the count used for the final measurements on purpose: the search runs one
    # program execution per candidate and repeating every one of them multiplies
    # the tuning time, while the noise a repetition removes only has to be smaller
    # than the improvement the search is asked to detect (--noise-threshold).
    execution_repetitions: int = DEFAULT_TUNING_REPETITIONS

    def __post_init__(self) -> None:
        self.project_path = str(Path(self.dot_dp_path).parent.absolute())
        self.configuration_path = os.path.join(self.dot_dp_path, "project", "configs", self.configuration)
        self.__validate()

    def log(self) -> None:
        logger.debug("Arguments:")
        for entry in self.__dict__:
            logger.debug("-- " + str(entry) + ": " + str(self.__dict__[entry]))

    def __validate(self) -> None:
        """Validate the arguments passed to the discopop autotuner, e.g check if given files exist"""

        required_files = [
            self.project_path,
            self.dot_dp_path,
            os.path.join(self.dot_dp_path, "FileMapping.txt"),
            os.path.join(self.dot_dp_path, "profiler"),
            os.path.join(self.dot_dp_path, "explorer"),
            os.path.join(self.dot_dp_path, "patch_generator"),
            os.path.join(self.dot_dp_path, "line_mapping.json"),
            os.path.join(self.dot_dp_path, "project"),
            os.path.join(self.dot_dp_path, "project", "configs"),
            os.path.join(self.dot_dp_path, "project", "configs", self.configuration),
            os.path.join(self.dot_dp_path, "project", "configs", "seq_settings.json"),
            resolve_compile_script_path(os.path.join(self.dot_dp_path, "project", "configs"), self.configuration),
            os.path.join(self.dot_dp_path, "project", "configs", self.configuration, "execute.sh"),
        ]
        for file in required_files:
            if not os.path.exists(file):
                raise FileNotFoundError(file)

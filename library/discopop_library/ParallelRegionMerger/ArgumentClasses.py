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

logger = logging.getLogger("AutotunerArguments")


@dataclass
class ParallelRegionMergerArguments(GeneralArguments):
    """Container Class for the arguments passed to the discopop parallel region merger"""

    dot_dp_path: str
    suggestions: Optional[str]
    allow_plots: bool
    auto_tuner_config: str
    # derived values
    project_path: str = ""

    def __post_init__(self) -> None:
        self.project_path = str(Path(self.dot_dp_path).parent.absolute())
        self.__validate()

    def log(self) -> None:
        logger.debug("Arguments:")
        for entry in self.__dict__:
            logger.debug("-- " + str(entry) + ": " + str(self.__dict__[entry]))

    def __validate(self) -> None:
        """Validate the arguments passed to the discopop parallel region merger, e.g check if given files exist"""

        required_files = [
            self.project_path,
            self.dot_dp_path,
            os.path.join(self.dot_dp_path, "FileMapping.txt"),
            os.path.join(self.dot_dp_path, "profiler"),
            os.path.join(self.dot_dp_path, "explorer"),
            os.path.join(self.dot_dp_path, "patch_generator"),
            os.path.join(self.dot_dp_path, "line_mapping.json"),
            os.path.join(self.dot_dp_path, "project"),
        ]

        if self.suggestions is not None:
            if self.suggestions == "auto":
                required_files.append(os.path.join(self.dot_dp_path, "auto_tuner"))
                required_files.append(os.path.join(self.dot_dp_path, "auto_tuner", "results.json"))

        for file in required_files:
            if not os.path.exists(file):
                raise FileNotFoundError(file)

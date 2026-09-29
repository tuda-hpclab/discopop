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
from typing import List
from discopop_library.ArgumentClasses.GeneralArguments import GeneralArguments
from discopop_library.HostpotLoader.HotspotType import HotspotType

logger = logging.getLogger("SanityCheckerArguments")


@dataclass
class SanityCheckerArguments(GeneralArguments):
    """Container Class for the arguments passed to the discopop sanity checker"""

    project_path: str
    dot_dp_path: str
    suggestion_classes: List[HotspotType]

    def __post_init__(self) -> None:
        self.__validate()

    def log(self) -> None:
        logger.debug("Arguments:")
        for entry in self.__dict__:
            logger.debug("-- " + str(entry) + ": " + str(self.__dict__[entry]))

    def __validate(self) -> None:
        """Validate the arguments passed to the discopop sanity checker, e.g check if given files exist"""

        required_files = [
            self.project_path,
            os.path.join(self.project_path, "DP_COMPILE_SANITIZE.sh"),
            os.path.join(self.project_path, "DP_EXECUTE_SANITIZE.sh"),
            self.dot_dp_path,
            os.path.join(self.dot_dp_path, "FileMapping.txt"),
            os.path.join(self.dot_dp_path, "profiler"),
            os.path.join(self.dot_dp_path, "explorer"),
            os.path.join(self.dot_dp_path, "patch_generator"),
            os.path.join(self.dot_dp_path, "line_mapping.json"),
            os.path.join(self.dot_dp_path, "hotspot_detection"),
        ]
        for file in required_files:
            if not os.path.exists(file):
                raise FileNotFoundError(file)

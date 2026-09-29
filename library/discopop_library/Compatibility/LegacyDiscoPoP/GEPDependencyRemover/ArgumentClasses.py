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
from discopop_library.ArgumentClasses.GeneralArguments import GeneralArguments

logger = logging.getLogger("AutotunerArguments")


@dataclass
class GEPDependencyRemoverArguments(GeneralArguments):
    """Container Class for the arguments passed to the discopop GEPDependencyRemover"""

    dyndep_file_path: str

    def __post_init__(self) -> None:
        self.__validate()

    def log(self) -> None:
        logger.debug("Arguments:")
        for entry in self.__dict__:
            logger.debug("-- " + str(entry) + ": " + str(self.__dict__[entry]))

    def __validate(self) -> None:
        """Validate the arguments passed to the discopop GEPDependencyRemover, e.g check if given files exist"""

        required_files = [
            self.dyndep_file_path,
        ]
        for file in required_files:
            if not os.path.exists(file):
                raise FileNotFoundError(file)

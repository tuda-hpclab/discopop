# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
import sys
from dataclasses import dataclass
from typing import List

from discopop_library.ArgumentClasses.GeneralArguments import GeneralArguments


@dataclass
class PreProcessorArguments(GeneralArguments):
    """Container Class for the arguments passed to the discopop_preprocessor"""

    def __post_init__(self) -> None:
        self.__validate()

    def __validate(self) -> None:
        """Validate the arguments passed to the discopop_preprocessor, e.g check if given files exist"""
        pass

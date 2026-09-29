# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from dataclasses import dataclass
from typing import List

from discopop_library.ArgumentClasses.GeneralArguments import GeneralArguments


@dataclass
class HotspotLoaderArguments(GeneralArguments):
    """Container Class for the arguments passed to the hotspot loader"""

    verbose: bool
    dot_discopop_path: str
    get_loops: bool
    get_functions: bool
    get_YES: bool
    get_NO: bool
    get_MAYBE: bool

    def __post_init__(self) -> None:
        self.__validate()

    def __validate(self) -> None:
        pass

    def __str__(self) -> str:
        return str(self.__dict__)

    def get_considered_hotness(self) -> List[str]:
        result_list: List[str] = []
        if self.get_YES:
            result_list.append("YES")
        if self.get_NO:
            result_list.append("NO")
        if self.get_MAYBE:
            result_list.append("MAYBE")
        return result_list

    def get_considered_types(self) -> List[str]:
        result_list: List[str] = []
        if self.get_loops:
            result_list.append("LOOP")
        if self.get_functions:
            result_list.append("FUNCTION")
        return result_list

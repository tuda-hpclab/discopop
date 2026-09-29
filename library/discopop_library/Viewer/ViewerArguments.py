# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from dataclasses import dataclass

from discopop_library.ArgumentClasses.GeneralArguments import GeneralArguments


@dataclass
class ViewerArguments(GeneralArguments):
    """Container Class for the arguments passed to the discopop_viewer"""

    path: str  # .discopop folder
    print_suggestions_overview: bool

    def __post_init__(self) -> None:
        self.__validate()

    def __validate(self) -> None:
        pass

    def __str__(self) -> str:
        return str(self.__dict__)

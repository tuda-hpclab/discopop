# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from dataclasses import dataclass


@dataclass
class CodeGeneratorArguments(object):
    """Container Class for the arguments passed to the discopop_code_generator"""

    fmap: str
    json: str
    patterns: str
    outputdir: str
    skip_compilation_check: bool
    compile_check_command: str

    def __post_init__(self) -> None:
        self.__validate()

    def __validate(self) -> None:
        pass

    def __str__(self) -> str:
        return str(self.__dict__)

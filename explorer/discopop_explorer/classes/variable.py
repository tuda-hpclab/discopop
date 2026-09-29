# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
from typing import Optional

from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName


class Variable(object):
    operation: Optional[str]

    def __init__(self, type: str, name: VarName, defLine: str, accessMode: str = "", sizeInByte: int = 0):
        self.type = type
        self.name: VarName = name
        self.defLine = defLine
        self.operation = None
        self.accessMode = accessMode
        # To prevent potentially dividing by 0, set the sizeInByte to 8 in case it is unknown.
        # Sizes are mainly unknown if the underlying variable is a pointer type.
        # Since Pointers in 64-bit architectures occupy 8 bytes, this size is chosen as the "default" at this point.
        if sizeInByte == 0:
            sizeInByte = 8
        self.sizeInByte = sizeInByte

    def __hash__(self) -> int:
        return hash(self.name)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Variable) and self.name == other.name

    def __lt__(self, other: Variable) -> bool:
        try:
            return self.name < other.name
        except:
            return True

    def __str__(self) -> str:
        return self.name

    def toJSON(self) -> str:
        if self.operation is None:
            return self.name
        else:
            return self.operation + ":" + self.name

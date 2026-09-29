# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from enum import IntEnum
from typing import Optional
from discopop_explorer.classes.PEGraph.Dependency import Dependency


class CTGEdgeType(IntEnum):
    CONTROL = 1
    DATA = 2


class CTGEdgeInfo(object):
    type: CTGEdgeType
    dep_obj: Optional[Dependency]

    def __init__(self, type: CTGEdgeType, dep_obj: Optional[Dependency] = None):
        self.type = type
        self.dep_obj = dep_obj

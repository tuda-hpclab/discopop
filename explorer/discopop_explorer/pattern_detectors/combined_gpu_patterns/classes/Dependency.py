# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Set

from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import (
    VarName,
)


class Dependency(object):
    source: NodeID
    sink: NodeID
    var_names: Set[VarName]
    memory_regions: Set[MemoryRegion]

    def __init__(
        self,
        source: NodeID,
        sink: NodeID,
        var_names: Set[VarName],
        memory_regions: Set[MemoryRegion],
    ):
        self.source = source
        self.sink = sink
        self.var_names = var_names
        self.memory_regions = memory_regions

    def __str__(self) -> str:
        return (
            "Dependency("
            + self.source
            + " -> "
            + self.sink
            + " "
            + str(self.var_names)
            + " / "
            + str(self.memory_regions)
            + ")"
        )

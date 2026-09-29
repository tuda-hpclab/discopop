# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import List
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TGFunctionNode import TGFunctionNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TGNode import TGNode


class TaskNode(TGNode):
    contained_pet_nodes: List[Node]
    parallel_friendly_towards: List[TGFunctionNode]

    def __init__(self) -> None:
        super().__init__()

        self.contained_pet_nodes = []

    def get_label(self) -> str:
        return "\n".join([c.start_position() + " - " + c.end_position() for c in self.contained_pet_nodes])

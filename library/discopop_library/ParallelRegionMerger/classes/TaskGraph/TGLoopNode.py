# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import List
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TGFunctionNode import TGFunctionNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TGNode import TGNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TaskNode import TaskNode


class TGLoopNode(TaskNode):

    def __init__(self) -> None:
        super().__init__()

    def get_label(self) -> str:
        return "\n".join([n.start_position() + " - " + n.end_position() for n in self.contained_pet_nodes])

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TGNode import TGNode


class TGFunctionNode(TGNode):
    fn: FunctionNode

    def __init__(self, fn_arg: FunctionNode) -> None:
        super().__init__()
        self.fn = fn_arg

    def get_label(self) -> str:
        return self.fn.start_position() + " " + self.fn.name

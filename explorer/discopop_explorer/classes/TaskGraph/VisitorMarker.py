# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_explorer.classes.TaskGraph.Aliases import LevelIndex, PETNodeID, PositionIndex
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.TGNode import TGNode


class VisitorMarker(TGNode):
    pass


class EndFunctionMarker(VisitorMarker):
    function_node: PETNodeID
    context: Context

    def __init__(self, function_node: PETNodeID, level: LevelIndex, position: PositionIndex):
        self.function_node = function_node
        super().__init__(None, level, position)

    def get_label(self) -> str:
        return "EFM " + str(self.function_node)

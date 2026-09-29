# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import TYPE_CHECKING, List

from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.enums.NodeType import NodeType

if TYPE_CHECKING:
    from discopop_explorer.classes.variable import Variable
    from discopop_explorer.aliases.NodeID import NodeID


# Data.xml: type="0"
class CUNode(Node):
    instructions_count: int = -1
    basic_block_id = ""
    return_instructions_count: int = -1
    local_vars: List[Variable] = []
    global_vars: List[Variable] = []
    performs_file_io: bool = False

    def __init__(self, node_id: NodeID):
        super().__init__(node_id)
        self.type = NodeType.CU

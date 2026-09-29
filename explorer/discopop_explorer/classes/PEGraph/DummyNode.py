# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import List

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.classes.variable import Variable


# Data.xml: type="3"
class DummyNode(Node):
    args: List[Variable] = []

    def __init__(self, node_id: NodeID):
        super().__init__(node_id)
        self.type = NodeType.DUMMY

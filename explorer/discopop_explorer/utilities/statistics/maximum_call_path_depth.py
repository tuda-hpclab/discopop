# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.utilities.statistics.utilities.call_path_depth import get_outgoing_call_path_depth


def get_maximum_call_path_depth(pet: PEGraphX) -> int:
    res = 0
    for node in all_nodes(pet):
        if node.type != NodeType.FUNC:
            continue
        res = max(res, get_outgoing_call_path_depth(pet, node))
    return res

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
from typing import TYPE_CHECKING, List

from discopop_explorer.functions.PEGraph.queries.edges import out_edges

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
    from discopop_explorer.classes.PEGraph.Node import Node

from discopop_explorer.enums.EdgeType import EdgeType


def direct_successors(pet: PEGraphX, root: Node) -> List[Node]:
    """Gets only direct successors of any type

    :param root: root node
    :return: list of direct successors
    """
    return [pet.node_at(t) for s, t, d in out_edges(pet, root.id, EdgeType.SUCCESSOR)]

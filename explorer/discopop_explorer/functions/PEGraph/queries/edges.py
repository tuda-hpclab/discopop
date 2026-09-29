# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
from typing import TYPE_CHECKING, List, Optional, Tuple, Union
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.Dependency import Dependency

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
    from discopop_explorer.enums.EdgeType import EdgeType


def in_edges(
    pet: PEGraphX, node_id: NodeID, etype: Optional[Union[EdgeType, List[EdgeType]]] = None
) -> List[Tuple[NodeID, NodeID, Dependency]]:
    """Get incoming edges of node of specified type

    :param node_id: id of the target node
    :param etype: type of edges
    :return: list of incoming edges
    """
    if etype is None:
        return [t for t in pet.g.in_edges(node_id, data="data")]
    elif type(etype) == list:
        return [t for t in pet.g.in_edges(node_id, data="data") if t[2].etype in etype]
    else:
        return [t for t in pet.g.in_edges(node_id, data="data") if t[2].etype == etype]


def out_edges(
    pet: PEGraphX, node_id: NodeID, etype: Optional[Union[EdgeType, List[EdgeType]]] = None
) -> List[Tuple[NodeID, NodeID, Dependency]]:
    """Get outgoing edges of node of specified type

    :param node_id: id of the source node
    :param etype: type of edges
    :return: list of outgoing edges
    """
    if etype is None:
        return [t for t in pet.g.out_edges(node_id, data="data")]
    elif type(etype) == list:
        return [t for t in pet.g.out_edges(node_id, data="data") if t[2].etype in etype]
    else:
        return [t for t in pet.g.out_edges(node_id, data="data") if t[2].etype == etype]


def count_edges(pet: PEGraphX, etype: Optional[Union[EdgeType, List[EdgeType]]] = None) -> int:
    if etype is None:
        return len([e for e in pet.g.edges(data=True)])
    elif type(etype) == list:
        return len([e for e in pet.g.edges(data=True) if e[2]["data"].etype in etype])
    else:
        return len([e for e in pet.g.edges(data=True) if e[2]["data"].etype == etype])

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

from typing import Dict, List, TYPE_CHECKING, Tuple

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.enums.EdgeType import EdgeType

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX

DataEdges = List[Tuple[NodeID, NodeID, Dependency]]


class DataEdgeIndex:
    """The DATA edges of a PET graph, indexed per node.

    The do-all analysis asks for the incoming and outgoing DATA edges of every CU of every loop
    candidate. Answering that through in_edges / out_edges means materializing a networkx edge
    view and filtering it by edge type once per CU *and per candidate*, and the same CU is
    visited by every copy of its enclosing loop - which made those queries one of the dominant
    costs of the analysis. This builds the same information once.

    The edge order of the underlying graph is preserved per node, because the classification of
    a variable as first read or first written depends on the order in which its dependencies are
    visited.

    The index is a snapshot: it must be built after the last modification of the PET graph, and
    is invalid afterwards. Pattern detection does not modify the graph, so building it once at
    the start of a detector is safe.
    """

    __slots__ = ("_incoming", "_outgoing")

    def __init__(self, pet: PEGraphX) -> None:
        self._incoming: Dict[NodeID, DataEdges] = {}
        self._outgoing: Dict[NodeID, DataEdges] = {}
        for node_id in pet.g.nodes():
            incoming = [t for t in pet.g.in_edges(node_id, data="data") if t[2].etype == EdgeType.DATA]
            if len(incoming) > 0:
                self._incoming[node_id] = incoming
            outgoing = [t for t in pet.g.out_edges(node_id, data="data") if t[2].etype == EdgeType.DATA]
            if len(outgoing) > 0:
                self._outgoing[node_id] = outgoing

    def in_edges(self, node_id: NodeID) -> DataEdges:
        """the incoming DATA edges of the given node, in the order the PET graph reports them"""
        return self._incoming.get(node_id, [])

    def out_edges(self, node_id: NodeID) -> DataEdges:
        """the outgoing DATA edges of the given node, in the order the PET graph reports them"""
        return self._outgoing.get(node_id, [])

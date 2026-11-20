# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

import heapq
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from discopop_explorer.classes.TaskGraph.Contexts.Context import Context

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph


class MergeWorklist:
    """The nodes to examine for a replacement that merges nodes into a new one, in the order of a scan that starts
    again from the last node of the graph after every merge: the node that was added to the graph last comes first.

    Starting again meant examining all nodes again after every merge (merges x nodes). A merge can only change
    the outcome for the nodes close to it, so after a merge only the nodes within two edges of the new node are put
    back; every other node was examined with the same result and stays out. The order of the merges, and so the
    result, is the one of the scan that starts again."""

    def __init__(self, ctg: ContextTaskGraph) -> None:
        self.ctg = ctg
        self._node_at: Dict[int, Context] = dict(enumerate(ctg.graph.nodes()))
        self._position: Dict[Context, int] = {node: position for position, node in self._node_at.items()}
        self._next_position = len(self._node_at)
        self._heap: List[int] = [-position for position in self._node_at]
        heapq.heapify(self._heap)

    def pop(self) -> Optional[Context]:
        """The next node still in the graph, or None."""
        while self._heap:
            node = self._node_at[-heapq.heappop(self._heap)]
            if node in self.ctg.graph:
                return node
        return None

    def merged_into(self, new_node: Context) -> None:
        """Call after nodes were replaced by new_node: puts the nodes the merge can affect back."""
        if new_node not in self.ctg.graph:
            return  # a region without any edge is not added to the graph
        self._node_at[self._next_position] = new_node
        self._position[new_node] = self._next_position
        heapq.heappush(self._heap, -self._next_position)
        self._next_position += 1
        reached: Set[Context] = {new_node}
        frontier: Set[Context] = {new_node}
        for _ in range(2):
            next_frontier: Set[Context] = set()
            for node in frontier:
                next_frontier.update(self.ctg.get_predecessors(node))
                next_frontier.update(self.ctg.get_successors(node))
            frontier = next_frontier - reached
            reached |= frontier
        for node in reached:
            if node is not new_node:
                heapq.heappush(self._heap, -self._position[node])

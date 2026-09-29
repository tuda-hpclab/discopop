# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
import logging
from typing import TYPE_CHECKING, List, Tuple

from discopop_explorer.classes.ContextTaskGraph.classes.edges import CTGEdgeInfo, CTGEdgeType
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph

import networkx as nx  # type: ignore

logger = logging.getLogger("Explorer")


def transitive_reduction(ctg: ContextTaskGraph) -> bool:
    """Removes redundant CONTROL edges. Redundant edges are always the shorter ones, if two or more exist.
    Returns True, if a modification was applied."""
    modification_applied = False
    edges_removed = True
    while edges_removed:
        edges_removed = False
        queue: List[Tuple[Context, Context]] = list(ctg.graph.edges())
        print("outer")
        while len(queue) > 0:
            print("queue: ", len(queue))
            edge = queue.pop()
            # check if edge is of type control
            if len([info for info in ctg.get_edge_info(edge[0], edge[1]) if info.type == CTGEdgeType.CONTROL]) < 1:
                continue
            # calculate alternative paths from source to target
            print("pre-call")
            paths = nx.all_simple_paths(ctg.graph, edge[0], edge[1], cutoff=25)
            print("post-call")
            # filter paths for use of CONTROL edges on every step
            filtered_paths: List[List[Context]] = []
            for p in paths:
                print("p")
                p_valid = True
                # check every step for edge type
                for idx in range(0, len(p) - 1):
                    print("idx")
                    if (
                        len([info for info in ctg.get_edge_info(edge[0], edge[1]) if info.type == CTGEdgeType.CONTROL])
                        < 1
                    ):
                        p_valid = False
                        break
                if p_valid:
                    filtered_paths.append(p)

            # check if a path with a length > 2 exist, i.e., one which is longer than the direct edge.
            remove_edge = False
            for p in filtered_paths:
                print("fp")
                if len(p) > 2:
                    remove_edge = True
                    break
            # remove CONTROL edge between source and target. Preserve DATA edge, if it exists
            if remove_edge:

                to_be_removed: List[CTGEdgeInfo] = []
                for info in ctg.get_edge_info(edge[0], edge[1]):
                    print("re")
                    if info.type == CTGEdgeType.CONTROL:
                        to_be_removed.append(info)

                for info in to_be_removed:
                    print("tre")
                    if info in ctg.edge_information[edge[0]][edge[1]]:
                        ctg.edge_information[edge[0]][edge[1]].remove(info)
                # delete edge, if no DATA edge remains
                if len(ctg.edge_information[edge[0]][edge[1]]) == 0:
                    ctg.graph.remove_edge(edge[0], edge[1])

                edges_removed = True
                modification_applied = True

            if edges_removed:
                break

    return modification_applied

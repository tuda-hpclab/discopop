# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
import logging
from typing import TYPE_CHECKING, List, Set, Tuple

from discopop_explorer.classes.ContextTaskGraph.classes.edges import CTGEdgeInfo, CTGEdgeType
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.ContextTaskGraph.modifications.utilities.dominator import is_dominator

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph

import networkx as nx  # type: ignore

logger = logging.getLogger("Explorer")


def partial_transitive_reduction(ctg: ContextTaskGraph) -> bool:
    """Removes redundant CONTROL edges incoming to leaf nodes of the graph.
    Does not perform a full transitive reduction.
    Returns True, if a modification was applied."""
    modification_applied = False
    queue: List[Context] = list(ctg.graph.nodes())
    while len(queue) > 0:
        node = queue.pop()
        # check if node is a leaf
        # NOTE: this is too restrictive. disabled.
        # if len(ctg.get_successors(node)) > 0:
        #    continue
        # check if node has multiple predecessors
        if len(ctg.get_predecessors(node)) < 2:
            continue
        edges_removed = True
        while edges_removed:
            edges_removed = False
            # check redundancy for each combination of (remaining) predecessors.
            control_edge_predecessors = [
                ctx
                for ctx in ctg.get_predecessors(node)
                if (len([info for info in ctg.get_edge_info(ctx, node) if info.type == CTGEdgeType.CONTROL]) > 0)
            ]
            if len(control_edge_predecessors) < 2:
                # trivially no redundancy possible
                continue
            # a control edge is considered redundant, if its source node is a dominator of every other incoming control edge
            for pred_1 in control_edge_predecessors:
                pred_1_is_dominator = True
                for pred_2 in control_edge_predecessors:
                    if pred_1 == pred_2:
                        continue
                    # check if pred_1 is a dominator of pred_2
                    if not is_dominator(ctg, pred_1, pred_2):
                        # pred_1 is not dominator of pred_2
                        pred_1_is_dominator = False
                        break

                if not pred_1_is_dominator:
                    continue
                # remove CONTROL edge between pred_1 and node as it is redundant. Preserve DATA edge, if it exists
                to_be_removed: List[CTGEdgeInfo] = []
                for info in ctg.get_edge_info(pred_1, node):
                    if info.type == CTGEdgeType.CONTROL:
                        to_be_removed.append(info)

                for info in to_be_removed:
                    if info in ctg.edge_information[pred_1][node]:
                        ctg.edge_information[pred_1][node].remove(info)
                # delete edge, if no DATA edge remains
                if len(ctg.edge_information[pred_1][node]) == 0:
                    ctg.graph.remove_edge(pred_1, node)
                edges_removed = True
                modification_applied = True

                # restart with updated list of CONTROL edge predecessors
                break

    return modification_applied

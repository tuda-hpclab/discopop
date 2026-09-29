# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
import logging
from typing import TYPE_CHECKING, List

from discopop_explorer.classes.ContextTaskGraph.classes.edges import CTGEdgeInfo, CTGEdgeType
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.TaskParentContext import TaskParentContext

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph

logger = logging.getLogger("Explorer")


def INVALID_merge_successive_TaskParentContext_nodes(ctg: ContextTaskGraph) -> bool:
    """Merges two TaskParentContext nodes, if one is a direct control edge successor of another.
    Iterates until no further optimizations could be found.
    Only CONTROL edges are checked / modified, since TaskParentContext nodes should only be connected to those.
    Returns True, if a modification was applied.
    NOTE: CURRENTLY INVALID DUE TO ADDITION OF TASKENDCONTEXTS!"""

    nodes_merged = True
    modification_applied = False

    while nodes_merged:
        nodes_merged = False
        queue: List[Context] = list(ctg.graph.nodes())
        while len(queue) > 0:
            node = queue.pop()
            # check if node is of type TaskParentContext
            if not isinstance(node, TaskParentContext):
                continue
            # iterate over outgoing edges and search for control edges
            node_control_edge_successors = [
                ctx
                for ctx in ctg.get_successors(node)
                if len([info for info in ctg.get_edge_info(node, ctx) if info.type == CTGEdgeType.CONTROL]) > 0
            ]
            to_be_removed: List[TaskParentContext] = []
            for successor in node_control_edge_successors:
                # check if successor is of type TaskParentContext
                if not isinstance(successor, TaskParentContext):
                    continue
                # merge successor into node
                control_edge_predecessors = [
                    ctx
                    for ctx in ctg.get_predecessors(successor)
                    if (
                        len([info for info in ctg.get_edge_info(ctx, successor) if info.type == CTGEdgeType.CONTROL])
                        > 0
                    )
                ]
                # redirect incoming control edges to node
                for pred in control_edge_predecessors:
                    if pred == node:
                        continue
                    ctg.add_edge(pred, node, CTGEdgeInfo(CTGEdgeType.CONTROL))
                # redirect outgoing control edges
                succ_control_edge_successors = [
                    ctx
                    for ctx in ctg.get_successors(successor)
                    if len([info for info in ctg.get_edge_info(successor, ctx) if info.type == CTGEdgeType.CONTROL]) > 0
                ]
                for succ in succ_control_edge_successors:
                    ctg.add_edge(node, succ, CTGEdgeInfo(CTGEdgeType.CONTROL))
                # register successor for removal from the graph
                to_be_removed.append(successor)
                nodes_merged = True
                modification_applied = True
            # remove nodes
            for ctx in to_be_removed:
                ctg.graph.remove_node(ctx)
            # if modification was applied, queue might now contain deleted nodes. and thus be invalid. Start new outer iteration
            if nodes_merged:
                break

    return modification_applied

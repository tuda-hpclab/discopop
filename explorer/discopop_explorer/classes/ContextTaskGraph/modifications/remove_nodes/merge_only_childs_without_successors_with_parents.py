# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
import logging
from typing import TYPE_CHECKING, List, Tuple, cast

from discopop_explorer.classes.ContextTaskGraph.classes.CombinedContext import CombinedContext
from discopop_explorer.classes.ContextTaskGraph.classes.edges import CTGEdgeInfo, CTGEdgeType
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph

logger = logging.getLogger("Explorer")


def merge_only_childs_without_successors_with_parents(ctg: ContextTaskGraph) -> bool:
    """Merges two successive nodes, if the first node is the parent node of the second, successive node.
    The seconde node must be of type WorkContext or CombinedContext, so that it contains at least some work.
    Returns true, if a modification was applied."""
    modification_applied = False
    nodes_merged = True
    while nodes_merged:
        nodes_merged = False
        queue: List[Context] = list(ctg.graph.nodes())
        while len(queue) > 0:
            node = queue.pop()
            # ensure node is of allowed type
            if not (isinstance(node, WorkContext) or isinstance(node, CombinedContext)):
                continue
            # check if node has no successor itself
            if len(ctg.get_successors(node)) > 0:
                continue

            # check if node has exactly one CONTROL predecessor
            control_edge_predecessors = [
                ctx
                for ctx in ctg.get_predecessors(node)
                if (len([info for info in ctg.get_edge_info(ctx, node) if info.type == CTGEdgeType.CONTROL]) > 0)
            ]
            if len(control_edge_predecessors) != 1:
                continue
            predecessor = control_edge_predecessors[0]
            # check if predecessor has exactly one successor
            pred_control_edge_successors = [
                ctx
                for ctx in ctg.get_successors(predecessor)
                if len([info for info in ctg.get_edge_info(predecessor, ctx) if info.type == CTGEdgeType.CONTROL]) > 0
            ]
            if len(pred_control_edge_successors) != 1:
                continue

            # check if predecessor is the parent of node
            if node.parent_context != predecessor:
                continue

            # combine both nodes into CombinedContext node
            combined_context_node = CombinedContext()
            if predecessor.parent_context is None:
                continue
            combined_context_node.register_parent_context(predecessor.parent_context)
            combined_context_node.register_outermost_context(predecessor)
            if isinstance(predecessor, CombinedContext):
                combined_context_node.contained_contexts = combined_context_node.contained_contexts.union(
                    predecessor.contained_contexts
                )
            else:
                combined_context_node.contained_contexts.add(predecessor)
            if isinstance(node, CombinedContext):
                combined_context_node.contained_contexts = combined_context_node.contained_contexts.union(
                    node.contained_contexts
                )
            else:
                combined_context_node.contained_contexts.add(node)
            # redirect incoming edges
            in_edges_with_info: List[Tuple[Context, List[CTGEdgeInfo]]] = [
                (pred, ctg.get_edge_info(pred, predecessor)) for pred in ctg.get_predecessors(predecessor)
            ]
            for pred, info in in_edges_with_info:
                for info_elem in info:
                    ctg.add_edge(pred, combined_context_node, info_elem)
            # redirect outgoing edges
            out_edges_with_info: List[Tuple[Context, List[CTGEdgeInfo]]] = [
                (succ, ctg.get_edge_info(node, succ)) for succ in ctg.get_successors(node)
            ]
            for succ, info in out_edges_with_info:
                for info_elem in info:
                    ctg.add_edge(combined_context_node, succ, info_elem)
            # delete original nodes
            ctg.graph.remove_node(predecessor)
            ctg.graph.remove_node(node)

            nodes_merged = True
            modification_applied = True
            break  # break, so that queue will be newly constructed as it might contain deleted nodes.

    return modification_applied

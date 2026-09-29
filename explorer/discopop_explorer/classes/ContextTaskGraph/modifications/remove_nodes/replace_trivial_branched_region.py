# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
import logging
from typing import TYPE_CHECKING, List, Optional, Tuple

from discopop_explorer.classes.ContextTaskGraph.classes.edges import CTGEdgeInfo, CTGEdgeType
from discopop_explorer.classes.ContextTaskGraph.classes.CombinedContext import CombinedContext
from discopop_explorer.classes.TaskGraph.Contexts.BranchContext import BranchContext
from discopop_explorer.classes.TaskGraph.Contexts.BranchingParentContext import BranchingParentContext
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph

logger = logging.getLogger("Explorer")


def replace_trivial_branched_region(ctg: ContextTaskGraph) -> bool:
    """Replaces a trivial branched section (BranchParent + exactly two children + one merge node) with a CombinedContext node.
    Returns True, if a modification was applied."""
    modification_applied = False
    nodes_merged = True
    while nodes_merged:
        nodes_merged = False
        queue: List[Context] = list(ctg.graph.nodes())
        while len(queue) > 0:
            node = queue.pop()
            # check if node is of type BranchParent
            if not isinstance(node, BranchingParentContext):
                continue
            # check if exactly two CONTROL successors exist
            control_edge_successors = [
                ctx
                for ctx in ctg.get_successors(node)
                if len([info for info in ctg.get_edge_info(node, ctx) if info.type == CTGEdgeType.CONTROL]) > 0
            ]
            if len(control_edge_successors) != 2:
                continue
            # check if both successors are of type BranchContext or CombinedContext with a BranchContext as the Parent
            successors_are_branch_entries = True
            for succ in control_edge_successors:
                if isinstance(succ, BranchContext):
                    # valid branch entry
                    continue
                if isinstance(succ, CombinedContext) and isinstance(succ.outermost_context, BranchContext):
                    # valid brach entry
                    continue
                # succ is not a valid branch entry
                successors_are_branch_entries = False
                break
            if not successors_are_branch_entries:
                continue
            # check if both successor have only a single predecessor (i.e., the BranchingParentContext node)
            successors_preceeding_nodes_valid = True
            for succ in control_edge_successors:
                succ_control_edge_predecessors = [
                    ctx
                    for ctx in ctg.get_predecessors(succ)
                    if (len([info for info in ctg.get_edge_info(ctx, succ) if info.type == CTGEdgeType.CONTROL]) > 0)
                ]
                if len(succ_control_edge_predecessors) != 1:
                    successors_preceeding_nodes_valid = False
                    break
            if not successors_preceeding_nodes_valid:
                continue
            # check if both successors are followed by the same node
            successors_followed_by_same_node = True
            potential_merge_node: Optional[Context] = None
            for successor in control_edge_successors:
                succ_control_edge_successors = [
                    ctx
                    for ctx in ctg.get_successors(successor)
                    if len([info for info in ctg.get_edge_info(successor, ctx) if info.type == CTGEdgeType.CONTROL]) > 0
                ]
                # check if every sucessors has exactly one successor of their own
                if len(succ_control_edge_successors) != 1:
                    successors_followed_by_same_node = False
                    break
                # check that every successor is succeeded by the same node
                if potential_merge_node is None:
                    potential_merge_node = succ_control_edge_successors[0]
                else:
                    if succ_control_edge_successors[0] != potential_merge_node:
                        successors_followed_by_same_node = False
                        break
            if not successors_followed_by_same_node:
                continue

            # combine nodes into CombinedContext node
            combined_context_node = CombinedContext()
            if node.parent_context is None:
                continue
            combined_context_node.register_parent_context(node.parent_context)
            combined_context_node.register_outermost_context(node)
            for n in [node] + control_edge_successors:
                if isinstance(n, CombinedContext):
                    combined_context_node.contained_contexts = combined_context_node.contained_contexts.union(
                        n.contained_contexts
                    )
                else:
                    combined_context_node.contained_contexts.add(n)

            # redirect incoming edges
            in_edges_with_info: List[Tuple[Context, List[CTGEdgeInfo]]] = [
                (pred, ctg.get_edge_info(pred, node)) for pred in ctg.get_predecessors(node)
            ]
            for pred, info in in_edges_with_info:
                for info_elem in info:
                    ctg.add_edge(pred, combined_context_node, info_elem)
            # redirect outgoing edges from successors
            for branch_node in control_edge_successors:
                out_edges_with_info: List[Tuple[Context, List[CTGEdgeInfo]]] = [
                    (succ, ctg.get_edge_info(branch_node, succ)) for succ in ctg.get_successors(branch_node)
                ]
                for succ, info in out_edges_with_info:
                    for info_elem in info:
                        ctg.add_edge(combined_context_node, succ, info_elem)
            # redirect dependencies
            for branch_node in control_edge_successors:
                # redirect incoming dependencies
                in_data_edges_with_info: List[Tuple[Context, List[CTGEdgeInfo]]] = [
                    (pred, ctg.get_edge_info(pred, branch_node)) for pred in ctg.get_predecessors(branch_node)
                ]
                for pred, info in in_data_edges_with_info:
                    for info_elem in info:
                        if info_elem.type == CTGEdgeType.DATA:
                            ctg.add_edge(pred, combined_context_node, info_elem)
                # redirect outgoing dependencies
                out_data_edges_with_info: List[Tuple[Context, List[CTGEdgeInfo]]] = [
                    (succ, ctg.get_edge_info(branch_node, succ)) for succ in ctg.get_successors(branch_node)
                ]
                for succ, info in out_data_edges_with_info:
                    for info_elem in info:
                        if info_elem.type == CTGEdgeType.DATA:
                            ctg.add_edge(combined_context_node, succ, info_elem)

            # delete original nodes
            for branch_node in control_edge_successors:
                ctg.graph.remove_node(branch_node)
            ctg.graph.remove_node(node)

            nodes_merged = True
            modification_applied = True
            break  # break, so that queue will be newly constructed as it might contain deleted nodes.

    return modification_applied

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
import logging
from typing import TYPE_CHECKING, List, Optional, Set, Tuple

from discopop_explorer.classes.ContextTaskGraph.classes.edges import CTGEdgeInfo, CTGEdgeType
from discopop_explorer.classes.ContextTaskGraph.classes.CombinedContext import CombinedContext
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph

logger = logging.getLogger("Explorer")


def trivial_control_sequence_simplification(ctg: ContextTaskGraph) -> bool:
    """Replace trivial, linear control sequences with a CombinedContext node. Loop until no further linear sequences exist.
    Trivial sequences can consist of WorkContext and CombinedContext nodes only.
    Trivial sequences must contain at least one WorkContext.
    (Currently disabled: trivial sequences must share a common parent.)
    This is enforced by requiring, that either a WorkContext or a CombinedContext are contained.
    CombinedContexts themselves have the same requirement.
    Returns True, if a modification was applied."""
    sequences_replaced = True
    modification_applied = False
    while sequences_replaced:
        sequences_replaced = False
        queue: List[Context] = list(ctg.graph.nodes())
        while len(queue) > 0:
            node = queue.pop()
            # a sequence replaced earlier in this scan may have consumed the node
            if node not in ctg.graph:
                continue
            # check if node is a valid sequence entry
            predecessors = ctg.get_predecessors(node)
            successors = ctg.get_successors(node)
            if (
                len(successors) != 1
            ):  # or len(predecessors) != 1:  Note: checking predecessor length is too pessimistic for effective reduction
                continue
            # ensure existing control edge to successor
            if len([info for info in ctg.get_edge_info(node, successors[0]) if info.type == CTGEdgeType.CONTROL]) < 1:
                continue

            # check if node is a valid sequence start
            if not (
                isinstance(node, WorkContext) or isinstance(node, CombinedContext) or isinstance(node, IterationContext)
            ):  # or isinstance(node, InlinedFunctionContext) or isinstance(node, FunctionContext)):
                # not a valid sequence start
                continue
            sequence: List[Context] = [node]
            node_succesors = ctg.get_successors(node)

            # construct the longest possible sequence.
            # The walk follows CONTROL edges, which are not guaranteed to be acyclic, so it is
            # bounded by the set of nodes it has already placed in the sequence. Without that
            # bound a control cycle whose members each have exactly one control predecessor and
            # one control successor would extend the sequence forever.
            current: Optional[Context] = node_succesors[0]
            sequence_members: Set[Context] = {node}
            while current is not None:
                if current in sequence_members:
                    # closing a cycle - the sequence ends here
                    break
                # ensure current is of either allowed type of sequence members
                if not (
                    isinstance(current, WorkContext) or isinstance(current, CombinedContext)
                ):  #  or isinstance(current, IterationContext) or isinstance(current, InlinedFunctionContext) or isinstance(current, FunctionContext)):
                    # not a valid sequence member
                    break

                # check if node is a valid sequence member
                control_edge_predecessors = [
                    ctx
                    for ctx in ctg.get_predecessors(current)
                    if (len([info for info in ctg.get_edge_info(ctx, current) if info.type == CTGEdgeType.CONTROL]) > 0)
                ]
                control_edge_successors = [
                    ctx
                    for ctx in ctg.get_successors(current)
                    if (len([info for info in ctg.get_edge_info(current, ctx) if info.type == CTGEdgeType.CONTROL]) > 0)
                ]
                if len(control_edge_predecessors) != 1:
                    # not a valid sequence member
                    break
                if len(control_edge_successors) != 1:
                    # end of the current sequence, but a valid member
                    sequence.append(current)
                    sequence_members.add(current)
                    break
                # ensure sequence members share a common parent
                # Note: too pessimistic to allow full reduction, but required to simplify reasoning about the results
                # if node.parent_context != current.parent_context:
                #    break

                # valid sequence member
                sequence.append(current)
                sequence_members.add(current)

                # ensure existing control edge to successor
                if (
                    len(
                        [info for info in ctg.get_edge_info(current, successors[0]) if info.type == CTGEdgeType.CONTROL]
                    )
                    < 1
                ):
                    # end of the sequence
                    current = None
                    break
                # check successor
                current = control_edge_successors[0]
            # ensure sequence consists of at least two elements
            if len(sequence) < 2:
                continue
            # ensure that the sequence contains at least one WorkContext or CombinedContext element, so that the Sequence performs at least some minor work.
            if (
                len(
                    [
                        seq_elem
                        for seq_elem in sequence
                        if isinstance(seq_elem, WorkContext) or isinstance(seq_elem, CombinedContext)
                    ]
                )
                < 1
            ):
                # no work contained in the sequence
                continue
            # ensure that there are no dependencies against the flow direction within the sequence
            invalid_dependency_within_sequence = False
            for idx_1, seq_elem_1 in enumerate(sequence):
                # get outgoing data edges of seq_elem_1
                data_edge_successors = [
                    ctx
                    for ctx in ctg.get_successors(seq_elem_1)
                    if (len([info for info in ctg.get_edge_info(seq_elem_1, ctx) if info.type == CTGEdgeType.DATA]) > 0)
                ]
                # check every sequence element for potential violations
                for idx_2, seq_elem_2 in enumerate(sequence):
                    if seq_elem_1 == seq_elem_2:
                        continue
                    if idx_2 > idx_1:
                        # a potential data dependency from seq_elem_1 to seq_elem_2 would follow the control edge flow, thus, not a problem.
                        continue

                    if seq_elem_2 in data_edge_successors:
                        invalid_dependency_within_sequence = True
                    break
            if invalid_dependency_within_sequence:
                continue

            # combine sequence into CombinedContext node
            combined_context_node = CombinedContext()
            if sequence[0].parent_context is None:
                continue
            combined_context_node.register_parent_context(sequence[0].parent_context)
            combined_context_node.register_outermost_context(sequence[0])
            for seq_elem in sequence:
                if isinstance(seq_elem, CombinedContext):
                    combined_context_node.contained_contexts = combined_context_node.contained_contexts.union(
                        seq_elem.contained_contexts
                    )
                else:
                    combined_context_node.contained_contexts.add(seq_elem)
            # redirect incoming edges
            in_edges_with_info: List[Tuple[Context, List[CTGEdgeInfo]]] = [
                (pred, ctg.get_edge_info(pred, sequence[0])) for pred in ctg.get_predecessors(sequence[0])
            ]
            for pred, info in in_edges_with_info:
                for info_elem in info:
                    ctg.add_edge(pred, combined_context_node, info_elem)
            # redirect outgoing edges
            out_edges_with_info: List[Tuple[Context, List[CTGEdgeInfo]]] = [
                (succ, ctg.get_edge_info(sequence[-1], succ)) for succ in ctg.get_successors(sequence[-1])
            ]
            for succ, info in out_edges_with_info:
                for info_elem in info:
                    ctg.add_edge(combined_context_node, succ, info_elem)
            # delete sequence nodes. They may still sit in the queue; the staleness check at the
            # top of the scan skips them, which is cheaper than the O(len(queue)) list removal
            # this used to perform per sequence element.
            for seq_elem in sequence:
                ctg.graph.remove_node(seq_elem)
            sequences_replaced = True
            modification_applied = True

            # Keep scanning rather than restarting. Rebuilding list(ctg.graph.nodes()) after every
            # single replacement made the pass O(replacements * |V|). Completeness is unaffected:
            # the enclosing "while sequences_replaced" loop still runs to a fixpoint over the whole
            # graph, so a candidate that only becomes valid because of this replacement - for
            # instance a predecessor that can now extend its sequence through the new node - is
            # picked up by the next scan.
            #
            # The new node is pushed last so that it is the very next node examined, matching the
            # previous behaviour where it was the newest, and therefore first popped, node of the
            # rebuilt queue.
            queue.append(combined_context_node)
    return modification_applied

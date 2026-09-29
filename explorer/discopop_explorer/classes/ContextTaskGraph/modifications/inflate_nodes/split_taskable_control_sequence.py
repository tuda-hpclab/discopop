# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
import logging
from typing import TYPE_CHECKING, List, Optional, Tuple, cast

from discopop_explorer.classes.ContextTaskGraph.classes.edges import CTGEdgeInfo, CTGEdgeType
from discopop_explorer.classes.ContextTaskGraph.classes.CombinedContext import CombinedContext
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Contexts.TaskEndContext import TaskEndContext
from discopop_explorer.classes.TaskGraph.Contexts.TaskParentContext import TaskParentContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph
    from discopop_explorer.aliases.LineID import LineID

logger = logging.getLogger("Explorer")


def split_taskable_control_sequence(
    ctg: ContextTaskGraph, identified_tasks: List[TaskParentContext]
) -> Tuple[bool, List[TaskParentContext]]:
    """Split Control sequence between two Work or CombinedContext nodes, if there is no DATA edge between them.
    To Perform the split, a TaskParent dummy node is inserted before the first node of the sequence and both sequence nodes will become direct successors of the TaskParent node.
    Incoming dependencies to the Task nodes will be redirected to the TaskParentContext node.
    Outgoing dependencies from the Task nodes will be redirected to originate from the TaskEndContext node.
    Implementation relies on the successive application of __break_triangles for cleanup, as it will not remove the edge between the first node in the sequence and its predecessor.
    Returns True, if the graph was modified."""
    sequences_split = True
    modification_applied = False
    logger.warning(
        "Note: incoming data for data sharing clauses of suggested tasks can be retrieved before redirecting data edges to TaskParentContext and TaskEndContext nodes."
    )
    while sequences_split:
        sequences_split = False
        queue: List[Context] = list(ctg.graph.nodes())
        while len(queue) > 0:
            node = queue.pop()
            # check if node is of type Work or CombinedContext
            if not (isinstance(node, WorkContext) or isinstance(node, CombinedContext)):
                continue
            # iterate over outgoing edges and search for control edges
            control_edge_successors = [
                ctx
                for ctx in ctg.get_successors(node)
                if len([info for info in ctg.get_edge_info(node, ctx) if info.type == CTGEdgeType.CONTROL]) > 0
            ]
            # ensure that node has exactly one control edge successor  (todo: this might be extended in the future, but should not be necessary for regular operation)
            if len(control_edge_successors) != 1:
                continue
            # at this point, control_edge_successors should only contain a single element, otherwise multiple TaskParents and TaskEnds would be spawned
            for successor in control_edge_successors:
                # check if successor is of type Work or CombinedContext
                if not (isinstance(successor, WorkContext) or isinstance(successor, CombinedContext)):
                    continue
                # check if a data dependency between both nodes exist, i.e., whether both can be executed in parallel or not
                if (
                    len([info for info in ctg.get_edge_info(node, successor) if info.type == CTGEdgeType.DATA]) > 0
                    or len([info for info in ctg.get_edge_info(successor, node) if info.type == CTGEdgeType.DATA]) > 0
                ):
                    continue
                # check that both nodes share the same parent or code scope
                parent_1 = node.parent_context if not isinstance(node, CombinedContext) else node.outermost_context
                parent_2 = (
                    successor.parent_context
                    if not isinstance(successor, CombinedContext)
                    else successor.outermost_context
                )
                if parent_1 != parent_2:
                    # check if task is located in the same code scope.
                    # check if one of the parents opens a new scope
                    if type(parent_1) != WorkContext or type(parent_2) != WorkContext:
                        # one of the parents opens a new scope themselves
                        continue
                    # Check for equality of closest, non WorkContext ancestor of both parents
                    parent_anc_1 = [anc for anc in parent_1.get_ancestor_contexts() if type(anc) != WorkContext]
                    parent_anc_2 = [anc for anc in parent_2.get_ancestor_contexts() if type(anc) != WorkContext]
                    if len(parent_anc_1) == 0 or len(parent_anc_2) == 0:
                        # trivially no match possible
                        continue
                    if parent_anc_1[0] != parent_anc_2[0]:
                        # scopes do not match. The tasks are not valid
                        continue
                    # scopes do match. Use this scope for the parent. Tasks are valid. Continue to the next check.
                    parent_1 = parent_anc_1[0]

                # both can be executed in parallel. Create a TaskParent node and connect.
                if parent_1 is None:
                    continue
                task_parent_node = TaskParentContext()
                task_parent_node.register_parent_context(parent_1)
                task_end_node = TaskEndContext()
                task_parent_node.set_task_end(task_end_node)
                task_end_node.set_task_parent(task_parent_node)
                task_parent_node.register_task(node)
                task_parent_node.register_task(successor)
                identified_tasks.append(task_parent_node)
                # get source nodes of incoming control edges of node
                node_control_edge_predecessors = [
                    ctx
                    for ctx in ctg.get_predecessors(node)
                    if (len([info for info in ctg.get_edge_info(ctx, node) if info.type == CTGEdgeType.CONTROL]) > 0)
                ]
                # redirect CONTROL edges from node predecessors to task_parent_node
                for pred in node_control_edge_predecessors:
                    ctg.add_edge(pred, task_parent_node, CTGEdgeInfo(CTGEdgeType.CONTROL))
                    ctg.graph.remove_edge(pred, node)
                # get source nodes of incoming data edges of node
                node_data_edge_predecessors = [
                    ctx
                    for ctx in ctg.get_predecessors(node)
                    if (len([info for info in ctg.get_edge_info(ctx, node) if info.type == CTGEdgeType.DATA]) > 0)
                ]
                # redirect DATA edges from node predecessors to task_parent_node
                for pred in node_data_edge_predecessors:
                    ctg.add_edge(pred, task_parent_node, CTGEdgeInfo(CTGEdgeType.DATA))
                    ctg.graph.remove_edge(pred, node)
                # get source nodes of incoming control edges of successor
                succ_control_edge_predecessors = [
                    ctx
                    for ctx in ctg.get_predecessors(successor)
                    if (
                        len([info for info in ctg.get_edge_info(ctx, successor) if info.type == CTGEdgeType.CONTROL])
                        > 0
                    )
                ]
                # redirect CONTROL edges from successors predecessors to task_parent_node. only consider additional predecessors to node
                for pred in succ_control_edge_predecessors:
                    if pred == node:
                        continue
                    ctg.add_edge(pred, task_parent_node, CTGEdgeInfo(CTGEdgeType.CONTROL))
                    ctg.graph.remove_edge(pred, successor)
                # get source nodes of incoming data edges of successor
                succ_data_edge_predecessors = [
                    ctx
                    for ctx in ctg.get_predecessors(successor)
                    if (len([info for info in ctg.get_edge_info(ctx, successor) if info.type == CTGEdgeType.DATA]) > 0)
                ]
                # redirect DATA edges from successor predecessors to task_parent_node
                for pred in succ_data_edge_predecessors:
                    ctg.add_edge(pred, task_parent_node, CTGEdgeInfo(CTGEdgeType.DATA))
                    ctg.graph.remove_edge(pred, successor)
                # connect task_parent_node to node
                ctg.add_edge(task_parent_node, node, CTGEdgeInfo(CTGEdgeType.CONTROL))
                # connect task_parent_node to successor
                ctg.add_edge(task_parent_node, successor, CTGEdgeInfo(CTGEdgeType.CONTROL))
                # remove control edge between node and successor
                ctg.graph.remove_edge(node, successor)
                # connect node to task_end_node
                ctg.add_edge(node, task_end_node, CTGEdgeInfo(CTGEdgeType.CONTROL))
                # redirect outgoing control edges of successor through task_end_node (again, __break_triangles will cleanup)
                succ_control_edge_successors = [
                    ctx
                    for ctx in ctg.get_successors(successor)
                    if len([info for info in ctg.get_edge_info(successor, ctx) if info.type == CTGEdgeType.CONTROL]) > 0
                ]
                for succ in succ_control_edge_successors:
                    ctg.add_edge(task_end_node, succ, CTGEdgeInfo(CTGEdgeType.CONTROL))
                    ctg.graph.remove_edge(successor, succ)
                # connect successor to task_end_node
                ctg.add_edge(successor, task_end_node, CTGEdgeInfo(CTGEdgeType.CONTROL))

                # check for task loop:
                parent_is_same_loop = True
                parent_loop_node: Optional[LoopParentContext] = None
                for succ in succ_control_edge_successors:
                    if isinstance(succ.parent_context, LoopParentContext):
                        if parent_loop_node is None:
                            parent_loop_node = succ.parent_context
                        else:
                            if succ.parent_context != parent_loop_node:
                                parent_is_same_loop = False
                                break
                    else:
                        parent_is_same_loop = False
                        break
                # prevent false positives
                if parent_is_same_loop and len(succ_control_edge_successors) == 0:
                    parent_is_same_loop = False

                if False:  # disable task reporting for debug purposes
                    if parent_is_same_loop:
                        print(" === FOUND TASK LOOP ===")
                    else:
                        print(" === FOUND TASK ===")
                    print(" == Scope1: ")
                    print("    == root node: ", node)
                    scope_1: List[LineID] = node.get_code_scope(ctg.pet)
                    for ctx in node.get_contained_contexts(inclusive=True):
                        # lsprint("--> ctx: ", ctx)
                        scope_1 += ctx.get_code_scope(ctg.pet)
                    scope_1 = list(dict.fromkeys(scope_1))
                    print("    == scope size: ", len(scope_1))

                    print(" == Scope2: ", successor)
                    print("    == root node: ", successor)
                    scope_2: List[LineID] = successor.get_code_scope(ctg.pet)
                    for ctx in successor.get_contained_contexts(inclusive=True):
                        #    print("--> ctx: ", ctx)
                        scope_2 += ctx.get_code_scope(ctg.pet)
                    scope_2 = list(dict.fromkeys(scope_2))
                    print("    == scope size: ", len(scope_2))

                sequences_split = True
                modification_applied = True

    return modification_applied, identified_tasks

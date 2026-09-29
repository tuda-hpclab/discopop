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

from tqdm import tqdm  # type: ignore

from discopop_explorer.classes.ContextTaskGraph.classes.CombinedContext import CombinedContext
from discopop_explorer.classes.ContextTaskGraph.classes.edges import CTGEdgeInfo, CTGEdgeType
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph

logger = logging.getLogger("Explorer")


def replace_triangles(ctg: ContextTaskGraph) -> None:
    """Replace triangles in the graph with a CombinedContext node. Loop until no further triangles exist."""
    logger.info("Replacing triangles...")
    triangles_replaced = True
    while triangles_replaced:
        logger.info("--> iterating...")
        triangles_replaced = False
        queue: List[Context] = list(ctg.graph.nodes())
        while len(queue) > 0:
            node = queue.pop()
            predecessors = ctg.get_predecessors(node)
            if len(predecessors) < 2:
                continue
            # check all combinations of predecessors for triangles
            triangle_nodes: Optional[Tuple[Context, Context]] = None
            for pred_1 in predecessors:
                for pred_2 in predecessors:
                    if pred_1 == pred_2:
                        continue
                    # triangle exists, if pred_1 is a predecessor of pred_2 or vice versa
                    if pred_1 in ctg.get_predecessors(pred_2):
                        triangle_nodes = (pred_1, pred_2)
                        break
                    if pred_2 in ctg.get_predecessors(pred_1):
                        triangle_nodes = (pred_2, pred_1)
                        break
            if triangle_nodes is None:
                # did not find a triangle
                continue
            # replace triangle with CombinedContext
            combined_context_node = CombinedContext()
            if triangle_nodes[0].parent_context is None:
                continue
            combined_context_node.register_parent_context(triangle_nodes[0].parent_context)
            ctg.add_node(combined_context_node)
            # register contained contexts
            if isinstance(node, CombinedContext):
                combined_context_node.contained_contexts = combined_context_node.contained_contexts.union(
                    node.contained_contexts
                )
            else:
                combined_context_node.contained_contexts.add(node)

            if isinstance(triangle_nodes[0], CombinedContext):
                combined_context_node.contained_contexts = combined_context_node.contained_contexts.union(
                    triangle_nodes[0].contained_contexts
                )
            else:
                combined_context_node.contained_contexts.add(triangle_nodes[0])

            if isinstance(triangle_nodes[1], CombinedContext):
                combined_context_node.contained_contexts = combined_context_node.contained_contexts.union(
                    triangle_nodes[1].contained_contexts
                )
            else:
                combined_context_node.contained_contexts.add(triangle_nodes[1])

            # check validity of the transformation. Do not allow the creation of bi-directional edges
            # -> get predecessors and successors
            raw_outside_predecessors = [
                n
                for n in ctg.get_predecessors(node)
                + ctg.get_predecessors(triangle_nodes[0])
                + ctg.get_predecessors(triangle_nodes[1])
            ]
            raw_outside_successors = [
                n
                for n in ctg.get_successors(node)
                + ctg.get_successors(triangle_nodes[0])
                + ctg.get_successors(triangle_nodes[1])
            ]
            # -> remove duplicates
            raw_outside_predecessors = list(dict.fromkeys(raw_outside_predecessors))
            raw_outside_successors = list(dict.fromkeys(raw_outside_successors))
            # -> cleanup
            outside_predecessors = [
                n
                for n in raw_outside_predecessors
                if not (n == node or n == triangle_nodes[0] or n == triangle_nodes[1])
            ]
            outside_successors = [
                n for n in raw_outside_successors if not (n == node or n == triangle_nodes[0] or n == triangle_nodes[1])
            ]
            # -> check if bi-directional edges would be created
            skip_triangle = False
            for pred in outside_predecessors:
                if pred in outside_successors:
                    # bi-directional edge would be created! Ignore triangle.
                    skip_triangle = True
                    break
            if skip_triangle:
                continue

            # redirect incoming edges
            for pred in outside_predecessors:
                ctg.add_edge(pred, combined_context_node, edge_info=CTGEdgeInfo(CTGEdgeType.CONTROL))

            # redirect outgoing edges
            for succ in outside_successors:
                ctg.add_edge(combined_context_node, succ, edge_info=CTGEdgeInfo(CTGEdgeType.CONTROL))

            # remove triangle nodes from queue
            if triangle_nodes[0] in queue:
                queue.remove(triangle_nodes[0])
            if triangle_nodes[1] in queue:
                queue.remove(triangle_nodes[1])
            # delete triangle nodes
            ctg.graph.remove_node(node)
            ctg.graph.remove_node(triangle_nodes[0])
            ctg.graph.remove_node(triangle_nodes[1])
            # allow one more iteration
            triangles_replaced = True

    logger.info("--> removing trivial nodes")
    to_be_removed: List[Context] = []
    for node in tqdm(ctg.graph.nodes):
        if len(ctg.get_predecessors(node)) == 0 and len(ctg.get_successors(node)) == 0:
            to_be_removed.append(node)
    for node in to_be_removed:
        ctg.graph.remove_node(node)

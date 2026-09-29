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

from discopop_explorer.classes.ContextTaskGraph.classes.edges import CTGEdgeType
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph

logger = logging.getLogger("Explorer")


def break_triangles(ctg: ContextTaskGraph) -> bool:
    """search for triangles. If a triangle is found, delete the direct edge between triangle entry and exit node.
    As a result, the __control_sequence_simplification can combine the triangle into one CombinedContext node.
    Returns True, if a modification was applied."""
    logger.info("Breaking triangles...")
    triangles_broken = True
    modification_applied = False
    while triangles_broken:
        logger.info("--> iterating...")
        triangles_broken = False
        queue: List[Context] = list(ctg.graph.nodes())
        while len(queue) > 0:
            node = queue.pop()
            control_edge_predecessors = [
                ctx
                for ctx in ctg.get_predecessors(node)
                if (len([info for info in ctg.get_edge_info(ctx, node) if info.type == CTGEdgeType.CONTROL]) > 0)
            ]
            if len(control_edge_predecessors) < 2:
                continue
            # check all combinations of predecessors for triangles
            triangle_nodes: Optional[Tuple[Context, Context]] = None
            for pred_1 in control_edge_predecessors:
                for pred_2 in control_edge_predecessors:
                    if pred_1 == pred_2:
                        continue
                    # triangle exists, if pred_1 is a predecessor of pred_2 or vice versa
                    if pred_1 in ctg.get_predecessors(pred_2):
                        triangle_nodes = (pred_1, pred_2)
                        break
                    if pred_2 in ctg.get_predecessors(pred_1):
                        triangle_nodes = (pred_2, pred_1)
            if triangle_nodes is None:
                # did not find a triangle
                continue
            # delete the short triangle edge
            ctg.graph.remove_edge(triangle_nodes[0], node)
            triangles_broken = True
            modification_applied = True
    return modification_applied

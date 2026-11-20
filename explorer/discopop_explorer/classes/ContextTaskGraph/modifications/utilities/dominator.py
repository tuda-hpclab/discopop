# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
import logging
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from discopop_explorer.classes.ContextTaskGraph.classes.edges import CTGEdgeType
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph


logger = logging.getLogger("Explorer")


def _control_predecessors(ctg: ContextTaskGraph, ctx: Context) -> List[Context]:
    """The predecessors of ctx that have a CONTROL edge to it."""
    return [
        pred
        for pred in ctg.get_predecessors(ctx)
        if any(info.type == CTGEdgeType.CONTROL for info in ctg.get_edge_info(pred, ctx))
    ]


def control_predecessor_map(ctg: ContextTaskGraph) -> Dict[Context, List[Context]]:
    """The control predecessors of every node that has any. A caller that asks is_dominator many times builds it once
    and removes a predecessor from its entry when the CONTROL edge disappears."""
    result: Dict[Context, List[Context]] = {}
    for source, target in ctg.graph.edges():
        if any(info.type == CTGEdgeType.CONTROL for info in ctg.get_edge_info(source, target)):
            result.setdefault(target, []).append(source)
    return result


def is_dominator(
    ctg: ContextTaskGraph,
    ctx_1: Context,
    ctx_2: Context,
    control_predecessors: Optional[Dict[Context, List[Context]]] = None,
) -> bool:
    """Returns True if ctx_1 is a dominator of ctx_2.
    Returns False otherwise.

    Walks the CONTROL edges backwards from ctx_2 without passing ctx_1: ctx_1 dominates ctx_2 if it is reached on
    the way and no root (a node without CONTROL predecessors) is reachable without it.
    control_predecessors (see control_predecessor_map) saves looking at the edges of the graph in every step."""
    if ctx_1 == ctx_2:
        return True

    def predecessors_of(ctx: Context) -> List[Context]:
        if control_predecessors is None:
            return _control_predecessors(ctg, ctx)
        return control_predecessors.get(ctx, [])

    queue = list(predecessors_of(ctx_2))
    # everything that is or was in the queue; a set, as a membership test on the queue itself is linear
    seen: Set[Context] = set(queue)
    encountered_ctx_1 = False
    while queue:
        current = queue.pop()
        if current == ctx_1:
            encountered_ctx_1 = True
            continue
        predecessors = predecessors_of(current)
        if not predecessors:
            # root level reached without finding ctx_1. I.e., ctx_1 is not a dominator.
            return False
        for pred in predecessors:
            if pred not in seen:
                seen.add(pred)
                queue.append(pred)
    # check if ctx_1 was encountered to prevent false positives
    return encountered_ctx_1

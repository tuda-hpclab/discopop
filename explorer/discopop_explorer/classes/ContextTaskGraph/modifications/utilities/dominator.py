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

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph


logger = logging.getLogger("Explorer")


def is_dominator(ctg: ContextTaskGraph, ctx_1: Context, ctx_2: Context) -> bool:
    """Returns True if ctx_1 is a dominator of ctx_2.
    Returns False otherwise."""
    if ctx_1 == ctx_2:
        return True
    control_edge_predecessors = [
        ctx
        for ctx in ctg.get_predecessors(ctx_2)
        if (len([info for info in ctg.get_edge_info(ctx, ctx_2) if info.type == CTGEdgeType.CONTROL]) > 0)
    ]
    queue = control_edge_predecessors
    encountered_ctx_1 = False
    visited: Set[Context] = set()
    while len(queue):
        current = queue.pop()
        if current == ctx_1:
            encountered_ctx_1 = True
            continue
        visited.add(current)
        current_control_edge_predecessors = [
            ctx
            for ctx in ctg.get_predecessors(current)
            if (len([info for info in ctg.get_edge_info(ctx, current) if info.type == CTGEdgeType.CONTROL]) > 0)
        ]
        if len(current_control_edge_predecessors) == 0:
            # root level reached without finding ctx_1. I.e., ctx_1 is not a dominator.
            return False
        else:
            for pred in current_control_edge_predecessors:
                if pred not in visited and pred not in queue:
                    queue.append(pred)
    # check if ctx_1 was encountered to prevent false positives
    if encountered_ctx_1:
        return True
    return False

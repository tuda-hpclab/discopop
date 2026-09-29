# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
from typing import TYPE_CHECKING, List, Optional, Sequence
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.Node import Node

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges


def is_readonly_inside_loop_body(
    pet: PEGraphX,
    dep: Dependency,
    root_loop: Node,
    children_cus: Sequence[Node],
    children_loops: Sequence[Node],
    loops_start_lines: Optional[List[LineID]] = None,
) -> bool:
    """Checks, whether a variable is read-only in loop body

    :param dep: dependency variable
    :param root_loop: root loop
    :return: true if variable is read-only in loop body
    """
    if loops_start_lines is None:
        loops_start_lines = [v.start_position() for v in children_loops]

    for v in children_cus:
        for t, d in [
            (t, d)
            for s, t, d in out_edges(pet, v.id, EdgeType.DATA)
            if d.dtype == DepType.WAR or d.dtype == DepType.WAW
        ]:
            # If there is a waw dependency for var, then var is written in loop
            # (sink is always inside loop for waw/war)
            if dep.memory_region == d.memory_region and not (d.sink_line in loops_start_lines):
                return False
        for t, d in [(t, d) for s, t, d in in_edges(pet, v.id, EdgeType.DATA) if d.dtype == DepType.RAW]:
            # If there is a reverse raw dependency for var, then var is written in loop
            # (source is always inside loop for reverse raw)
            if dep.memory_region == d.memory_region and not (d.source_line in loops_start_lines):
                return False
    return True

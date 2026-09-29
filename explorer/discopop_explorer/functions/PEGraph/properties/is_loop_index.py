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
from discopop_explorer.classes.PEGraph.Node import Node

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import out_edges


def is_loop_index(
    pet: PEGraphX, var_name: Optional[str], loops_start_lines: List[LineID], children: Sequence[Node]
) -> bool:
    """Checks, whether the variable is a loop index.

    :param var_name: name of the variable
    :param loops_start_lines: start lines of the loops
    :param children: children nodes of the loops
    :return: true if edge represents loop index
    """

    # If there is a raw dependency for var, the source cu is part of the loop
    # and the dependency occurs in loop header, then var is loop index+

    for c in children:
        for t, d in [
            (t, d)
            for s, t, d in out_edges(pet, c.id, EdgeType.DATA)
            if d.dtype == DepType.RAW and d.var_name == var_name
        ]:
            if d.sink_line == d.source_line and d.source_line in loops_start_lines and pet.node_at(t) in children:
                return True

    return False

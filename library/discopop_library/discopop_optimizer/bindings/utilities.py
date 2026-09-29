# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import List, Optional, Set

import networkx as nx  # type: ignore

from discopop_library.discopop_optimizer.utilities.MOGUtilities import get_parents


def is_child_of_any(graph: nx.DiGraph, start_node: int, potential_parents: List[Optional[int]]) -> bool:
    """returns True, if start_node is a child of any of the potential_parents"""
    # get all parents of start_node
    all_parents: Set[int] = set()
    cur_parents = get_parents(graph, start_node)
    while len(cur_parents) != 0:
        cp = cur_parents.pop(0)
        all_parents.add(cp)
        cur_parents += get_parents(graph, cp)

    # check if an intersection exists with potential parents
    intersection = all_parents.intersection(set(potential_parents))

    # if so, start_node is a child of the potential parents
    if len(intersection) != 0:
        return True
    return False

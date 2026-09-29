# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Set
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import out_edges


def get_memory_regions(pet: PEGraphX, nodes: List[CUNode], var_name: str) -> Set[MemoryRegion]:
    """check dependencies of nodes for usages of 'var_name' and extract memory regions related to this name"""
    mem_regs: Set[MemoryRegion] = set()
    for node in nodes:
        out_deps = out_edges(pet, node.id, EdgeType.DATA)
        for s, t, d in out_deps:
            if d.var_name == var_name:
                if d.memory_region is not None:
                    mem_regs.add(d.memory_region)
    return mem_regs

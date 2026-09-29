# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Tuple, Set, cast

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_library.discopop_optimizer.classes.types.DataAccessType import (
    WriteDataAccess,
    ReadDataAccess,
)

next_free_unique_write_id: int = 0


def get_next_free_unique_write_id() -> int:
    global next_free_unique_write_id
    buffer = next_free_unique_write_id
    next_free_unique_write_id += 1
    return buffer


def get_data_accesses_for_cu(pet: PEGraphX, cu_id: NodeID) -> Tuple[Set[WriteDataAccess], Set[ReadDataAccess]]:
    """Calculates and returns the sets of accessed memory regions for the given cu node.
    The first element contains write accesses, the second element contains read accesses."""
    parent_function = get_parent_function(pet, pet.node_at(cu_id))
    subtree = subtree_of_type(pet, parent_function, CUNode)

    in_dep_edges = in_edges(pet, cu_id, EdgeType.DATA)
    out_dep_edges = out_edges(pet, cu_id, EdgeType.DATA)

    written_memory_regions = [
        WriteDataAccess(MemoryRegion(cast(str, d.memory_region)), get_next_free_unique_write_id(), d.var_name)
        for s, t, d in in_dep_edges
        if (d.dtype == DepType.RAW or d.dtype == DepType.WAW)
        and d.memory_region is not None
        and len(d.memory_region) != 0
    ]
    written_memory_regions += [
        WriteDataAccess(MemoryRegion(cast(str, d.memory_region)), get_next_free_unique_write_id(), d.var_name)
        for s, t, d in out_dep_edges
        if (d.dtype == DepType.WAR or d.dtype == DepType.WAW)
        and d.memory_region is not None
        and len(d.memory_region) != 0
    ]

    read_memory_regions = [
        ReadDataAccess(MemoryRegion(cast(str, d.memory_region)), d.var_name)
        for s, t, d in in_dep_edges
        if (d.dtype == DepType.WAR) and d.memory_region is not None and len(d.memory_region) != 0
    ]
    read_memory_regions += [
        ReadDataAccess(MemoryRegion(cast(str, d.memory_region)), d.var_name)
        for s, t, d in out_dep_edges
        if (d.dtype == DepType.RAW) and d.memory_region is not None and len(d.memory_region) != 0
    ]
    # remove duplicates (manual, since hashing MemoryRegions did not work as intended. might be fixed in the future)
    rmr_set: Set[ReadDataAccess] = set()
    for rmr in read_memory_regions:
        if str(rmr) not in [str(e) for e in rmr_set]:
            rmr_set.add(rmr)

    return set(written_memory_regions), rmr_set

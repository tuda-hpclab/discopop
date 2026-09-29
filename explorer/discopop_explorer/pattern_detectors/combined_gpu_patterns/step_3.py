# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Dict, List, Tuple, Set, Optional

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_explorer.pattern_detectors.combined_gpu_patterns.CombinedGPURegions import CombinedGPURegion

global_write_unique_id = 0


def initialize_writes(
    memory_region_liveness: Dict[MemoryRegion, List[NodeID]],
    written_memory_regions_by_cu: Dict[NodeID, Set[MemoryRegion]],
) -> Dict[MemoryRegion, Set[Tuple[NodeID, Optional[int]]]]:
    global global_write_unique_id

    result_dict: Dict[MemoryRegion, Set[Tuple[NodeID, Optional[int]]]] = dict()
    for mem_reg in memory_region_liveness:
        if mem_reg not in result_dict:
            result_dict[mem_reg] = set()
        for cu_id in memory_region_liveness[mem_reg]:
            written = False
            if cu_id in written_memory_regions_by_cu:
                if mem_reg in written_memory_regions_by_cu[cu_id]:
                    written = True
            optional_unique_write_id = None
            if written:
                optional_unique_write_id = global_write_unique_id
                global_write_unique_id += 1

            result_dict[mem_reg].add((cu_id, optional_unique_write_id))

    return result_dict


def propagate_writes(
    comb_gpu_reg: CombinedGPURegion, pet: PEGraphX, writes: Dict[MemoryRegion, Set[Tuple[NodeID, Optional[int]]]]
) -> Dict[MemoryRegion, Set[Tuple[NodeID, Optional[int]]]]:
    """propagate writes to parents.
     propagate writes to successors and their children.
     propagate writes to calling functions if a return has been reached.
    Stop on the level of the base function"""
    parent_functions: List[NodeID] = []
    for region in comb_gpu_reg.contained_regions:
        parent_functions.append(get_parent_function(pet, pet.node_at(region.node_id)).id)

    modification_found = True
    while modification_found:
        # propagate writes to parents
        modification_found = True
        while modification_found:
            modification_found = False
            for mem_reg in writes:
                for cu_id_1, write_identifier_1 in writes[mem_reg]:
                    if write_identifier_1 is None:
                        # no write
                        continue
                    # propagate to parents
                    for parent_id, _, _ in in_edges(pet, cu_id_1, EdgeType.CHILD):
                        if parent_id in parent_functions:
                            # do not propagate above the function which contains the GPU Regions
                            continue
                        if (parent_id, write_identifier_1) not in writes[mem_reg]:
                            writes[mem_reg].add((parent_id, write_identifier_1))
                            modification_found = True
                            # propagated to parent
                            break
                    if modification_found:
                        break
                if modification_found:
                    break

        # propagate to successors and their children
        modification_found = True
        while modification_found:
            modification_found = False
            for mem_reg in writes:
                for cu_id_1, write_identifier_1 in writes[mem_reg]:
                    if write_identifier_1 is None:
                        # no write
                        continue
                    # propagate to successors
                    for _, successor_id, _ in out_edges(pet, cu_id_1, EdgeType.SUCCESSOR):
                        if (successor_id, write_identifier_1) not in writes[mem_reg]:
                            writes[mem_reg].add((successor_id, write_identifier_1))
                            modification_found = True
                            # propagated to successor

                            # propagate to children of successors
                            for _, child_id, _ in out_edges(pet, successor_id, EdgeType.CHILD):
                                if (child_id, write_identifier_1) not in writes[mem_reg]:
                                    writes[mem_reg].add((child_id, write_identifier_1))
                                    modification_found = True
                                    # propagated to children of successor
                            # propagate to called functions of successors
                            for _, called_node_id, _ in out_edges(pet, successor_id, EdgeType.CALLSNODE):
                                if (called_node_id, write_identifier_1) not in writes[mem_reg]:
                                    writes[mem_reg].add((called_node_id, write_identifier_1))
                                    modification_found = True
                                    # propagated to called nodes of successor
                            break
                    if modification_found:
                        break
                if modification_found:
                    break

        # propagate writes to calling functions if a return has been reached.
        modification_found = True
        while modification_found:
            modification_found = False
            for mem_reg in writes:
                for cu_id, write_identifier in writes[mem_reg]:
                    pet_node = pet.node_at(cu_id)
                    if type(pet_node) != CUNode:
                        continue
                    if pet_node.return_instructions_count > 0:
                        # propagate write to calling cus
                        parent_function = get_parent_function(pet, pet_node)
                        callees = [s for s, t, d in in_edges(pet, parent_function.id, EdgeType.CALLSNODE)]
                        for callee_id in callees:
                            if (callee_id, write_identifier) not in writes[mem_reg]:
                                writes[mem_reg].add((callee_id, write_identifier))
                                modification_found = True
                                # propagated to callee
                        if modification_found:
                            break
                if modification_found:
                    break

    return writes


def cleanup_writes(
    writes: Dict[MemoryRegion, Set[Tuple[NodeID, Optional[int]]]],
) -> Dict[MemoryRegion, Set[Tuple[NodeID, Optional[int]]]]:
    """remove entries from the Sets with an second-element entry of None,
    if it is overwritten by a different memory write."""
    for mem_reg in writes:
        to_be_removed: Set[Tuple[NodeID, Optional[int]]] = set()
        # determine elements to be removed
        for cu_id, ident in writes[mem_reg]:
            if ident is None:
                continue
            if (cu_id, None) in writes[mem_reg]:
                # entry is overwritten by write access (cu_id, ident)
                to_be_removed.add((cu_id, None))
        # remove elements
        for cu_id, ident in to_be_removed:
            if (cu_id, ident) in writes[mem_reg]:
                writes[mem_reg].remove((cu_id, ident))
    return writes


def group_writes_by_cu(
    writes: Dict[MemoryRegion, Set[Tuple[NodeID, Optional[int]]]],
) -> Dict[NodeID, Dict[MemoryRegion, Set[Optional[int]]]]:
    result_dict: Dict[NodeID, Dict[MemoryRegion, Set[Optional[int]]]] = dict()

    for mem_reg in writes:
        for cu_id, ident in writes[mem_reg]:
            if cu_id not in result_dict:
                result_dict[cu_id] = dict()
            if mem_reg not in result_dict[cu_id]:
                result_dict[cu_id][mem_reg] = set()
            result_dict[cu_id][mem_reg].add(ident)
    return result_dict

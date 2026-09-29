# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Tuple, Dict, Set, cast

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import (
    VarName,
)
from discopop_explorer.pattern_detectors.simple_gpu_patterns.GPURegions import GPURegionInfo


def get_written_and_read_memory_regions_by_cu(
    contained_regions: List[GPURegionInfo], pet: PEGraphX
) -> Tuple[Dict[NodeID, Set[MemoryRegion]], Dict[NodeID, Set[MemoryRegion]]]:
    all_function_cu_ids: Set[NodeID] = set()
    for region in contained_regions:
        parent_function = get_parent_function(pet, pet.node_at(region.node_id))

        subtree = subtree_of_type(pet, parent_function, CUNode)
        all_function_cu_ids.update([NodeID(n.id) for n in subtree])

    written_memory_regions_by_cu_id: Dict[NodeID, Set[MemoryRegion]] = dict()
    read_memory_regions_by_cu_id: Dict[NodeID, Set[MemoryRegion]] = dict()
    for cu_id in all_function_cu_ids:
        in_dep_edges = in_edges(pet, cu_id, EdgeType.DATA)
        out_dep_edges = out_edges(pet, cu_id, EdgeType.DATA)

        written_memory_regions = [
            MemoryRegion(cast(str, d.memory_region))
            for s, t, d in in_dep_edges
            if (d.dtype == DepType.RAW or d.dtype == DepType.WAW)
            and d.memory_region is not None
            and len(d.memory_region) != 0
        ]
        written_memory_regions += [
            MemoryRegion(cast(str, d.memory_region))
            for s, t, d in out_dep_edges
            if (d.dtype == DepType.WAR or d.dtype == DepType.WAW)
            and d.memory_region is not None
            and len(d.memory_region) != 0
        ]

        read_memory_regions = [
            MemoryRegion(cast(str, d.memory_region))
            for s, t, d in in_dep_edges
            if (d.dtype == DepType.WAR) and d.memory_region is not None and len(d.memory_region) != 0
        ]
        read_memory_regions += [
            MemoryRegion(cast(str, d.memory_region))
            for s, t, d in out_dep_edges
            if (d.dtype == DepType.RAW) and d.memory_region is not None and len(d.memory_region) != 0
        ]

        if cu_id not in written_memory_regions_by_cu_id:
            written_memory_regions_by_cu_id[cu_id] = set()
        written_memory_regions_by_cu_id[cu_id] = set(written_memory_regions)

        if cu_id not in read_memory_regions_by_cu_id:
            read_memory_regions_by_cu_id[cu_id] = set()
        read_memory_regions_by_cu_id[cu_id] = set(read_memory_regions)
    return written_memory_regions_by_cu_id, read_memory_regions_by_cu_id


def get_cu_and_varname_to_memory_regions(
    contained_regions: List[GPURegionInfo], pet: PEGraphX, written_memory_regions_by_cu: Dict[NodeID, Set[MemoryRegion]]
) -> Dict[NodeID, Dict[VarName, Set[MemoryRegion]]]:
    # dict -> {Cu_ID: {var_name: [memory regions]}}
    result_dict: Dict[NodeID, Dict[VarName, Set[MemoryRegion]]] = dict()

    all_function_cu_ids: Set[NodeID] = set()
    for region in contained_regions:
        parent_function = get_parent_function(pet, pet.node_at(region.node_id))

        subtree = subtree_of_type(pet, parent_function, CUNode)
        all_function_cu_ids.update([NodeID(n.id) for n in subtree])

    for cu_id in all_function_cu_ids:
        if cu_id not in result_dict:
            result_dict[cu_id] = dict()

        # only out_deps considered, as in_deps might use variable names
        # which originate from different source code scopes
        out_dep_edges = out_edges(pet, cu_id, EdgeType.DATA)
        for _, _, dep in out_dep_edges:
            if dep.var_name is None or dep.memory_region is None or len(dep.memory_region) == 0:
                continue
            if dep.var_name not in result_dict[cu_id]:
                result_dict[cu_id][VarName(dep.var_name)] = set()
            result_dict[cu_id][VarName(dep.var_name)].add(dep.memory_region)

    return result_dict


def get_memory_region_to_cu_and_variables_dict(
    cu_and_variable_to_memory_regions: Dict[NodeID, Dict[VarName, Set[MemoryRegion]]],
) -> Dict[MemoryRegion, Dict[NodeID, Set[VarName]]]:
    # inverts the given cu_and_variable_to_memory_regions dictionary
    result_dict: Dict[MemoryRegion, Dict[NodeID, Set[VarName]]] = dict()

    for cu_id in cu_and_variable_to_memory_regions:
        for var_name in cu_and_variable_to_memory_regions[cu_id]:
            for mem_reg in cu_and_variable_to_memory_regions[cu_id][var_name]:
                if mem_reg not in result_dict:
                    result_dict[mem_reg] = dict()
                if cu_id not in result_dict[mem_reg]:
                    result_dict[mem_reg][cu_id] = set()
                result_dict[mem_reg][cu_id].add(var_name)
    return result_dict

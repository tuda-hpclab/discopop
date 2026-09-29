# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Dict, Set

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import (
    VarName,
)


def propagate_variable_name_associations(
    pet: PEGraphX,
    memory_regions_to_cus_and_variables: Dict[MemoryRegion, Dict[NodeID, Set[VarName]]],
) -> Dict[MemoryRegion, Dict[NodeID, Set[VarName]]]:
    """Replaces individual cu ids with id's of their parent functions."""
    updated_dict: Dict[MemoryRegion, Dict[NodeID, Set[VarName]]] = dict()

    for mem_reg in memory_regions_to_cus_and_variables:
        for cu_id in memory_regions_to_cus_and_variables[mem_reg]:
            var_names = memory_regions_to_cus_and_variables[mem_reg][cu_id]
            cu_node = pet.node_at(cu_id)
            # get parent function
            parent = get_parent_function(pet, cu_node)

            # save variable name association for parent function
            if mem_reg not in updated_dict:
                updated_dict[mem_reg] = dict()
            if parent.id not in updated_dict[mem_reg]:
                updated_dict[mem_reg][parent.id] = set()
            updated_dict[mem_reg][parent.id].update(var_names)

    return updated_dict

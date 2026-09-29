# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.NodeID import NodeID
from typing import Any, List, Optional, Set, Tuple

from discopop_explorer.functions.PEGraph.traversal.children import direct_children

global_pet: Optional[PEGraphX] = None


def pet_function_metadata_initialize_worker(pet: PEGraphX) -> None:
    global global_pet
    global_pet = pet


def pet_function_metadata_parse_func(func_node: FunctionNode) -> Tuple[NodeID, Any, set[NodeID]]:
    if global_pet is None:
        raise ValueError("global_pet is None!")

    stack: List[Node] = direct_children(global_pet, func_node)
    func_node.children_cu_ids = [node.id for node in stack]
    local_children: Set[NodeID] = set()

    while stack:
        child = stack.pop()
        local_children.add(child.id)
        children = direct_children(global_pet, child)
        func_node.children_cu_ids.extend([node.id for node in children])
        stack.extend(children)

    local_reachability_dict = func_node.calculate_reachability_pairs(global_pet)
    local_result = func_node.id, local_reachability_dict, local_children
    return local_result

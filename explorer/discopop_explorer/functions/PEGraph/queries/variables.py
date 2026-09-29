# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
from collections import deque
from typing import TYPE_CHECKING, Deque, Dict, List, Optional, Sequence, Set, cast
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.variable import Variable
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.properties.is_reduction_var_by_name import is_reduction_var_by_name
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type


def get_variable(pet: PEGraphX, root_node_id: NodeID, var_name: str) -> Optional[Variable]:
    """Search for the type of the given variable by BFS searching through successor edges in reverse, starting from
    the given root node, and checking the global and local vars of each encountered CU node."""
    queue: Deque[NodeID] = deque([root_node_id])
    visited: Set[NodeID] = set()
    while queue:
        current = queue.popleft()
        current_node = cast(CUNode, pet.node_at(current))
        visited.add(current)
        variables = current_node.local_vars + current_node.global_vars
        for v in variables:
            if v.name == var_name:
                return v
        # add predecessors of current to the list
        predecessors = [s for s, t, d in in_edges(pet, current, EdgeType.SUCCESSOR)]
        for pred in predecessors:
            if pred not in visited and pred not in queue:
                queue.append(pred)
    return None


def get_variables(pet: PEGraphX, nodes: Sequence[Node]) -> Dict[Variable, Set[MemoryRegion]]:
    """Gets all variables and corresponding memory regions in nodes

    :param nodes: nodes
    :return: Set of variables
    """
    res: Dict[Variable, Set[MemoryRegion]] = dict()
    for node in nodes:
        if isinstance(node, CUNode):
            for v in node.local_vars:
                if v not in res:
                    res[v] = set()
            for v in node.global_vars:
                if v not in res:
                    res[v] = set()
            # try to identify memory regions.
            # since the variable name is checked for equality afterwards,
            # it is safe to consider incoming dependencies at this point as well.
            # Note that INIT type edges are considered as well!
            # The node's dependencies do not depend on the variable, so they are collected once per
            # node and indexed by variable name. Querying them inside the loop over `res` re-filtered
            # all of the node's edges for every variable seen so far, which made this quadratic in
            # the number of variables and dominated the do-all pattern construction.
            memory_regions_by_var_name: Dict[str, Set[MemoryRegion]] = dict()
            for _, _, dep in out_edges(pet, node.id, EdgeType.DATA) + in_edges(pet, node.id, EdgeType.DATA):
                if dep.var_name is not None and dep.memory_region is not None:
                    memory_regions_by_var_name.setdefault(dep.var_name, set()).add(dep.memory_region)
            for var_name in res:
                res[var_name].update(memory_regions_by_var_name.get(var_name.name, set()))
    return res


def get_undefined_variables_inside_loop(
    pet: PEGraphX,
    root_loop: Node,
    include_global_vars: bool = False,
    include_called_functions: bool = False,
    root: Optional[Node] = None,
) -> Dict[Variable, Set[MemoryRegion]]:
    sub = subtree_of_type(pet, root_loop, CUNode, ignore_called_functions=True)
    vars = get_variables(pet, sub)
    if root_loop.start_line == 122 and root_loop.file_id == 9:
        pass
    dummyVariables = []
    definedVarsInLoop = []
    definedVarsInCalledFunctions = []

    # Remove llvm temporary variables
    for var in vars:
        if var.defLine == "LineNotFound" or "0:" in var.defLine:
            dummyVariables.append(var)
        elif not include_global_vars:
            if var.defLine == "GlobalVar" and not is_reduction_var_by_name(pet, root_loop.start_position(), var.name):
                dummyVariables.append(var)

    # vars = list(set(vars) ^ set(dummyVariables))
    for key in set(dummyVariables):
        if key in vars:
            del vars[key]

    # Exclude variables which are defined inside the loop
    for var in vars:
        if var.defLine >= root_loop.start_position() and var.defLine <= root_loop.end_position():
            definedVarsInLoop.append(var)

    # vars = list(set(vars) ^ set(definedVarsInLoop))
    for key in set(definedVarsInLoop):
        if key in vars:
            del vars[key]

    # Also, exclude variables which are defined inside
    # functions that are called within the loop
    for var in vars:
        for s in sub:
            if var.defLine >= s.start_position() and var.defLine <= s.end_position():
                definedVarsInCalledFunctions.append(var)

    # vars = list(set(vars) ^ set(definedVarsInCalledFunctions))
    for key in set(definedVarsInCalledFunctions):
        if key in vars:
            del vars[key]

    return vars

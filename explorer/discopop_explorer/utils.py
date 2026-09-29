# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations

import itertools
from typing import TYPE_CHECKING, Callable, List, Optional, Sequence, Set, Dict, Tuple, TypeVar, cast

import numpy as np
import warnings
from discopop_explorer.functions.PEGraph.properties.is_loop_index import is_loop_index
from discopop_explorer.functions.PEGraph.properties.is_reduction_var_by_name import is_reduction_var_by_name
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.reductions import get_reduction_sign
from discopop_explorer.functions.PEGraph.queries.subtree import get_left_right_subtree, subtree_of_type
from discopop_explorer.functions.PEGraph.queries.variables import get_undefined_variables_inside_loop, get_variables
from discopop_explorer.functions.PEGraph.traversal.children import (
    direct_children_or_called_nodes,
    direct_children_or_called_nodes_of_type,
)
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType

from discopop_library.HostpotLoader.HotspotType import HotspotType

from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.utilities.PEGraphConstruction.classes.LoopData import LoopData
from discopop_explorer.classes.variable import Variable

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX

loop_data: Dict[LineID, int] = {}

T = TypeVar("T")


def contains(list: List[T], filter: Callable[[T], bool]) -> bool:
    for x in list:
        if filter(x):
            return True
    return False


def correlation_coefficient(v1: List[float], v2: List[float]) -> float:
    """Calculates correlation coefficient as (A dot B) / (norm(A) * norm(B))

    :param v1: first vector
    :param v2: second vector
    :return: correlation coefficient, 0 if one of the norms is 0
    """
    norm_product = np.linalg.norm(v1) * np.linalg.norm(v2)  # type: ignore
    return 0 if norm_product == 0 else np.dot(v1, v2) / norm_product  # type: ignore


def find_subnodes(pet: PEGraphX, node: Node, criteria: EdgeType) -> List[Node]:
    """Returns direct children of a given node

    :param pet: PET graph
    :param node: CUNode
    :param criteria: EdgeType, type of edges to traverse
    :return: list of children nodes
    """
    return [pet.node_at(t) for s, t, d in out_edges(pet, node.id) if d.etype == criteria]


def depends(pet: PEGraphX, source: Node, target: Node) -> bool:
    """Detects if source node or one of it's children has a RAW dependency to target node or one of it's children

    :param pet: PET graph
    :param source: source node for dependency detection
    :param target: target of dependency
    :return: true, if there is RAW dependency
    """
    if source == target:
        return False
    target_nodes = subtree_of_type(pet, target)

    for node in subtree_of_type(pet, source, CUNode):
        for target in [
            pet.node_at(target_id)
            for source_id, target_id, dependence in out_edges(pet, node.id, EdgeType.DATA)
            if dependence.dtype == DepType.RAW
        ]:
            if target in target_nodes:
                return True
    return False


def is_loop_index2(pet: PEGraphX, root_loop: Node, var_name: str) -> bool:
    """Checks, whether the variable is a loop index.

    :param pet: CU graph
    :param root_loop: root loop
    :param var_name: name of the variable
    :return: true if variable is index of the loop
    """
    loops_start_lines = [v.start_position() for v in subtree_of_type(pet, root_loop, LoopNode)]
    return is_loop_index(pet, var_name, loops_start_lines, subtree_of_type(pet, root_loop, CUNode))


# NOTE: left old code as it may become relevant again in the near future
# We decided to omit the information that computes the workload and the relevant codes. For large programs (e.g., ffmpeg), the generated Data.xml file becomes very large. However, we keep the code here because we would like to integrate a hotspot detection algorithm (TODO: Bertin) with the parallelism discovery. Then, we need to retrieve the information to decide which code sections (loops or functions) are worth parallelizing.
def calculate_workload(pet: PEGraphX, node: Node, ignore_function_calls_and_cached_values: bool = False) -> int:
    """Calculates and stores the workload for a given node
    The workload is the number of instructions multiplied by respective number of iterations

    :param pet: PET graph
    :param node: root node
    :return: workload
    """
    # check if value already present
    if node.workload is not None:
        if not ignore_function_calls_and_cached_values:
            return node.workload
    res = 0
    if node.type == NodeType.DUMMY:
        # store workload
        node.workload = 0
        return 0
    elif node.type == NodeType.CU:
        # if a function is called, replace the instruction with the costs of the called function
        # note: recursive function calls are counted as a single instruction
        res += cast(CUNode, node).instructions_count
        if not ignore_function_calls_and_cached_values:
            for calls_edge in out_edges(pet, cast(CUNode, node).id, EdgeType.CALLSNODE):
                # add costs of the called function
                res += calculate_workload(
                    pet,
                    pet.node_at(calls_edge[1]),
                    ignore_function_calls_and_cached_values=ignore_function_calls_and_cached_values,
                )
                # substract 1 to ignore the call instruction
                # todo: should we keep the cost for the call instruction and just add the costs of the called funciton?
                res -= 1
    elif node.type == NodeType.FUNC:
        if not ignore_function_calls_and_cached_values:
            for child in find_subnodes(pet, node, EdgeType.CHILD):
                res += calculate_workload(
                    pet,
                    child,
                    ignore_function_calls_and_cached_values=ignore_function_calls_and_cached_values,
                )
    elif node.type == NodeType.LOOP:
        for child in find_subnodes(pet, node, EdgeType.CHILD):
            if child.type == NodeType.CU:
                if "for.inc" in cast(CUNode, child).basic_block_id:
                    res += cast(CUNode, child).instructions_count
                elif "for.cond" in cast(CUNode, child).basic_block_id:
                    # determine average iteration count. Use traditional iteration count as a fallback
                    average_iteration_count = (
                        cast(LoopNode, node).loop_iterations
                        if cast(LoopNode, node).loop_data is None
                        else cast(LoopData, cast(LoopNode, node).loop_data).average_iteration_count
                    )
                    res += (
                        calculate_workload(
                            pet,
                            child,
                            ignore_function_calls_and_cached_values=ignore_function_calls_and_cached_values,
                        )
                        * average_iteration_count
                        + 1
                    )
                else:
                    # determine average iteration count. Use traditional iteration count as a fallback
                    average_iteration_count = (
                        cast(LoopNode, node).loop_iterations
                        if cast(LoopNode, node).loop_data is None
                        else cast(LoopData, cast(LoopNode, node).loop_data).average_iteration_count
                    )
                    res += (
                        calculate_workload(
                            pet,
                            child,
                            ignore_function_calls_and_cached_values=ignore_function_calls_and_cached_values,
                        )
                        * average_iteration_count
                    )
            else:
                # determine average iteration count. Use traditional iteration count as a fallback
                average_iteration_count = (
                    cast(LoopNode, node).loop_iterations
                    if cast(LoopNode, node).loop_data is None
                    else cast(LoopData, cast(LoopNode, node).loop_data).average_iteration_count
                )
                res += (
                    calculate_workload(
                        pet,
                        child,
                        ignore_function_calls_and_cached_values=ignore_function_calls_and_cached_values,
                    )
                    * average_iteration_count
                )
    # store workload
    node.workload = res
    return res


def calculate_per_iteration_workload_of_loop(pet: PEGraphX, node: Node) -> int:
    """Calculates and returns the per iteration workload for a given node
    The workload is the number of instructions that happens within the loops body.
    The amount of iterations of the outer loop does not influence the result.
    :param pet: PET graph
    :param loop: root loop
    :return: workload per iteration
    """
    if node.type != NodeType.LOOP:
        raise ValueError("root has to be of type LOOP!")

    res = 0
    # sum up all children of the loops body (i.e. children excluding increment and condition)
    # in contrast to calculate_workload, do not multiply the amount of loop iterations to the workload of the children
    for child in find_subnodes(pet, node, EdgeType.CHILD):
        if child.type == NodeType.CU:
            if "for.inc" in cast(CUNode, child).basic_block_id:
                continue
            elif "for.cond" in cast(CUNode, child).basic_block_id:
                continue
            else:
                try:
                    res += calculate_workload(pet, child)
                except RecursionError as rerr:
                    warnings.warn("Cost calculation not possible for node: " + str(child.id) + "!")
        else:
            try:
                res += calculate_workload(pet, child)
            except RecursionError as rerr:
                warnings.warn("Cost calculation not possible for node: " + str(child.id) + "!")
    return res


def __get_dep_of_type(
    pet: PEGraphX, node: Node, dep_type: DepType, reversed: bool
) -> List[Tuple[NodeID, NodeID, Dependency]]:
    """Searches all dependencies of specified type

    :param pet: CU graph
    :param node: node
    :param dep_type: type of dependency
    :param reversed: if true the it looks for incoming dependencies
    :return: list of dependencies
    """
    return [
        e
        for e in (in_edges(pet, node.id, EdgeType.DATA) if reversed else out_edges(pet, node.id, EdgeType.DATA))
        if e[2].dtype == dep_type
    ]


def __get_variables(nodes: Sequence[Node]) -> Set[Variable]:
    """Gets all variables in nodes

    :param nodes: nodes
    :return: Set of variables
    """
    res = set()
    for node in nodes:
        if not isinstance(node, CUNode):
            continue
        for v in node.local_vars:
            res.add(v)
        for v in node.global_vars:
            res.add(v)
    return res


def is_reduction_var(line: LineID, name: str, reduction_vars: List[Dict[str, str]]) -> bool:
    """Determines, whether or not the given variable is reduction variable

    :param line: loop line number
    :param name: variable name
    :param reduction_vars: List of reduction variables
    :return: true if is reduction variable
    """
    return any(rv for rv in reduction_vars if rv["loop_line"] == line and rv["name"] == name)


def is_reduction_any(possible_lines: List[LineID], var_name: str, reduction_vars: List[Dict[str, str]]) -> bool:
    """Determines, whether or not the given variable is reduction variable

    :param possible_lines: possible loop line number
    :param name: variable name
    :param reduction_vars: List of reduction variables
    :return: true if is reduction variable
    """
    for line in possible_lines:
        if is_reduction_var(line, var_name, reduction_vars):
            return True

    return False


def is_written_in_subtree(
    mem_regs: Set[MemoryRegion],
    raw: Set[Tuple[NodeID, NodeID, Dependency]],
    waw: Set[Tuple[NodeID, NodeID, Dependency]],
    tree: List[Node],
) -> bool:
    """Checks if variable is written in subtree

    :param mem_reg: memory region
    :param raw: raw dependencies of the loop
    :param waw: waw dependencies of the loop
    :param tree: subtree
    :return: true if is written
    """
    for e in itertools.chain(raw, waw):
        if e[2].memory_region in mem_regs and any([n.id == e[1] for n in tree]):
            return True
    return False


def is_func_arg(pet: PEGraphX, var: str, node: Node) -> bool:
    """Checks if variable is a function argument

    :param pet: CU graph
    :param var: variable name
    :param node: loop node
    :return: true if variable is argument
    """
    # None may occur because __get_variables doesn't check for actual elements
    if var is None:
        return False
    if "." not in var:
        return False
    parents = [pet.node_at(edge[0]) for edge in in_edges(pet, node.id, EdgeType.CHILD)]
    # add current node to parents, if it is of type FUNC
    if isinstance(node, FunctionNode):
        parents.append(node)
    parent_functions = [cu for cu in parents if isinstance(cu, FunctionNode)]
    for pf in parent_functions:
        for arg in pf.args:
            if var.startswith(arg.name):
                return True
    return False


def is_scalar_val(var: Variable) -> bool:
    """Checks if variable is a scalar value

    :param var: variable
    :return: true if scalar
    """
    return not (var.type.endswith("**") or var.type.startswith("ARRAY") or var.type.startswith("["))


def is_readonly(
    mem_regs: Set[MemoryRegion],
    war: Set[Tuple[NodeID, NodeID, Dependency]],
    waw: Set[Tuple[NodeID, NodeID, Dependency]],
    rev_war: Set[Tuple[NodeID, NodeID, Dependency]],
) -> bool:
    """Checks if variable is readonly

    :param var: variable name
    :param war: war dependencies of the loop
    :param waw: waw dependencies of the loop
    :param rev_war: reversed raw dependencies of the loop
    :return: trie if readonly
    """
    for e in itertools.chain(war, waw, rev_war):
        if e[2].memory_region in mem_regs:
            return False
    return True


def is_global(var: str, tree: Sequence[Node]) -> bool:
    """Checks if variable is global

    :param var: variable name
    :param tree: nodes to search
    :return: true if global
    """

    for node in tree:
        if isinstance(node, CUNode):
            for gv in node.global_vars:
                if gv.name == var:
                    # TODO from tmp global vars
                    return True
    return False


def is_first_written(
    mem_regs: Set[MemoryRegion],
    raw: Set[Tuple[NodeID, NodeID, Dependency]],
    war: Set[Tuple[NodeID, NodeID, Dependency]],
    sub: List[CUNode],
) -> bool:
    """Checks whether a variable is first written inside the current node

    :param var: variable name
    :param raw: raw dependencies of the loop
    :param war: war dependencies of the loop
    :param sub: subtree of the loop
    :return: true if first written
    """
    for e in war:
        if e[2].memory_region in mem_regs and any([n.id == e[1] for n in sub]):
            res = False
            for eraw in raw:
                if (
                    eraw[2].memory_region in mem_regs
                    and any([n.id == e[1] for n in sub])
                    and e[2].source_line == eraw[2].sink_line
                ):
                    res = True
                    break
            if not res:
                return False

    # catch potential false-positives if len(war) == 0
    if len(war) == 0:
        for eraw in raw:
            if eraw[2].memory_region in mem_regs and eraw[1] not in [n.id for n in sub]:
                # value written prior to loop is read --> can not be first written
                return False
    return True


def is_first_written_new(
    var: Variable,
    mem_regs: Set[MemoryRegion],
    raw_deps: Set[Tuple[NodeID, NodeID, Dependency]],
    war_deps: Set[Tuple[NodeID, NodeID, Dependency]],
    reverse_raw_deps: Set[Tuple[NodeID, NodeID, Dependency]],
    reverse_war_deps: Set[Tuple[NodeID, NodeID, Dependency]],
    tree: Sequence[Node],
) -> bool:
    """Checks whether a variable is first written inside the current node

    :param var:
    :param raw_deps: raw dependencies of the loop
    :param war_deps: war dependencies of the loop
    :param reverse_raw_deps:
    :param reverse_war_deps:
    :param tree: subtree of the loop
    :return: true if first written
    """
    result = False
    # None may occur because __get_variables doesn't check for actual elements
    if var.name is None:
        return False
    is_read = is_read_in(mem_regs, raw_deps, war_deps, reverse_raw_deps, reverse_war_deps, tree)
    if var.name is None:
        print("Empty var.name found. Skipping.")
        return False
    for dep in raw_deps:
        assert dep[2].var_name is not None
        if dep[2].memory_region in mem_regs and any([n.id == dep[1] for n in tree]):
            result = True
            for warDep in war_deps:
                assert warDep[2].var_name is not None
                if (
                    warDep[2].memory_region in mem_regs
                    and any([n.id == dep[1] for n in tree])
                    and dep[2].source_line == warDep[2].sink_line
                ):
                    result = False
                    break
    return result or not is_read


def is_read_in_subtree(
    mem_regs: Set[MemoryRegion], rev_raw: Set[Tuple[NodeID, NodeID, Dependency]], tree: List[Node]
) -> bool:
    """Checks if variable is read in subtree

    :param var: variable name
    :param rev_raw: reversed raw dependencies of the loop
    :param tree: subtree
    :return: true if read in right subtree
    """
    for e in rev_raw:
        if e[2].memory_region in mem_regs and any([n.id == e[0] for n in tree]):
            return True
    return False


def is_read_in_right_subtree(
    mem_regs: Set[MemoryRegion], rev_raw: Set[Tuple[NodeID, NodeID, Dependency]], tree: List[CUNode]
) -> bool:
    """Checks if variable is read in subtree

    :param var: variable name
    :param rev_raw: reversed raw dependencies of the loop
    :param tree: subtree
    :return: true if read in right subtree
    """
    for e in rev_raw:
        if e[2].memory_region in mem_regs:
            if any([n.id == e[1] for n in tree]):
                if not any([k.id == e[0] for k in tree]):
                    return True
    return False


def is_depend_in_out(
    mem_regs: Set[MemoryRegion],
    in_deps: List[Tuple[NodeID, NodeID, Dependency]],
    out_deps: List[Tuple[NodeID, NodeID, Dependency]],
) -> bool:
    """there is an in and out dependency

    :param var: Variable
    :param in_deps: in dependencies
    :param out_deps: out dependencies
    :return: true if dependency is both in and out
    """
    for in_dep in in_deps:
        for out_dep in out_deps:
            if in_dep[2].memory_region in mem_regs and in_dep[2].memory_region == out_dep[2].memory_region:
                return True
    return False


def is_depend_in_var(
    mem_regs: Set[MemoryRegion],
    in_deps: List[Tuple[NodeID, NodeID, Dependency]],
    raw_deps_on: Set[Tuple[NodeID, NodeID, Dependency]],
) -> bool:
    """Checks if variable is written inside a dependent task and read in current task

    :param var: Variable
    :param in_deps: in dependencies
    :param raw_deps_on: raw dependencies
    :return: true if variable is in dependency
    """
    for in_dep in in_deps:
        if in_dep[2].memory_region in mem_regs and in_dep in raw_deps_on:
            return True
    return False


def is_depend_out_var(
    mem_regs: Set[MemoryRegion],
    reverse_raw_deps_on: Set[Tuple[NodeID, NodeID, Dependency]],
    out_deps: List[Tuple[NodeID, NodeID, Dependency]],
) -> bool:
    """Checks if variable is written inside a current task and read in dependent task

    :param var: Variable
    :param reverse_raw_deps_on: raw dependencies
    :param out_deps: in dependencies
    :return: true if variable is out dependency
    """
    for dep in out_deps:
        if dep[2].memory_region in mem_regs and dep in reverse_raw_deps_on:
            return True
    return False


def is_read_in(
    mem_regs: Set[MemoryRegion],
    raw_deps_on: Set[Tuple[NodeID, NodeID, Dependency]],
    war_deps_on: Set[Tuple[NodeID, NodeID, Dependency]],
    reverse_raw_deps_on: Set[Tuple[NodeID, NodeID, Dependency]],
    reverse_war_deps_on: Set[Tuple[NodeID, NodeID, Dependency]],
    tree: Sequence[Node],
) -> bool:
    """Check all reverse RAW dependencies (since we know that var is written in loop, because
    is_first_written returned true)

    :param var: variable
    :param raw_deps_on: raw dependencies
    :param war_deps_on: war dependencies
    :param reverse_raw_deps_on: reverse raw dependencies
    :param reverse_war_deps_on: reverse war dependencies
    :param tree: nodes of the loop
    :return:
    """
    for dep in raw_deps_on:
        # If there is a reverse raw dependency for var and the sink cu is not part
        # of the loop, then var is read in rst
        if dep[2].memory_region in mem_regs:
            return True
    for dep in war_deps_on:
        if dep[2].memory_region in mem_regs and any([n.id == dep[1] for n in tree]):
            return True
    for dep in reverse_raw_deps_on:
        # If there is a reverse raw dependency for var and the sink cu is not part
        # of the loop, then var is read in rst
        if dep[2].memory_region in mem_regs and any([n.id == dep[1] for n in tree]):
            return True
    for dep in reverse_war_deps_on:
        if dep[2].memory_region in mem_regs:
            return True
    return False


def get_child_loops(pet: PEGraphX, node: Node) -> Tuple[List[Node], List[Node]]:
    """Gets all do-all and reduction subloops

    :param pet: CU graph
    :param node: root node
    :return: list of do-all and list of reduction loop nodes
    """
    do_all: List[Node] = []
    reduction: List[Node] = []

    for loop_child in subtree_of_type(pet, node, LoopNode):
        if loop_child.do_all:
            do_all.append(loop_child)
        elif loop_child.reduction:
            reduction.append(loop_child)

    for func_child in direct_children_or_called_nodes_of_type(pet, node, FunctionNode):
        for child in direct_children_or_called_nodes_of_type(pet, func_child, CUNode):
            if child.do_all:
                do_all.append(child)
            elif child.reduction:
                reduction.append(child)

    return do_all, reduction


def get_initialized_memory_regions_in(
    pet: PEGraphX, cu_nodes: List[CUNode], include_called_functions: bool = True, root: Optional[Node] = None
) -> Dict[Variable, Set[MemoryRegion]]:
    initialized_memory_regions: Dict[Variable, Set[MemoryRegion]] = dict()
    root_parent_function: Optional[Node] = None
    if not include_called_functions:
        root_parent_function = get_parent_function(pet, cast(Node, root))
    for cu in cu_nodes:
        parent_function = get_parent_function(pet, cu)
        if not include_called_functions:
            if root_parent_function is not None:
                if parent_function != root_parent_function:
                    print("ROOT PARENT FUNCTION: ", root_parent_function.name)
                    print("---> SKIPPING CALLED FUNCTION: ", parent_function.name)
                    continue
        for s, t, d in out_edges(pet, cu.id, EdgeType.DATA):
            if d.dtype == DepType.INIT and d.memory_region is not None:
                # get variable object from cu
                for var in cu.global_vars + cu.local_vars:
                    if var.name == d.var_name:
                        # ignore pass by value type function arguments
                        is_passed_by_value = False
                        if str(parent_function.start_position()) == var.defLine:
                            for arg in parent_function.args:
                                if arg.name == var.name:
                                    if "*" not in arg.type:
                                        # found pass by value argument
                                        is_passed_by_value = True
                                        break
                        if is_passed_by_value:
                            continue

                        if var not in initialized_memory_regions:
                            initialized_memory_regions[var] = set()
                        # create entry for initialized variable
                        initialized_memory_regions[var].add(d.memory_region)

    return initialized_memory_regions


def classify_loop_variables(
    pet: PEGraphX, loop: Node
) -> Tuple[List[Variable], List[Variable], List[Variable], List[Variable], List[Variable]]:
    """Classifies variables inside the loop

    :param pet: CU graph
    :param loop: loop node
    :return: first_private, private, last_private, shared, reduction
    """
    first_private = []
    private = []
    last_private = []
    shared = []
    reduction = []
    lst = get_left_right_subtree(pet, loop, False)
    rst = get_left_right_subtree(pet, loop, True)
    sub: List[CUNode] = subtree_of_type(pet, loop, CUNode)

    raw = set()
    war = set()
    waw = set()
    rev_raw = set()

    for sub_node in sub:
        raw.update(__get_dep_of_type(pet, sub_node, DepType.RAW, False))
        war.update(__get_dep_of_type(pet, sub_node, DepType.WAR, False))
        waw.update(__get_dep_of_type(pet, sub_node, DepType.WAW, False))
        rev_raw.update(__get_dep_of_type(pet, sub_node, DepType.RAW, True))

    vars = get_undefined_variables_inside_loop(pet, loop, include_called_functions=False, root=loop)

    # only consider memory regions which are know at the current code location.
    # ignore memory regions which stem from called functions.
    left_subtree_without_called_nodes = get_left_right_subtree(pet, loop, False, ignore_called_nodes=True)
    prior_known_vars = get_variables(pet, left_subtree_without_called_nodes)
    prior_known_mem_regs = set()
    for pkv in prior_known_vars:
        prior_known_mem_regs.update(prior_known_vars[pkv])
    initialized_in_loop = get_initialized_memory_regions_in(
        pet, sub, include_called_functions=False, root=loop
    )  # TODO: CHECK IF THESE SHOULD INCLUDE INITS FROM CALLED FUNCTIONS!
    initialized_memory_regions: Set[MemoryRegion] = set()
    for var in initialized_in_loop:
        initialized_memory_regions.update(initialized_in_loop[var])
    uninitialized_vars: Dict[Variable, Set[MemoryRegion]] = dict()
    for var in vars:
        if var in prior_known_vars or var in initialized_in_loop:
            continue
        require_continue = False
        for entry in vars[var]:
            if entry in prior_known_mem_regs or entry in initialized_memory_regions:
                require_continue = True
                break
        if require_continue:
            continue

        uninitialized_vars[var] = vars[var]
    uninitialized_memregs: Set[MemoryRegion] = set()
    for var in uninitialized_vars:
        for mem_reg in uninitialized_vars[var]:
            uninitialized_memregs.add(mem_reg)

    for var in vars:
        vars[var] = set(
            [
                mem_reg
                for mem_reg in vars[var]
                if mem_reg in prior_known_mem_regs
                or mem_reg in initialized_memory_regions
                or mem_reg in uninitialized_memregs
            ]
        )

    # vars = list(pet.get_variables(sub))
    metadata_safe_index_accesses: List[Variable] = []
    for var in vars:
        if loop.start_position() == "2:517" and var.name == "nidx":  # (var.name == "d" or var.name == "d2"):
            pass
        # separate pointer and pointee dependencies for separated clasification
        # classifications will be merged before returning
        non_gep_mem_regs = set([mr for mr in vars[var] if not mr.startswith("GEPRESULT_")])
        gep_mem_regs = set([mr for mr in vars[var] if mr.startswith("GEPRESULT_")])

        for subset_idx, mem_reg_subset in enumerate([non_gep_mem_regs, gep_mem_regs]):
            if subset_idx >= 0 and len(mem_reg_subset) == 0:
                continue
            if is_loop_index2(pet, loop, var.name):
                if is_read_in_subtree(mem_reg_subset, rev_raw, rst):
                    last_private.append(var)
                else:
                    private.append(var)
            elif loop.reduction and is_reduction_var_by_name(pet, loop.start_position(), var.name):
                var.operation = get_reduction_sign(pet, loop.start_position(), var.name)
                reduction.append(var)
            elif (
                is_written_in_subtree(mem_reg_subset, raw, waw, lst)
                or is_func_arg(pet, var.name, loop)
                and is_scalar_val(var)
            ):
                if is_readonly(mem_reg_subset, war, waw, rev_raw):
                    if is_global(var.name, sub):
                        shared.append(var)
                    else:
                        first_private.append(var)
                elif is_read_in_subtree(mem_reg_subset, rev_raw, rst):
                    if is_scalar_val(var):
                        last_private.append(var)
                    else:
                        shared.append(var)
                else:
                    if not is_scalar_val(var):
                        # array type variable is written
                        shared.append(var)
                    else:
                        if is_first_written(mem_reg_subset, raw, waw, sub):
                            private.append(var)
                        else:
                            first_private.append(var)

            elif is_first_written(mem_reg_subset, raw, war, sub):
                if (len(mem_reg_subset.intersection(initialized_memory_regions)) > 0 and subset_idx < 1) or len(
                    mem_reg_subset.intersection(uninitialized_memregs)
                ) > 0:
                    # subset_idx < 1 to ignore this check for gep memory regions, as they create additional INIT dependencies
                    # variable is initialized in loop.

                    # No data sharing clauses required, if the variable is declared inside the loop.
                    if var_declared_in_subtree(var, sub):
                        pass
                    # Else, the variable requires a private clause
                    else:
                        private.append(var)
                else:
                    if is_read_in_subtree(mem_reg_subset, rev_raw, rst):
                        if is_scalar_val(var):
                            last_private.append(var)
                        else:
                            shared.append(var)
                    else:
                        # do not distinguish between scalar and structure types
                        private.append(var)
                        # keep old code until above replacement is proven to work
                        # BEGIN: OLD CODE
                        # if is_scalar_val(var):
                        #    private.append(var)
                        # else:
                        #    shared.append(var)
                        # END: OLD CODE
            if subset_idx >= 1 and no_inter_iteration_dependency_exists(
                mem_reg_subset, raw, war, sub, cast(LoopNode, loop)
            ):
                # check if metadata suggests, that index accesses are not problematic wrt. parallelization
                metadata_safe_index_accesses.append(var)

    # modify classifications
    # note: 23.07.25: disabled, since private is a more performant alternative to shared in most cases
    #    first_private, private, last_private, shared, reduction = __modify_classifications(
    #        first_private, private, last_private, shared, reduction, metadata_safe_index_accesses
    #    )

    # merge classifications
    first_private, private, last_private, shared, reduction = __merge_classifications(
        first_private, private, last_private, shared, reduction
    )

    # remove duplicates
    first_private = __remove_duplicate_variables(first_private)
    private = __remove_duplicate_variables(private)
    last_private = __remove_duplicate_variables(last_private)
    shared = __remove_duplicate_variables(shared)
    reduction = __remove_duplicate_variables(reduction)

    # return first_private, private, last_private, shared, reduction
    if loop.start_position() == "19:133":
        pass
    return (
        sorted(first_private),
        sorted(private),
        sorted(last_private),
        sorted(shared),
        sorted(reduction),
    )


def __remove_duplicate_variables(vars: List[Variable]) -> List[Variable]:
    buffer: List[str] = []
    vars_wo_duplicates: List[Variable] = []
    for var in vars:
        if str(var.name) + var.defLine not in buffer:
            vars_wo_duplicates.append(var)
            buffer.append(str(var.name) + var.defLine)
        else:
            # duplicate found
            continue
    return vars_wo_duplicates


def var_declared_in_subtree(var: Variable, sub: list[CUNode]) -> bool:
    try:
        var_file_id = int(var.defLine.split(":")[0])
        var_def_line = int(var.defLine.split(":")[1])
    except ValueError:
        return False
    for node in sub:
        if (node.file_id == var_file_id) and (node.start_line <= var_def_line) and (node.end_line >= var_def_line):
            return True
    return False


def no_inter_iteration_dependency_exists(
    mem_regs: Set[MemoryRegion],
    raw: Set[Tuple[NodeID, NodeID, Dependency]],
    war: Set[Tuple[NodeID, NodeID, Dependency]],
    sub: List[CUNode],
    root_loop: LoopNode,
) -> bool:
    for dep in raw.union(war):
        if dep[0] in [s.id for s in sub] and dep[1] in [s.id for s in sub]:
            if dep[2].memory_region in mem_regs:
                if dep[2].metadata_inter_iteration_dep is not None:
                    if root_loop.start_position() in dep[2].metadata_inter_iteration_dep:
                        return False
    return True


def __modify_classifications(
    first_private: list[Variable],
    private: list[Variable],
    last_private: list[Variable],
    shared: list[Variable],
    reduction: list[Variable],
    metadata_safe_index_accesses: list[Variable],
) -> Tuple[list[Variable], list[Variable], list[Variable], list[Variable], list[Variable]]:
    # Rule 1: if structure index accesses suggest, that parallelizing is safe without data sharing clauses, loosen private clauses to shared.
    # --> this rule does not affect first_ and last_private clauses, as they require a specific access / dependency pattern
    move_to_shared: List[Variable] = []
    for var in metadata_safe_index_accesses:
        if var in private:
            move_to_shared.append(var)
    for var in move_to_shared:
        if var in private:
            private.remove(var)
        if var not in shared:
            shared.append(var)

    return first_private, private, last_private, shared, reduction


def __merge_classifications(
    first_private: list[Variable],
    private: list[Variable],
    last_private: list[Variable],
    shared: list[Variable],
    reduction: list[Variable],
) -> Tuple[list[Variable], list[Variable], list[Variable], list[Variable], list[Variable]]:
    new_first_private: list[Variable] = []
    new_private: list[Variable] = []
    new_last_private: list[Variable] = []
    new_shared: list[Variable] = []
    new_reduction: list[Variable] = reduction

    remove_from_private: Set[Variable] = set()
    remove_from_first_private: Set[Variable] = set()
    remove_from_last_private: Set[Variable] = set()
    remove_from_shared: Set[Variable] = set()
    remove_from_reduction: Set[Variable] = set()

    # Rule 1: firstprivate is more restrictive than private
    for var_1 in first_private:
        for var_2 in private:
            if var_1.name == var_2.name:
                remove_from_private.add(var_2)
    # Rule 2: lastprivate is more restrictive than private
    for var_1 in last_private:
        for var_2 in private:
            if var_1.name == var_2.name:
                remove_from_private.add(var_2)
    # Rule 3: shared is less restrictive than first_private or last_private
    for var_1 in first_private + last_private:
        for var_2 in shared:
            if var_1.name == var_2.name:
                remove_from_shared.add(var_2)
    # Rule 4: if a variable is classifyable as shared and private, select shared.
    for var_1 in shared:
        for var_2 in private:
            if var_1.name == var_2.name:
                remove_from_private.add(var_2)

    new_first_private = [v for v in first_private if v not in remove_from_first_private]
    new_last_private = [v for v in last_private if v not in remove_from_last_private]
    new_private = [v for v in private if v not in remove_from_private]
    new_shared = [v for v in shared if v not in remove_from_shared]
    new_reduction = [v for v in reduction if v not in remove_from_reduction]

    return new_first_private, new_private, new_last_private, new_shared, new_reduction


def classify_task_vars(
    pet: PEGraphX,
    task: Node,
    type: str,
    in_deps: List[Tuple[NodeID, NodeID, Dependency]],
    out_deps: List[Tuple[NodeID, NodeID, Dependency]],
    used_in_task_parallelism_detection: bool = False,
) -> Tuple[List[Variable], List[Variable], List[Variable], List[Variable], List[Variable], List[Variable], List[str]]:
    """Classify task variables

    :param pet: CU graph
    :param task: node
    :param type: type of task
    :param in_deps: in dependencies
    :param out_deps: out dependencies
    :param used_in_task_parallelism_detection: set True, if called in a task-parallelism detection context
    """

    first_private: List[Tuple[Variable, Set[MemoryRegion]]] = []
    private: List[Tuple[Variable, Set[MemoryRegion]]] = []
    shared: List[Tuple[Variable, Set[MemoryRegion]]] = []
    depend_in: List[Tuple[Variable, Set[MemoryRegion]]] = []
    depend_out: List[Tuple[Variable, Set[MemoryRegion]]] = []
    depend_in_out: List[Tuple[Variable, Set[MemoryRegion]]] = []
    reduction_var_names: List[str] = []

    left_sub_tree = get_left_right_subtree(pet, task, False)

    right_sub_tree = get_left_right_subtree(pet, task, True)
    subtree = subtree_of_type(pet, task, CUNode)
    t_loop = subtree_of_type(pet, task, LoopNode)

    vars: Dict[Variable, Set[MemoryRegion]] = dict()
    if isinstance(task, FunctionNode):
        tmp = get_variables(pet, subtree)
        vars_strings = []
        for v in task.args:
            vars_strings.append(v.name)
        for v in tmp:
            # None may occur because __get_variables doesn't check for actual elements
            if v.name is None:
                continue

            if "." in v.name:
                name = v.name[0 : v.name.index(".")]  # substring before '.'
            else:
                name = v.name

            if name in vars_strings:
                vars[v] = tmp[v]
    else:
        vars = get_variables(pet, subtree)

    raw_deps_on = set()  # set<Dependence>
    war_deps_on = set()
    waw_deps_on = set()

    reverse_raw_deps_on = set()
    reverse_war_deps_on = set()
    reverse_waw_deps_on = set()

    for sub_node in subtree:
        # insert all entries from child_cu.RAW_deps_on into RAW_deps_on etc.
        raw_deps_on.update(__get_dep_of_type(pet, sub_node, DepType.RAW, False))
        war_deps_on.update(__get_dep_of_type(pet, sub_node, DepType.WAR, False))
        waw_deps_on.update(__get_dep_of_type(pet, sub_node, DepType.WAW, False))

        reverse_raw_deps_on.update(__get_dep_of_type(pet, sub_node, DepType.RAW, True))
        reverse_war_deps_on.update(__get_dep_of_type(pet, sub_node, DepType.WAR, True))
        reverse_waw_deps_on.update(__get_dep_of_type(pet, sub_node, DepType.WAW, True))

    do_all_loops, reduction_loops = get_child_loops(pet, task)
    # reduction_result = ""

    if isinstance(task, LoopNode):
        if task.reduction:
            reduction_loops.append(task)
        else:
            do_all_loops.append(task)

    loop_nodes: List[Node] = [n for n in t_loop if n.reduction]
    if task.reduction:
        loop_nodes.append(task)

    loops_start_lines = [n.start_position() for n in loop_nodes]
    loop_children = [c for n in loop_nodes for c in direct_children_or_called_nodes(pet, n)]

    for var in vars:
        var_is_loop_index = False
        # get RAW dependencies for var
        tmp_deps = [dep for dep in raw_deps_on if dep[2].memory_region in vars[var]]
        for edge in tmp_deps:
            if is_loop_index(pet, edge[2].var_name, loops_start_lines, loop_children):
                var_is_loop_index = True
                break
        if var_is_loop_index:
            private.append((var, vars[var]))
        elif ("GeometricDecomposition" in type or "Pipeline" in type) and is_reduction_any(
            loops_start_lines, var.name, pet.reduction_vars
        ):
            reduction_var_names.append(var.name)
        elif is_depend_in_out(vars[var], in_deps, out_deps):
            depend_in_out.append((var, vars[var]))
        elif is_depend_in_var(vars[var], in_deps, raw_deps_on):
            depend_in.append((var, vars[var]))
        elif is_depend_out_var(vars[var], reverse_raw_deps_on, out_deps):
            depend_out.append((var, vars[var]))
        elif (
            is_written_in_subtree(vars[var], raw_deps_on, waw_deps_on, left_sub_tree)
            or (is_func_arg(pet, var.name, task) and is_scalar_val(var))
        ) and is_readonly(vars[var], war_deps_on, waw_deps_on, reverse_raw_deps_on):
            if is_global(var.name, subtree):
                shared.append((var, vars[var]))
            else:
                first_private.append((var, vars[var]))
        elif is_first_written_new(
            var,
            vars[var],
            raw_deps_on,
            war_deps_on,
            reverse_raw_deps_on,
            reverse_war_deps_on,
            subtree,
        ):
            if is_scalar_val(var) and (
                not used_in_task_parallelism_detection or not __is_written_prior_to_task(pet, var, task)
            ):
                if is_read_in(
                    vars[var],
                    raw_deps_on,
                    war_deps_on,
                    reverse_raw_deps_on,
                    reverse_war_deps_on,
                    right_sub_tree,
                ):
                    shared.append((var, vars[var]))
                else:
                    private.append((var, vars[var]))
            else:
                shared.append((var, vars[var]))

    # use known variables to reconstruct the correct variable names from the classified memory regions
    left_subtree_without_called_nodes = get_left_right_subtree(pet, task, False, ignore_called_nodes=True)
    prior_known_vars = get_variables(pet, left_subtree_without_called_nodes)

    return (
        sorted(__apply_dealiasing(first_private, prior_known_vars)),
        sorted(__apply_dealiasing(private, prior_known_vars)),
        sorted(__apply_dealiasing(shared, prior_known_vars)),
        sorted(__apply_dealiasing(depend_in, prior_known_vars)),
        sorted(__apply_dealiasing(depend_out, prior_known_vars)),
        sorted(__apply_dealiasing(depend_in_out, prior_known_vars)),
        sorted(reduction_var_names),
    )


def __apply_dealiasing(
    input_list: List[Tuple[Variable, Set[MemoryRegion]]],
    previously_known: Dict[Variable, Set[MemoryRegion]],
) -> List[Variable]:
    tmp_memory_regions = set()
    for _, mem_regs in input_list:
        tmp_memory_regions.update(mem_regs)
    cleaned = [pkv for pkv in previously_known if len(previously_known[pkv].intersection(tmp_memory_regions))]
    return cleaned


def __is_written_prior_to_task(pet: PEGraphX, var: Variable, task: Node) -> bool:
    """Check if var has been written in predecessor of task.

    :param pet: CU graph
    :param var: variable
    :param task: node
    """
    # get predecessors of task
    queue: List[Node] = [task]
    visited: List[Node] = []
    predecessors: List[Node] = []
    while queue:
        current = queue.pop()
        if current not in visited:
            visited.append(current)
        if current not in predecessors:
            predecessors.append(current)
        queue += [
            pet.node_at(edge[0])
            for edge in in_edges(pet, current.id, EdgeType.SUCCESSOR)
            if pet.node_at(edge[0]) not in visited
        ]

    # check if raw-dependency on var to any predecessor exists)
    for out_dep in out_edges(pet, task.id, EdgeType.DATA):
        if out_dep[2].dtype != DepType.RAW:
            continue
        # check if out_dep.source in predecessors
        if pet.node_at(out_dep[0]) in predecessors:
            return True
    return False


def filter_for_hotspots(
    pet: PEGraphX,
    nodes: List[Node],
    hotspot_information: Optional[Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]],
) -> List[Node]:
    """Removes such nodes from the list which are not identified as hotspots"""
    if hotspot_information is None:
        return nodes
    if len(hotspot_information) == 0:
        return nodes
    # collect hotspot information
    all_hotspot_descriptions: List[Tuple[int, int, HotspotNodeType, str, float]] = []
    for key in hotspot_information:
        for entry in hotspot_information[key]:
            all_hotspot_descriptions.append(entry)

    result_set: Set[Node] = set()
    # check for direct matches
    for node in nodes:
        for hotspot in all_hotspot_descriptions:
            # check if file matches
            if hotspot[0] == node.file_id:
                # check if location matches
                if hotspot[1] == node.start_line:
                    # check if type matches
                    if node.type == NodeType.LOOP and hotspot[2] == HotspotNodeType.LOOP:
                        result_set.add(node)
                    if node.type == NodeType.FUNC and hotspot[2] == HotspotNodeType.FUNCTION:
                        result_set.add(node)

    #    # check for matches from hotspot functions
    #    for node in nodes:
    #        for hotspot in all_hotspot_descriptions:
    #            if hotspot[2] == HotspotNodeType.FUNCTION:
    #                if hotspot[0] == node.file_id:
    #                    try:
    #                        if pet.get_parent_function(node).name == hotspot[3]:
    #                            print("HOTSPOT FUNCTION MATCH FROM NODE: ", node.id)
    #                    except AssertionError:
    #                        continue

    return list(result_set)

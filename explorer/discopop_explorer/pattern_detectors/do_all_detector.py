# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import sys
from multiprocessing import Pool
from typing import List, Dict, Optional, Set, Tuple, cast
import warnings

from discopop_explorer.functions.PEGraph.properties.depends_ignore_readonly import depends_ignore_readonly
from discopop_explorer.functions.PEGraph.properties.is_loop_index import is_loop_index
from discopop_explorer.functions.PEGraph.properties.is_readonly_inside_loop_body import is_readonly_inside_loop_body
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.functions.PEGraph.queries.variables import get_variables
from discopop_explorer.functions.PEGraph.traversal.parent import get_all_parent_functions, get_parent_function
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType  # type: ignore
from discopop_library.StatusReporting.console import progress

from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.pattern_detectors.reduction_detector import ReductionInfo
from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
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
from discopop_explorer.utils import classify_loop_variables, filter_for_hotspots
from discopop_explorer.classes.variable import Variable


class DoAllInfo(PatternInfo):
    """Class, that contains do-all detection result"""

    def __init__(self, pet: PEGraphX, node: Node):
        """
        :param pet: PET graph
        :param node: node, where do-all was detected
        """
        PatternInfo.__init__(self, node)
        self.pragma = "#pragma omp parallel for"
        fp, p, lp, s, r = classify_loop_variables(pet, node)
        self.first_private = fp
        self.private = p
        self.last_private = lp
        self.shared = s
        self.reduction = r
        self.scheduling_clause = "static"
        self.collapse_level = 1
        # pattern ids of the do-all patterns which have been folded into this one by the loop
        # collapse analysis, outermost first. Empty for every non-collapsed pattern.
        # Applying this pattern excludes applying any of them: inserting a pragma between two
        # collapsed loops does not compile.
        self.collapsed_pattern_ids: List[int] = []
        self.pattern_tag = self.get_tag()

        # determine affected cu and line ids
        affected_cus = subtree_of_type(pet, node)
        self.affected_cu_ids = [n.id for n in affected_cus]
        self.affected_line_ids: List[LineID] = []
        for node in affected_cus:
            self.affected_line_ids += [
                lid for lid in node.get_contained_line_ids() if lid not in self.affected_line_ids
            ]
        self.affected_functions = [
            str(f.start_position()) + ":" + f.name for f in [get_parent_function(pet, node)]
        ]  # get_all_parent_functions(pet, node)]

    def __str__(self) -> str:
        return (
            f"Do-all at: {self.node_id}\n"
            f"Start line: {self.start_line}\n"
            f"End line: {self.end_line}\n"
            # f"iterations: {self.iterations_count}\n"
            # f"instructions: {self.instructions_count}\n"
            # f"workload: {self.workload}\n"
            f'pragma: "#pragma omp parallel for"\n'
            f"collapse: {self.collapse_level}\n"
            f"private: {[v.name for v in self.private]}\n"
            f"shared: {[v.name for v in self.shared]}\n"
            f"first private: {[v.name for v in self.first_private]}\n"
            f"reduction: {[v.name for v in self.reduction]}\n"
            f"last private: {[v.name for v in self.last_private]}\n"
            f"scheduling clause: {self.scheduling_clause}"
        )

    def get_tag(self) -> str:
        # the clause lists are materialized from sets, so their order is not reproducible
        # across runs. The tag identifies a pattern - including for the duplicate check in the
        # detectors - so it is built from sorted names.
        result = super().get_tag() + "_"
        result += f"p({sorted(v.name for v in self.private)})_"
        result += f"s({sorted(v.name for v in self.shared)})_"
        result += f"fp({sorted(v.name for v in self.first_private)})_"
        result += f"r({sorted(v.name for v in self.reduction)})_"
        result += f"lp({sorted(v.name for v in self.last_private)})_"
        # the collapse level distinguishes patterns which target the same loop but fold in a
        # different number of nested loops, and which may carry identical clauses
        result += f"c({self.collapse_level})"
        return result


global_pet = None


def run_detection(
    pet: PEGraphX,
    hotspots: Optional[Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]],
    reduction_info: List[ReductionInfo],
    jobs: Optional[int] = None,
) -> List[DoAllInfo]:
    """Search for do-all loop pattern

    :param pet: PET graph
    :return: List of detected pattern info
    """
    global global_pet
    global_pet = pet
    result: List[DoAllInfo] = []
    nodes = all_nodes(pet, LoopNode)

    ## DEBUG
    #    nodes = [n for n in nodes if n.file_id == 2]
    ## !DEBUG

    # remove reduction loops
    nodes = [n for n in nodes if n.id not in [r.node_id for r in reduction_info]]

    nodes = cast(List[LoopNode], filter_for_hotspots(pet, cast(List[Node], nodes), hotspots))

    param_list = [(node) for node in nodes]
    if jobs is None or jobs > 1:
        with Pool(initializer=__initialize_worker, initargs=(pet,)) as pool:
            tmp_result = list(progress(pool.imap_unordered(__check_node, param_list), total=len(param_list)))
        for local_result in tmp_result:
            result += local_result
    else:
        for param_tpl in param_list:
            result += __check_node(param_tpl)

    for pattern in result:
        pattern.get_workload(pet)
        pattern.get_per_iteration_workload(pet)

    # remove reduction operations from shared variables to prevent issues / incorrect results in the exported JSON file
    for idx, _ in enumerate(result):
        for idx_2, _ in enumerate(result[idx].shared):
            result[idx].shared[idx_2].operation = None

    return result


def __initialize_worker(pet: PEGraphX) -> None:
    global global_pet
    global_pet = pet


def __check_node(param_tuple: LoopNode) -> List[DoAllInfo]:
    global global_pet
    local_result = []
    node = param_tuple
    if global_pet is None:
        raise ValueError("global_pet is None!")

    if __detect_do_all(global_pet, node):
        node.do_all = True
        if not node.reduction and node.loop_iterations >= 0 and not node.contains_array_reduction:
            local_result.append(DoAllInfo(global_pet, node))

    return local_result


def __detect_do_all(pet: PEGraphX, root_loop: LoopNode) -> bool:
    """Calculate do-all value for node

    :param pet: PET graph
    :param root: root node
    :return: true if do-all
    """
    subnodes = [pet.node_at(t) for s, t, d in out_edges(pet, root_loop.id, [EdgeType.CHILD, EdgeType.CALLSNODE])]

    # get required metadata
    loop_start_lines: List[LineID] = []
    root_children = subtree_of_type(pet, root_loop, (CUNode, LoopNode), ignore_called_functions=False)
    root_children_cus = [cast(CUNode, cu) for cu in root_children if cu.type == NodeType.CU]
    root_children_loops = [cast(LoopNode, cu) for cu in root_children if cu.type == NodeType.LOOP]
    for v in root_children_loops:
        loop_start_lines.append(v.start_position())
    ## DEBUG
    if root_loop.start_line == 517:
        pass
    ## !DEBUG

    fp, p, lp, s, r = classify_loop_variables(pet, root_loop)

    # get parents of root_loop
    parent_loops = __get_parent_loops(pet, root_loop)
    parent_function_lineid = get_parent_function(pet, root_loop).start_position()
    called_functions_lineids = __get_called_functions(pet, root_loop)

    # get variables which are defined inside the loop
    defined_inside_loop: List[Tuple[Variable, Set[MemoryRegion]]] = []
    tmp_loop_variables = get_variables(pet, root_children_cus)
    for var in tmp_loop_variables:
        if ":" in var.defLine:
            file_id = int(var.defLine.split(":")[0])
            def_line_num = int(var.defLine.split(":")[1])
            for rc_cu in root_children_cus:
                if file_id == rc_cu.file_id and def_line_num >= rc_cu.start_line and def_line_num <= rc_cu.end_line:
                    defined_inside_loop.append((var, tmp_loop_variables[var]))

    # check if all subnodes are parallelizable
    file_io_warnings = []
    for node in subtree_of_type(pet, root_loop, CUNode):
        if node.performs_file_io:
            # node is not reliably parallelizable as some kind of file-io is performed.
            file_io_warnings.append(node)
            # return False  # too pessimistic
            # todo: issue critical around file_io

    for i in range(0, len(subnodes)):
        children_cache: Dict[Node, List[Node]] = dict()
        dependency_cache: Dict[Tuple[Node, Node], Set[Node]] = dict()
        for j in range(i, len(subnodes)):
            if __check_loop_dependencies(
                pet,
                subnodes[i],
                subnodes[j],
                root_loop,
                root_children_cus,
                root_children_loops,
                loop_start_lines,
                fp,
                p,
                lp,
                defined_inside_loop,
                parent_loops,
                parent_function_lineid,
                called_functions_lineids,
            ):
                # if pet.depends_ignore_readonly(subnodes[i], subnodes[j], root_loop):
                return False

    for fio in file_io_warnings:
        warnings.warn("FileIO performed inside DoAll @ " + str(node.start_position()))

    return True


def __check_loop_dependencies(
    pet: PEGraphX,
    node_1: Node,
    node_2: Node,
    root_loop: LoopNode,
    root_children_cus: List[CUNode],
    root_children_loops: List[LoopNode],
    loop_start_lines: List[LineID],
    first_privates: List[Variable],
    privates: List[Variable],
    last_privates: List[Variable],
    defined_inside_loop: List[Tuple[Variable, Set[MemoryRegion]]],
    parent_loops: List[LineID],
    parent_function_lineid: LineID,
    called_functions_lineids: List[LineID],
) -> bool:
    """Returns True, if dependencies between the respective subgraphs chave been found.
    Returns False otherwise, which results in the potential suggestion of a Do-All pattern."""
    # get recursive children of source and target
    node_1_children_ids = [node.id for node in subtree_of_type(pet, node_1, CUNode, ignore_called_functions=False)]
    node_2_children_ids = [node.id for node in subtree_of_type(pet, node_2, CUNode, ignore_called_functions=False)]

    # get dependency edges between children nodes
    deps = set()
    for n in node_1_children_ids + node_2_children_ids:
        deps.update(
            [(s, t, d) for s, t, d in in_edges(pet, n, EdgeType.DATA) if s in node_1_children_ids + node_2_children_ids]
        )
        deps.update(
            [
                (s, t, d)
                for s, t, d in out_edges(pet, n, EdgeType.DATA)
                if t in node_1_children_ids + node_2_children_ids
            ]
        )

    # get memory regions which are defined inside the loop
    memory_regions_defined_in_loop = set()
    for var, mem_regs in defined_inside_loop:
        memory_regions_defined_in_loop.update(mem_regs)

    pass

    for source, target, dep in deps:
        if root_loop.start_position() == "1:27":
            pass
        # todo: move this calculation to the innermost point possible to reduce computation costs
        # get metadata for dependency
        dep_source_nesting_level = __calculate_nesting_level(pet, root_loop, source)
        dep_target_nesting_level = __calculate_nesting_level(pet, root_loop, target)
        max_considered_intra_iteration_dep_level = max(dep_source_nesting_level, dep_target_nesting_level)

        # check if targeted variable is readonly inside loop
        if is_readonly_inside_loop_body(
            pet,
            dep,
            root_loop,
            root_children_cus,
            root_children_loops,
            loops_start_lines=loop_start_lines,
        ):
            # variable is readonly -> no problem
            continue

        # check if targeted variable is loop index
        if is_loop_index(pet, dep.var_name, loop_start_lines, root_children_cus):
            continue

        # if metadata exists, ignore dependencies where either source or sink do not lie within root_loop
        if dep.metadata_source_ancestors is not None and dep.metadata_sink_ancestors is not None:
            if len(dep.metadata_source_ancestors) > 0 and len(dep.metadata_sink_ancestors) > 0:
                if not (
                    (root_loop.start_position() in dep.metadata_sink_ancestors)
                    and root_loop.start_position() in dep.metadata_source_ancestors
                ):
                    tmp = root_loop.start_position()
                    continue

        # targeted variable is not read-only
        if dep.dtype == DepType.INIT:
            continue
        elif dep.dtype == DepType.RAW:
            # check RAW dependencies
            # RAW problematic, if it is not an intra-iteration RAW
            if (
                dep.metadata_intra_iteration_dep is None
                or dep.metadata_inter_iteration_dep is None
                or dep.metadata_intra_call_dep is None
                or dep.metadata_inter_call_dep is None
                or dep.metadata_sink_ancestors is None
                or dep.metadata_source_ancestors is None
                or (len(dep.metadata_sink_ancestors) == 0 and len(dep.metadata_source_ancestors) == 0)
            ):

                # no metadata created
                if not dep.intra_iteration:
                    return True
                else:
                    if dep.intra_iteration_level <= max_considered_intra_iteration_dep_level:
                        if pet.node_at(source) in root_children_cus and pet.node_at(target) in root_children_cus:
                            pass
                        else:
                            return True
            else:
                # metadata exists
                cond_1 = (len(dep.metadata_intra_iteration_dep) == 0) and parent_function_lineid in (
                    dep.metadata_intra_call_dep if dep.metadata_intra_call_dep is not None else []
                )
                cond_2 = len([cf for cf in called_functions_lineids if cf in dep.metadata_inter_call_dep]) > 0
                cond_3 = len([t for t in parent_loops if t in dep.metadata_inter_iteration_dep]) > 0
                cond_4 = root_loop.start_position() in dep.metadata_inter_iteration_dep
                # if cond_1 or cond_2 or cond_3:
                if cond_2 or cond_4:
                    return True
                # if it is an intra iteration dependency, it is problematic if it belongs to a parent loop
                else:
                    if dep.intra_iteration_level <= max_considered_intra_iteration_dep_level:
                        if pet.node_at(source) in root_children_cus and pet.node_at(target) in root_children_cus:
                            pass
                        else:
                            # check if metadata exists
                            if dep.metadata_intra_iteration_dep is not None:
                                for t in dep.metadata_intra_iteration_dep:
                                    if t in parent_loops:
                                        return True
                                return False
                            else:
                                return True

        elif dep.dtype == DepType.WAR:
            # check WAR dependencies
            # WAR problematic, if it is not an intra-iteration WAR and the variable is not private or firstprivate
            if dep.metadata_intra_iteration_dep is None:
                # no metadata created
                if not dep.intra_iteration:
                    if dep.var_name not in [v.name for v in first_privates + privates + last_privates]:
                        # check if variable is defined inside loop
                        if dep.memory_region not in memory_regions_defined_in_loop:
                            return True
                # if it is an intra iteration dependency, it is problematic if it belongs to a parent loop
                elif dep.intra_iteration_level > root_loop.get_nesting_level(pet):
                    return True

            else:
                # metadata exists
                if (
                    not dep.intra_iteration
                    and (dep.metadata_intra_iteration_dep is None or len(dep.metadata_intra_iteration_dep) == 0)
                    and parent_function_lineid
                    in (dep.metadata_intra_call_dep if dep.metadata_intra_call_dep is not None else [])
                ) or (
                    (
                        False
                        if dep.metadata_inter_call_dep is None
                        else (len([cf for cf in called_functions_lineids if cf in dep.metadata_inter_call_dep]) > 0)
                    )
                    and (
                        False
                        if dep.metadata_inter_iteration_dep is None
                        else (len([t for t in parent_loops if t in dep.metadata_inter_iteration_dep]) > 0)
                    )
                ):
                    if dep.var_name not in [v.name for v in first_privates + privates + last_privates]:
                        # check if variable is defined inside loop
                        if dep.memory_region not in memory_regions_defined_in_loop:
                            return True
                        # check if the definitions of the accessed variable originates from a function call
                        if __check_for_problematic_function_argument_access(pet, source, target, dep):
                            return True
                # if it is an intra iteration dependency, it is problematic if it belongs to a parent loop
                elif dep.intra_iteration_level > root_loop.get_nesting_level(pet):
                    tmp_nesting_level = root_loop.get_nesting_level(pet)
                    # check if metadata exists
                    if len(dep.metadata_intra_iteration_dep) != 0:
                        for t in dep.metadata_intra_iteration_dep:
                            if t in parent_loops:
                                return True
                        return False
                    else:
                        return True
        elif dep.dtype == DepType.WAW:
            # check WAW dependencies
            # handled by variable classification
            pass
        else:
            raise ValueError("Unsupported dependency type: ", dep.dtype)

    # no problem found. Potentially suggest Do-All
    return False


def __old_detect_do_all(pet: PEGraphX, root_loop: CUNode) -> bool:
    """Calculate do-all value for node

    :param pet: PET graph
    :param root: root node
    :return: true if do-all
    """
    subnodes = [pet.node_at(t) for s, t, d in out_edges(pet, root_loop.id, [EdgeType.CHILD, EdgeType.CALLSNODE])]

    # check if all subnodes are parallelizable
    for node in subtree_of_type(pet, root_loop, CUNode):
        if node.performs_file_io:
            # node is not reliably parallelizable as some kind of file-io is performed.
            return False

    for i in range(0, len(subnodes)):
        children_cache: Dict[CUNode, List[CUNode]] = dict()
        dependency_cache: Dict[Tuple[CUNode, CUNode], Set[CUNode]] = dict()
        for j in range(i, len(subnodes)):
            if depends_ignore_readonly(pet, subnodes[i], subnodes[j], root_loop):
                return False

    return True


def __calculate_nesting_level(pet: PEGraphX, root_loop: LoopNode, cu_node_id: str) -> int:
    potential_parents = [(cu_node_id, -1)]  # -1 to offset the initialization with cu_node_id
    while True:
        if len(potential_parents) == 0:
            # warnings.warn("root_loop: " + str(root_loop) + " not a parent of cu_node_id: " + str(cu_node_id))
            return sys.maxsize
        current_node_id, nesting_level = potential_parents.pop()
        if current_node_id == root_loop.id:
            # found
            return nesting_level
        # add new parents to the queue
        for in_child_edge in in_edges(pet, cast(NodeID, current_node_id), EdgeType.CHILD):
            potential_parents.append((in_child_edge[0], nesting_level + 1))


def __get_parent_loops(pet: PEGraphX, root_loop: LoopNode) -> List[LineID]:
    """duplicates exists: do_all_detector <-> reduction_detector !"""
    parents: List[NodeID] = []
    queue = [root_loop.id]
    visited: Set[NodeID] = set()
    while queue:
        current = queue.pop()
        visited.add(current)
        if type(pet.node_at(current)) == LoopNode:
            parents.append(current)

        # process incoming child edges
        for s, t, e in in_edges(pet, current, EdgeType.CHILD):
            if s not in visited and s not in queue:
                queue.append(s)
        # process incoming call edges
        for s, t, e in in_edges(pet, current, EdgeType.CALLSNODE):
            if s not in visited and s not in queue:
                queue.append(s)

    return [pet.node_at(p).start_position() for p in parents if p != root_loop.id]


def __get_called_functions(pet: PEGraphX, root_loop: LoopNode) -> List[LineID]:
    """duplicates exists: do_all_detector <-> reduction_detector !"""
    # identify children CUs without following function calls
    called_functions: Set[NodeID] = set()
    queue = [root_loop.id]
    visited: Set[NodeID] = set()
    while queue:
        current = queue.pop()
        visited.add(current)
        # get called functions
        for s, t, e in out_edges(pet, current, EdgeType.CALLSNODE):
            called_functions.add(t)
        # add children to queue
        for s, t, e in out_edges(pet, current, EdgeType.CHILD):
            if t not in queue and t not in visited:
                queue.append(t)

    # convert node ids of called functions to line ids
    return [pet.node_at(n).start_position() for n in called_functions]


def __check_for_problematic_function_argument_access(
    pet: PEGraphX, source: NodeID, target: NodeID, dep: Dependency
) -> bool:
    """duplicates exists: do_all_detector <-> reduction_detector !"""
    # check if the "same" function argument is accessed and it is a pointer type.
    # if so, return True. Else. return false

    # find accessed function argument for source
    source_pf = get_parent_function(pet, pet.node_at(source))
    source_accessed_pf_args = [a for a in source_pf.args if a.name == dep.var_name]
    if len(source_accessed_pf_args) == 0:
        return False

    # find accessed function argument for target
    target_pf = get_parent_function(pet, pet.node_at(target))
    target_accessed_pf_args = [a for a in target_pf.args if a.name == dep.var_name]
    if len(target_accessed_pf_args) == 0:
        return False

    # check for overlap in accessed args

    for source_a in source_accessed_pf_args:
        for target_a in target_accessed_pf_args:
            if source_a == target_a:
                # found overlap
                # check for pointer type
                if "*" in source_a.type:
                    return True
    # not problematic
    return False

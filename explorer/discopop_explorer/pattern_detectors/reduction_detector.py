# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


from multiprocessing import Pool
from typing import Dict, List, Optional, cast, Set, Tuple
import warnings

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
from discopop_explorer.utils import filter_for_hotspots, is_reduction_var, classify_loop_variables
from discopop_explorer.classes.variable import Variable


class ReductionInfo(PatternInfo):
    """Class, that contains reduction detection result"""

    def __init__(self, pet: PEGraphX, node: Node, reduction: Optional[List[Variable]] = None):
        """
        :param pet: PET graph
        :param node: node, where reduction was detected
        """
        PatternInfo.__init__(self, node)
        self.pragma = "#pragma omp parallel for"

        # fp, p, lp, s, r = classify_loop_variables(pet, node)

        self.first_private: List[Variable] = []
        self.private: List[Variable] = []
        self.last_private: List[Variable] = []
        self.shared: List[Variable] = []
        self.reduction: List[Variable] = [] if reduction is None else reduction
        self.pattern_tag = self.get_tag()
        self.collapse_level = 1

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
            f"Reduction at: {self.node_id}\n"
            f"Start line: {self.start_line}\n"
            f"End line: {self.end_line}\n"
            f"pragma: {self.pragma}\n"
            f"private: {[v.name for v in self.private]}\n"
            f"shared: {[v.name for v in self.shared]}\n"
            f"first private: {[v.name for v in self.first_private]}\n"
            f'reduction: {[str(v.operation) + ":" + v.name for v in self.reduction]}\n'
            f"last private: {[v.name for v in self.last_private]}"
        )

    def get_tag(self) -> str:
        # sorted, see DoAllInfo.get_tag
        result = super().get_tag() + "_"
        result += f"p({sorted(v.name for v in self.private)})_"
        result += f"s({sorted(v.name for v in self.shared)})_"
        result += f"fp({sorted(v.name for v in self.first_private)})_"
        result += f'r({sorted(str(v.operation) + ":" + v.name for v in self.reduction)})_'
        result += f"lp({sorted(v.name for v in self.last_private)})"
        return result


global_pet = None


def run_detection(
    pet: PEGraphX,
    hotspots: Optional[Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]],
    jobs: Optional[int] = None,
) -> List[ReductionInfo]:
    """Search for reduction pattern

    :param pet: PET graph
    :return: List of detected pattern info
    """
    global global_pet
    global_pet = pet
    result: List[ReductionInfo] = []
    nodes = all_nodes(pet, LoopNode)

    ## DEBUG
    #    nodes = [n for n in nodes if n.file_id == 2]
    ## !DEBUG

    nodes = cast(List[LoopNode], filter_for_hotspots(pet, cast(List[Node], nodes), hotspots))

    param_list = [(node) for node in nodes]
    if jobs is None or jobs > 1:
        with Pool(processes=jobs, initializer=__initialize_worker, initargs=(pet,)) as pool:
            tmp_result = list(progress(pool.imap_unordered(__check_node, param_list), total=len(param_list)))
        for local_result in tmp_result:
            result += local_result
    else:
        for param_tpl in param_list:
            result += __check_node(param_tpl)

    for pattern in result:
        pattern.get_workload(pet)
        pattern.get_per_iteration_workload(pet)

    return result


def __initialize_worker(pet: PEGraphX) -> None:
    global global_pet
    global_pet = pet


def __check_node(param_tuple: LoopNode) -> List[ReductionInfo]:
    global global_pet
    local_result: List[ReductionInfo] = []
    node = param_tuple
    if global_pet is None:
        raise ValueError("global_pet is None!")
    if __detect_reduction(global_pet, node):
        node.reduction = True
        if node.loop_iterations >= 0 and not node.contains_array_reduction:
            local_result.append(ReductionInfo(global_pet, node))

    return local_result


def __detect_reduction(pet: PEGraphX, root: LoopNode) -> bool:
    """Detects reduction pattern in loop
    :param pet: PET graph
    :param root: the loop node
    :return: true if is reduction loop
    """
    all_vars = []
    for node in subtree_of_type(pet, root, CUNode):
        all_vars.extend(node.local_vars)
        all_vars.extend(node.global_vars)

    # get required metadata
    loop_start_lines: List[LineID] = []
    root_children = subtree_of_type(pet, root, (CUNode, LoopNode), ignore_called_functions=False)
    root_children_cus: List[CUNode] = [cast(CUNode, cu) for cu in root_children if cu.type == NodeType.CU]
    root_children_loops: List[LoopNode] = [cast(LoopNode, cu) for cu in root_children if cu.type == NodeType.LOOP]
    for v in root_children_loops:
        loop_start_lines.append(v.start_position())
    reduction_vars = [
        v
        for v in all_vars
        if is_reduction_var(root.start_position(), v.name, pet.reduction_vars)
        # and "**" not in v.type --> replaced by check for array reduction
    ]
    reduction_var_names = cast(List[str], [v.name for v in reduction_vars])

    fp, p, lp, s, r = classify_loop_variables(pet, root)

    # get parents of loop
    parent_loops = __get_parent_loops(pet, root)
    parent_function_lineid = get_parent_function(pet, root).start_position()
    called_functions_lineids = __get_called_functions(pet, root)

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

    if __check_loop_dependencies(
        pet,
        root,
        root_children_cus,
        root_children_loops,
        loop_start_lines,
        reduction_var_names,
        fp,
        p,
        lp,
        defined_inside_loop,
        parent_loops,
        parent_function_lineid,
        called_functions_lineids,
    ):
        return False

    # mark loop as containing array reductions, if variable types are accordingly
    if reduction_vars and len([v for v in reduction_vars if "**" in v.type]) > 0:
        root.contains_array_reduction = True

    # if the loop contains any reduction variable, create a reduction suggestion
    return bool(reduction_vars)


def __check_loop_dependencies(
    pet: PEGraphX,
    root_loop: LoopNode,
    root_children_cus: List[CUNode],
    root_children_loops: List[LoopNode],
    loop_start_lines: List[LineID],
    reduction_var_names: List[str],
    first_privates: List[Variable],
    privates: List[Variable],
    last_privates: List[Variable],
    defined_inside_loop: List[Tuple[Variable, Set[MemoryRegion]]],
    parent_loops: List[LineID],
    parent_function_lineid: LineID,
    called_functions_lineids: List[LineID],
) -> bool:
    """Returns True, if dependencies between the respective subgraphs chave been found.
    Returns False otherwise, which results in the potential suggestion of a Reduction pattern."""
    # get recursive children of source and target
    loop_children_ids = [node.id for node in root_children_cus]

    # get dependency edges between children nodes
    deps = set()
    for n in loop_children_ids:
        deps.update([(s, t, d) for s, t, d in in_edges(pet, n, EdgeType.DATA) if s in loop_children_ids])
        deps.update([(s, t, d) for s, t, d in out_edges(pet, n, EdgeType.DATA) if t in loop_children_ids])

    # get memory regions which are defined inside the loop
    memory_regions_defined_in_loop = set()
    for var, mem_regs in defined_inside_loop:
        memory_regions_defined_in_loop.update(mem_regs)

    for source, target, dep in deps:
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
            # Reductions are only valid, if the value of the reduction variable is not stored in a shared variable.
            # This property is violated if a RAW dependency for the reduction variable between different CUs exist
            # since CUs follow the Read-Compute-Write pattern.
            if dep.var_name in reduction_var_names:
                if source != target:
                    # if raw_deps for reduction variables between different CU's exist,
                    # the above described property is violated
                    # --> not a valid reduction
                    return True
            else:
                # RAW does not target a reduction variable.
                # RAW problematic, if it is not an intra-iteration RAW.
                if (
                    dep.metadata_intra_iteration_dep is None
                    or dep.metadata_inter_iteration_dep is None
                    or dep.metadata_intra_call_dep is None
                    or dep.metadata_inter_call_dep is None
                    or dep.metadata_sink_ancestors is None
                    or dep.metadata_source_ancestors is None
                    or (len(dep.metadata_sink_ancestors) == 0 and len(dep.metadata_source_ancestors) == 0)
                ):
                    # no metadata generated
                    if not dep.intra_iteration:
                        return True
                else:
                    # metadata exist
                    cond_1 = (len(dep.metadata_intra_iteration_dep) == 0) and parent_function_lineid in (
                        dep.metadata_intra_call_dep if dep.metadata_intra_call_dep is not None else []
                    )
                    cond_2 = len([cf for cf in called_functions_lineids if cf in dep.metadata_inter_call_dep]) > 0
                    cond_3 = len([t for t in parent_loops if t in dep.metadata_inter_iteration_dep]) > 0
                    cond_4 = root_loop.start_position() in dep.metadata_inter_iteration_dep
                    # if cond_1 or cond_2 or cond_3:
                    if cond_2 or cond_4:
                        return True
        elif dep.dtype == DepType.WAR:
            # check WAR dependencies
            # WAR problematic, if it is not an intra-iteration WAR and the variable is not private or firstprivate
            if dep.metadata_intra_iteration_dep is None:
                # no metadata generated
                if not dep.intra_iteration:
                    if dep.var_name not in [v.name for v in first_privates + privates + last_privates]:
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
                            pass
                            return True
        elif dep.dtype == DepType.WAW:
            # check WAW dependencies
            # handled by variable classification
            pass
        else:
            raise ValueError("Unsupported dependency type: ", dep.dtype)

    # no problem found. Potentially suggest reduction
    return False


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

    return [pet.node_at(p).start_position() for p in parents]


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

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import os
from enum import IntEnum
from typing import List, Set, Optional, Union, Any, Dict, Tuple, cast

from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.functions.PEGraph.properties.is_reduction_var_by_name import is_reduction_var_by_name
from discopop_explorer.functions.PEGraph.queries.memory_regions import get_memory_regions
from discopop_explorer.functions.PEGraph.queries.reductions import get_reduction_sign
from discopop_explorer.functions.PEGraph.queries.subtree import get_left_right_subtree, subtree_of_type
from discopop_explorer.functions.PEGraph.queries.variables import get_undefined_variables_inside_loop, get_variables
from discopop_explorer.functions.PEGraph.traversal.children import direct_children
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_explorer.functions.PEGraph.traversal.successors import direct_successors
from discopop_explorer.utils import (
    __get_dep_of_type as get_dep_of_type,
)
from discopop_explorer.utilities.PEGraphConstruction.ParserUtilities import parse_id
from discopop_explorer.utils import (
    is_scalar_val,
    is_loop_index2,
    classify_loop_variables,
    get_initialized_memory_regions_in,
)
from discopop_explorer.utils import (
    is_written_in_subtree,
    is_func_arg,
    is_readonly,
    is_global,
    is_read_in_right_subtree,
    is_first_written,
    is_read_in_subtree,
)
from discopop_explorer.classes.variable import Variable
from discopop_library.MemoryRegions.utils import get_sizes_of_memory_regions
from discopop_library.result_classes.DetectionResult import DetectionResult
from discopop_explorer.pattern_detectors.simple_gpu_patterns.GPUMemory import getCalledFunctions, map_node

"""
def remove_duplicates(my_list: List) -> List:
    ""removes the duplicates of a given list

    :param my_list:
    :return:
    ""
    return list(dict.fromkeys(my_list))
"""


def fmt_vars(v: List[Variable]) -> str:
    """inserts the elements of the VarID vector 'v' into 'ss';
        elements are separated by ','

    :param v:
    :return:
    """
    if not v:  # if (v.empty())
        return ""

    ss: str = v[0].name
    for i in range(1, len(v)):
        ss += ", " + v[i].name
    return ss


def omp_clause_str(name: str, args: List[str]) -> str:
    """generates a string for omp clauses/constructs

    :param name: contains 'args' if args list is not empty
    :param args:
    :return:
    """

    # check if "args" contained in name
    if "args" in name and len(args) > 0:
        # replace "args" with contents of args list
        return name.replace("args", ",".join(args))
    elif len(args) == 0:
        return name
    else:
        raise ValueError("Unsupported name: ", name, "and args:", args)


def omp_clause_str_old(name: str, args: List[str]) -> str:
    """generates a json-string for omp clauses/constructs

    :param name:
    :param args:
    :return:
    """
    # name, converted std::ostringstream to str
    result: str = '{"name":"' + name + '",'

    # args
    result += '"args":['
    if args:
        result += '"' + args[0] + '"'
        for i in range(1, len(args)):
            result += ',"' + args[i] + '"'
    result += "]}"
    return result


def omp_construct_str(name: str, line: int, clauses: List[str]) -> str:
    """

    :param name:
    :param line:
    :param clauses:
    :return:
    """
    result: str = '{"name":"' + name + '",'
    result += '"line":' + str(line) + ","
    result += '"clauses":['
    if clauses:
        result += clauses[0]
    for i in range(1, len(clauses)):
        result += "," + clauses[i]
    result += "]}"
    return result


class OmpConstructPositioning(IntEnum):
    BEFORE_LINE = 0
    AFTER_LINE = 1


def omp_construct_dict(
    name: str,
    line: LineID,
    clauses: List[str],
    positioning: OmpConstructPositioning = OmpConstructPositioning.BEFORE_LINE,
) -> Dict[str, Union[str, LineID, List[str], OmpConstructPositioning]]:
    """

    :param name:
    :param line:
    :param clauses:
    :return:
    """
    result: Dict[str, Union[str, LineID, List[str], OmpConstructPositioning]] = dict()
    result["name"] = name
    result["line"] = line
    result["clauses"] = clauses
    result["positioning"] = positioning
    return result


# inherits from class ParallelPattern (=PatternInfo)
class GPULoopPattern(PatternInfo):
    # public:
    called_functions: Set[NodeID]
    map_type_to: List[Variable]
    map_type_from: List[Variable]
    map_type_tofrom: List[Variable]
    map_type_alloc: List[Variable]
    reduction_vars_str: List[str]
    reduction_vars_ids: List[Variable]
    iteration_count: int = 0
    has_scalar_reduction_var: bool
    nodeID: NodeID
    # new
    nestedLoops: Set[NodeID]
    nextLoop: Optional[NodeID]
    parentLoop: str
    collapse: int
    scheduling: str
    constructs: List[Dict[Any, Any]]
    project_folder_path: str

    def __init__(
        self,
        pet: PEGraphX,
        nodeID: NodeID,
        startLine: LineID,
        endLine: LineID,
        iterationCount: int,
        project_folder_path: str,
        reduction_vars: Optional[List[Variable]] = None,
    ):
        node = map_node(pet, nodeID)
        super().__init__(node)  # PatternInfo(node)
        PatternInfo.iterations_count = iterationCount
        self.has_scalar_reduction_var = False  # copy.deepcopy(False)
        self.nodeID = nodeID
        self.startLine = startLine
        self.endLine = endLine
        self.iterationCount = iterationCount
        self.project_folder_path = project_folder_path
        # explicitly initialize empty, else it will copy values of other patterns
        self.map_type_to = []
        self.map_type_tofrom = []
        self.map_type_alloc = []
        self.map_type_from = []
        # should also be done with all others? probably
        self.nestedLoops = set()
        self.called_functions = set()
        if reduction_vars is None:
            self.reduction_vars_str: List[str] = []
            self.reduction_vars_ids: List[Variable] = []
        else:
            self.reduction_vars_str: List[str] = [cast(str, v.operation) + ":" + v.name for v in reduction_vars]
            self.reduction_vars_ids: List[Variable] = reduction_vars
        self.iteration_count = 0
        self.nextLoop = None
        self.parentLoop = ""
        self.collapse = 1
        self.scheduling = ""
        self.constructs = []
        self.declared_global_variables: Set[Variable] = set()

    def __str__(self) -> str:
        raise NotImplementedError()  # used to identify necessity to call to_string() instead

    def to_string(self, pet: PEGraphX) -> str:
        constructs = self.__get_constructs(pet, self.project_folder_path)
        construct_str = "\n" if len(constructs) > 0 else ""
        for entry in constructs:
            for key in entry:
                construct_str += "\t" + key + ": " + str(entry[key]) + "\n"
            construct_str += "\n"
        return (
            f"{'DoAll (GPU)' if not self.reduction_vars_str else 'Reduction (GPU)'} at: {self.node_id}\n"
            f"Start line: {self.startLine}\n"
            f"End line: {self.endLine}\n"
            f"Collapse: {self.collapse}\n"
            f"Map to: {self.map_type_to}\n"
            f"Map from: {self.map_type_from}\n"
            f"Map to_from: {self.map_type_tofrom}\n"
            f"Map alloc: {self.map_type_alloc}\n"
            f"Reduction vars: {self.reduction_vars_str}\n"
            f"OpenMP constructs: {construct_str}\n"
        )

    def save_omp_constructs(self, pet: PEGraphX, project_folder_path: str) -> None:
        """Save OpenMP constructs such that they are included in the exported JSON file."""
        constructs = self.__get_constructs(pet, project_folder_path)
        self.constructs = constructs

    def toJson(self, pet: PEGraphX, project_folder_path: str) -> str:
        """Generates a json-string which contains the information about how to
            implement this pattern using OpenMP constructs

        :return:
        """
        json_output: str = "{"
        # == == Metadata == ==
        json_output += '"id":"' + str(self.nodeID) + '",'
        json_output += '"startline":"' + self.start_line + '",'
        json_output += '"endline":"' + self.end_line + '",'

        # == == Type == ==
        json_type: str = "DoAll (GPU)" if not self.reduction_vars_str else "Reduction (GPU)"
        json_output += '"type":"' + json_type + '",'

        # == == Constructs == ==
        json_output += '"constructs":['

        constructs: List[Any] = self.__get_constructs(pet, project_folder_path)

        # add all constructs to the output string
        json_output += constructs[0]
        for i in range(1, len(constructs)):
            json_output += "," + constructs[i]

        json_output += "]}"
        return json_output

    def __get_constructs(
        self, pet: PEGraphX, project_folder_path: str
    ) -> List[Dict[str, Union[str, LineID, List[str], OmpConstructPositioning]]]:
        constructs: List[Dict[str, Union[str, LineID, List[str], OmpConstructPositioning]]] = []

        # == default construct ==
        clauses: List[str] = []
        var_names: List[str] = []
        modified_var_names: List[str] = []
        subnodes = subtree_of_type(pet, pet.node_at(self.node_id), CUNode)
        if self.map_type_to:
            modified_var_names = []
            for var in self.map_type_to:
                memory_regions = get_memory_regions(pet, subnodes, var.name)

                # get size of memory region
                memory_region_sizes = get_sizes_of_memory_regions(
                    memory_regions, os.path.join(project_folder_path, "profiler/memory_regions.txt")
                )
                if len(memory_region_sizes) > 0:
                    max_mem_reg_size = max(memory_region_sizes.values())
                    # divide memory region size by size of variable
                    # construct new list of modified var names
                    modified_var_names.append(
                        (
                            # var.name + "[:]"
                            var.name + "[:" + str(int(max_mem_reg_size / var.sizeInByte)) + "]"
                            if "**" in var.type
                            else var.name
                        )
                    )
                else:
                    modified_var_names.append(var.name + "[:]" if "**" in var.type else var.name)

            clauses.append(omp_clause_str("map(to: args)", modified_var_names))
            var_names = []

        if self.map_type_from:
            modified_var_names = []
            for var in self.map_type_from:
                memory_regions = get_memory_regions(pet, subnodes, var.name)

                # get size of memory region
                memory_region_sizes = get_sizes_of_memory_regions(
                    memory_regions, os.path.join(project_folder_path, "profiler/memory_regions.txt")
                )
                if len(memory_region_sizes) > 0:
                    max_mem_reg_size = max(memory_region_sizes.values())
                    # divide memory region size by size of variable
                    # construct new list of modified var names
                    modified_var_names.append(
                        (
                            var.name + "[:" + str(int(max_mem_reg_size / var.sizeInByte)) + "]"
                            if "**" in var.type
                            else var.name
                        )
                    )
                else:
                    modified_var_names.append(var.name + "[:]" if "**" in var.type else var.name)
            clauses.append(omp_clause_str("map(from: args)", modified_var_names))
            var_names = []

        if self.map_type_tofrom:
            modified_var_names = []
            for var in self.map_type_tofrom:
                memory_regions = get_memory_regions(pet, subnodes, var.name)

                # get size of memory region
                memory_region_sizes = get_sizes_of_memory_regions(
                    memory_regions, os.path.join(project_folder_path, "profiler/memory_regions.txt")
                )
                if len(memory_region_sizes) > 0:
                    max_mem_reg_size = max(memory_region_sizes.values())
                    # divide memory region size by size of variable
                    # construct new list of modified var names
                    modified_var_names.append(
                        (
                            var.name + "[:" + str(int(max_mem_reg_size / var.sizeInByte)) + "]"
                            if "**" in var.type
                            else var.name
                        )
                    )
                else:
                    modified_var_names.append(var.name + "[:]" if "**" in var.type else var.name)
            clauses.append(omp_clause_str("map(tofrom: args)", modified_var_names))
            var_names = []

        if self.map_type_alloc:
            modified_var_names = []
            for var in self.map_type_alloc:
                memory_regions = get_memory_regions(pet, subnodes, var.name)

                # get size of memory region
                memory_region_sizes = get_sizes_of_memory_regions(
                    memory_regions, os.path.join(project_folder_path, "profiler/memory_regions.txt")
                )
                if len(memory_region_sizes) > 0:
                    max_mem_reg_size = max(memory_region_sizes.values())
                    # divide memory region size by size of variable
                    # construct new list of modified var names
                    modified_var_names.append(
                        (
                            var.name + "[:" + str(int(max_mem_reg_size / var.sizeInByte)) + "]"
                            if "**" in var.type
                            else var.name
                        )
                    )
                else:
                    modified_var_names.append(var.name + "[:]" if "**" in var.type else var.name)
            clauses.append(omp_clause_str("map(alloc: args)", modified_var_names))
            var_names = []

        if self.reduction_vars_str:
            clauses.append(omp_clause_str("reduction(args)", self.reduction_vars_str))
            if self.has_scalar_reduction_var:
                clauses.append(omp_clause_str("defaultmap(tofrom:scalar)", []))

        tmp_start_line = LineID(str(self._node.file_id) + ":" + str(self.startLine))
        constructs.append(
            omp_construct_dict("#pragma omp target teams distribute parallel for", tmp_start_line, clauses)
        )

        # == additional constructs ==
        used_global_vars: Set[Variable] = set()
        for node_id in self.called_functions:
            fn_node: FunctionNode = cast(FunctionNode, map_node(pet, node_id))
            fn_node_start_line = LineID(str(fn_node.file_id) + ":" + str(fn_node.start_line))
            fn_node_end_line = LineID(str(fn_node.file_id) + ":" + str(fn_node.end_line + 1))
            constructs.append(omp_construct_dict("#pragma omp declare target", fn_node_start_line, []))
            constructs.append(
                omp_construct_dict(
                    "#pragma omp end declare target",
                    fn_node_end_line,
                    [],
                    positioning=OmpConstructPositioning.AFTER_LINE,
                )
            )
            # get used global variables
            cu_nodes: List[CUNode] = subtree_of_type(pet, fn_node, CUNode)
            tmp_global_vars: Set[Variable] = set()
            for cu_node in cu_nodes:
                tmp_global_vars.update(cu_node.global_vars)

            # check if global var is defined outside fn_node's body and update used_global_vars
            used_global_vars.update(
                global_var
                for global_var in tmp_global_vars
                if global_var.defLine
                if not fn_node.contains_line(global_var.defLine)
            )

        # declare all global variables used in called functions
        self.declared_global_variables.update(used_global_vars)
        for global_var in used_global_vars:
            constructs.append(
                omp_construct_dict(
                    "#pragma omp declare target  // " + str(global_var.name), LineID(global_var.defLine), []
                )
            )
            constructs.append(
                omp_construct_dict(
                    "#pragma omp end declare target  // " + str(global_var.name),
                    LineID(global_var.defLine),
                    [],
                    positioning=OmpConstructPositioning.AFTER_LINE,
                )
            )

        return constructs

    def getDataStr(self, pet: PEGraphX) -> str:
        """Generates a string which contains data that is used to rank this loop, e.g.
            the number of iterations and which variables have to be transferred etc.

        :return:
        """
        # The string begins with the type, the LID and the number of iterations.
        fileID = parse_id(self.nodeID)
        ss: str = str(fileID[0]) + ":"
        ss += str(self.startLine) + " "
        ss += "0" if not self.reduction_vars_str else "1"
        ss += " " + str(self.iteration_count) + " "

        # This is followed by three arrays, each containing variable names separated
        # by spaces, e.g. [var_1 var_2 ... var_n].
        # The first array references the variables that have to be copied to the GPU,
        # the second array references the variables that have to be copied to host
        # memory, and the variable names in the third array correspond to the
        # variables that have to be copied to the GPU and then back to host memory.
        ss += "["
        ss += fmt_vars(self.map_type_to)
        ss += "] ["
        ss += fmt_vars(self.map_type_from)
        ss += "] ["
        tmp: List[Variable] = self.map_type_tofrom

        for va in self.reduction_vars_ids:
            tmp.append(va)
        ss += fmt_vars(tmp)
        ss += "]"

        # The final part of this string contains information about the loop's nested
        # loops including their iteration numbers.
        n: LoopNode = cast(LoopNode, map_node(pet, self.nodeID))
        total_i: int = n.loop_iterations
        for cn_id in direct_children(pet, n):
            if cn_id.type == 2:  # type loop
                ss += self.__add_sub_loops_rec(pet, cn_id.id, total_i)
        return ss

    def classifyLoopVars(self, pet: PEGraphX, loop: LoopNode) -> None:
        """Classify the variables that are accessed in this loop, e.g. assign them
            to a map-type vector and find reduction variables

        :return:
        """
        reduction = []
        lst = get_left_right_subtree(pet, loop, False)
        rst = get_left_right_subtree(pet, loop, True)
        sub = subtree_of_type(pet, loop, CUNode)

        raw = set()
        war = set()
        waw = set()
        rev_raw = set()

        dummyFunctions: Set[NodeID] = set()
        self.called_functions.update(getCalledFunctions(pet, loop, self.called_functions, dummyFunctions))

        for sub_node in sub:
            raw.update(get_dep_of_type(pet, sub_node, DepType.RAW, False))
            war.update(get_dep_of_type(pet, sub_node, DepType.WAR, False))
            waw.update(get_dep_of_type(pet, sub_node, DepType.WAW, False))
            rev_raw.update(get_dep_of_type(pet, sub_node, DepType.RAW, True))

        # global vars need to be considered as well since mapping / updates may be required
        vars = get_undefined_variables_inside_loop(pet, loop, include_global_vars=True)

        _, private_vars, _, _, _ = classify_loop_variables(pet, loop)

        # define temporary classification lists
        map_type_to: List[Tuple[Variable, Set[MemoryRegion]]] = []
        map_type_tofrom: List[Tuple[Variable, Set[MemoryRegion]]] = []
        map_type_from: List[Tuple[Variable, Set[MemoryRegion]]] = []
        map_type_alloc: List[Tuple[Variable, Set[MemoryRegion]]] = []

        for var in vars:
            if var in private_vars:
                continue
            if is_scalar_val(var) and var.accessMode == "R" and False:
                # will be implicitly mapped as firstprivate
                continue
            if is_loop_index2(pet, loop, var.name):
                continue
            elif loop.reduction and is_reduction_var_by_name(pet, loop.start_position(), var.name):
                var.operation = get_reduction_sign(pet, loop.start_position(), var.name)
                reduction.append(var)
            # TODO grouping

            if (
                is_written_in_subtree(vars[var], raw, waw, lst)
                or is_func_arg(pet, var.name, loop)
                or (
                    # "manual" triggering of "map(to)" required for true global variables since initialization of global
                    # variables might not occur in dependencies since the initializations are not instrumented
                    is_global(var.name, sub)
                    and not get_parent_function(pet, loop).contains_line(var.defLine)
                )
            ):
                if is_readonly(vars[var], war, waw, rev_raw):
                    map_type_to.append((var, vars[var]))
                elif is_read_in_right_subtree(vars[var], rev_raw, sub):
                    map_type_tofrom.append((var, vars[var]))
                elif is_written_in_subtree(vars[var], raw, waw, cast(List[Node], sub)):
                    map_type_alloc.append((var, vars[var]))
                else:
                    pass

            elif is_first_written(vars[var], raw, war, sub):
                # TODO simplify
                if is_read_in_subtree(vars[var], rev_raw, rst):
                    map_type_from.append((var, vars[var]))
                else:
                    map_type_alloc.append((var, vars[var]))
            else:
                pass

        # use known variables to reconstruct the correct variable names from the classified memory regions
        left_subtree_without_called_nodes = get_left_right_subtree(pet, loop, False, ignore_called_nodes=True)
        prior_known_vars = get_variables(pet, left_subtree_without_called_nodes)
        # get memory regions which are initialized in the loop and treat them like prior known vars wrt. de-aliasing
        initilized_in_loop = get_initialized_memory_regions_in(pet, sub)
        combined_know_vars: Dict[Variable, Set[MemoryRegion]] = dict()
        for var in prior_known_vars:
            if var not in combined_know_vars:
                combined_know_vars[var] = set()
            combined_know_vars[var].update(prior_known_vars[var])
        for var in initilized_in_loop:
            if var not in combined_know_vars:
                combined_know_vars[var] = set()
            combined_know_vars[var].update(initilized_in_loop[var])

        # de-alias and store identified mapping information
        self.map_type_to = self.__apply_dealiasing(map_type_to, combined_know_vars)
        self.map_type_tofrom = self.__apply_dealiasing(map_type_tofrom, combined_know_vars)

        self.map_type_alloc = self.__apply_dealiasing(map_type_alloc, combined_know_vars)

        self.map_type_from = self.__apply_dealiasing(map_type_from, combined_know_vars)

    def __apply_dealiasing(
        self,
        input_list: List[Tuple[Variable, Set[MemoryRegion]]],
        previously_known: Dict[Variable, Set[MemoryRegion]],
    ) -> List[Variable]:
        """Apply de-aliasing such that only valid (i.e. known) variable names are returned.
        Memory Regions specified in initialized_memory_regions will be ignored respectively passed through.
        """

        tmp_memory_regions = set()
        for _, mem_regs in input_list:
            tmp_memory_regions.update(mem_regs)
        cleaned = [pkv for pkv in previously_known if len(previously_known[pkv].intersection(tmp_memory_regions))]
        return cleaned

    def setParentLoop(self, pl: str) -> None:
        """

        :param pl:
        :return:
        """
        self.parentLoop = pl

    def getNestedLoops(self, pet: PEGraphX, node_id: NodeID) -> None:
        """

        :param node_id:
        :return:
        """
        # calculate the number of iterations of this loop relative to the top loop
        n = map_node(pet, node_id)

        # extend the string stream with this information and scan all child nodes to
        # identify and process further nested loops
        for cn_id in direct_children(pet, n):
            if cn_id.type == 2:  # type loop
                self.nestedLoops.add(cn_id.id)
                self.getNestedLoops(pet, cn_id.id)

    def getNextLoop(self, pet: PEGraphX, node_id: NodeID) -> None:
        """

        :param node_id:
        :return:
        """
        n = map_node(pet, node_id)
        endLine = 0
        for children in direct_children(pet, n):
            if children.end_line > endLine:
                endLine = children.end_line

    def setCollapseClause(self, pet: PEGraphX, node_id: NodeID, res: DetectionResult) -> None:
        """

        :param node_id:
        :return:
        """
        # calculate the number of iterations of this loop relative to the top loop
        n: LoopNode = cast(LoopNode, map_node(pet, node_id))

        do_all_loops = [node.node_id for node in res.patterns.do_all]

        loop_entry_node = cast(LoopNode, pet.node_at(node_id)).get_entry_node(pet)
        if loop_entry_node is None:
            loop_entry_node = direct_children(pet, pet.node_at(node_id))[0]

        for cn_id in direct_children(pet, n):
            if cn_id.type == 2:  # check for loop node contained in the loop body
                if cn_id.end_line <= n.end_line:  # todo not true if loop bodies are terminated by braces
                    # only consider child as collapsible, if it is a do-all loop
                    if cn_id.id in do_all_loops:
                        # check for perfect nesting of both loops (i.e. no statements inbetween)
                        # todo: possible improvement: consider columns as well, or test using the AST / nesting
                        #  information from the LLVM debug information
                        # check if distance between first CU of node_id and cn_id is 2 steps on the successor graph
                        potentials: Set[Node] = set()
                        for succ1 in direct_successors(pet, loop_entry_node):
                            for succ2 in direct_successors(pet, succ1):
                                potentials.add(succ2)
                        if cast(LoopNode, cn_id).get_entry_node(pet) in potentials:
                            # perfect nesting possible. allow collapsing the loops, if root loop has no other children
                            if len(direct_children(pet, pet.node_at(node_id))) == 5:
                                # 2 children for loop condition and body
                                # 1 child is the collapsible loop
                                # 2 children for loop end and increment
                                self.collapse += 1
                                self.setCollapseClause(pet, cn_id.id, res)

    def findMappedVar(self, direction: str, var: Variable) -> bool:
        """

        :param var:
        :param direction:
        :return:
        """
        if direction == "alloc":
            for v in self.map_type_alloc:
                if v == var:
                    return True
        elif direction == "to":
            for v in self.map_type_to:
                if v == var:
                    return True
        elif direction == "from":
            for v in self.map_type_from:
                if v == var:
                    return True
        elif direction == "tofrom":
            for v in self.map_type_tofrom:
                if v == var:
                    return True
        return False

    def printGPULoop(self) -> None:
        """

        :return:
        """
        print("#pragma omp target data ")
        print(self.node_id + " = " + self.start_line + " " + self.end_line)
        # long ll = determineLineNumber(firstGPULoop.getStartLine());
        print("map_type_alloc: ")
        for k in [v.name for v in self.map_type_alloc]:
            print("    " + k)
        print("map_type_to: ")
        for k in [v.name for v in self.map_type_to]:
            print("    " + k)
        print("map_type_from: ")
        for k in [v.name for v in self.map_type_from]:
            print("    " + k)
        print("map_type_tofrom: ")
        for k in [v.name for v in self.map_type_tofrom]:
            print("    " + k)

    def __add_sub_loops_rec(self, pet: PEGraphX, node_id: NodeID, top_loop_iterations: int) -> str:
        """This function adds information about the loop's child loops to the string
            stream 'ss'. This information contains the child loop's line number and
            its number of iterations divided by the number of iterations of the top loop.
            For each loop, the string is extended with " line_number iteration_count".

        :param node_id:
        :param top_loop_iterations:
        :return:
        """
        # calculate the number of iterations of this loop relative to the top loop
        n = map_node(pet, node_id)
        ll = n.start_line
        total_i = cast(LoopNode, n).loop_iterations
        i_cnt = 0 if top_loop_iterations == 0 else total_i / top_loop_iterations

        # extend the string stream with this information and scan all child nodes to
        # identify and process further nested loops
        ss: str = " " + str(ll) + "-" + str(i_cnt)
        for cn_id in direct_children(pet, n):
            if cn_id.type == 2:
                ss += self.__add_sub_loops_rec(pet, cn_id.id, top_loop_iterations)
        return ss

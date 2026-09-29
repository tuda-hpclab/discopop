# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
from typing import List, Dict, Tuple, Optional, cast, Any

from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.traversal.children import (
    direct_children_or_called_nodes,
    direct_children_or_called_nodes_of_type,
)
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_explorer.pattern_detectors.task_parallelism.alias_detection import (
    get_alias_information as get_alias_detection_result,
)
from discopop_explorer.pattern_detectors.task_parallelism.classes import (
    TaskParallelismInfo,
    TPIType,
)
from discopop_explorer.pattern_detectors.task_parallelism.tp_utils import (
    line_contained_in_region,
    get_function_call_from_source_code,
    get_called_function_and_parameter_names_from_function_call,
    demangle,
    get_called_functions_recursively,
)


def detect_dependency_clauses_alias_based(
    pet: PEGraphX,
    suggestions: List[PatternInfo],
    file_mapping_path: str,
    cu_xml: str,
    dep_file: str,
    cu_inst_result_file: str,
    discopop_build_path: str,
) -> List[PatternInfo]:
    """Wrapper for alias based dependency detection.
    :param pet: PET Graph
    :param suggestions: List[PatternInfo]
    :param file_mapping_path: path to FileMapping file
    :param cu_xml: path to cu_xml file
    :param dep_file: path to dependency file
    :param cu_inst_result_file: path to CUInstResult.txt
    :param discopop_build_path: path to discopop build directory
    :return: List[PatternInfo]
    """
    # Read contents of file_mapping
    source_code_files = dict()
    with open(file_mapping_path) as f:
        for line in f.readlines():
            line = line.replace("\n", "")
            line_split = line.split("\t")
            source_code_files[line_split[0]] = line_split[1]
    # get RAW depencency information as a dict
    raw_dependency_information = get_raw_dependency_information_from_dep_file(dep_file)
    # parse cu_inst_result_file contents into dict
    cu_inst_result_dict = get_dict_from_cu_inst_result_file(cu_inst_result_file)
    aliases = get_alias_information(pet, suggestions, source_code_files)
    # get function-internal parameter aliases
    function_parameter_alias_dict = get_function_internal_parameter_aliases(
        file_mapping_path, cu_xml, discopop_build_path
    )
    # find dependencies between calls of different functions inside function scopes
    suggestions = identify_dependencies_for_different_functions(
        pet, suggestions, aliases, source_code_files, raw_dependency_information
    )
    # find dependencies between calls of same function inside function scopes
    suggestions = identify_dependencies_for_same_functions(
        pet, suggestions, source_code_files, cu_inst_result_dict, function_parameter_alias_dict
    )
    return suggestions


def get_raw_dependency_information_from_dep_file(dep_file: str) -> Dict[str, List[Tuple[str, str]]]:
    """return RAW dependency information contained in dep_file in the form of a dictionary.
    Format: {source_line: [(sink_line, var_name)]
    :param dep_file: path to dependency file
    :return: RAW dictionary
    """
    raw_dependencies: Dict[str, List[Tuple[str, str]]] = dict()
    with open(dep_file) as f:
        for line in f.readlines():
            line = line.replace("\n", "")
            # format of dependency entries in _dep.txt-file:
            #   sourceLine NOM RAW sinkLine|variable
            if " NOM " not in line:
                continue
            split_line = line.split(" NOM ")
            source_line = split_line[0]
            # split entries
            entries = []
            current_entry = ""
            for word in split_line[1].split(" "):
                word = word.replace(" ", "")
                if word == "RAW" or word == "WAR" or word == "WAW" or word == "INIT":
                    if len(current_entry) > 0:
                        entries.append(current_entry)
                    current_entry = ""
                if len(current_entry) > 0:
                    current_entry += " " + word
                else:
                    current_entry += word
            if len(current_entry) > 0:
                entries.append(current_entry)
            if source_line not in raw_dependencies:
                raw_dependencies[source_line] = []
            for entry in entries:
                # filter for RAW dependencies
                split_entry = entry.split(" ")
                if split_entry[0] != "RAW":
                    continue
                split_sink_line_var = split_entry[1].split("|")
                sink_line = split_sink_line_var[0]
                var_name = split_sink_line_var[1].replace(".addr", "")
                raw_dependencies[source_line].append((sink_line, var_name))
    return raw_dependencies


def get_dict_from_cu_inst_result_file(
    cu_inst_result_file: str,
) -> Dict[str, List[Dict[str, Optional[str]]]]:
    """Parses the information contained in cu_inst_result_file into a dictionary of dictionaries,
    ordered by dependency type and returns the dictionary.
    :param cu_inst_result_file: Path (string) to cu_inst_result file
    :return: parsed dictionary"""
    res_dict: Dict[str, List[Dict[str, Optional[str]]]] = {"RAW": [], "WAR": [], "WAW": []}
    try:
        with open(cu_inst_result_file) as f:
            for line in f:
                line = line.replace("\n", "")
                line_split = line.split(" ")
                dep_type = line_split[0]
                target_type = line_split[2]
                if target_type == "line:":
                    target_function = None
                    target_line = line_split[3]
                    target_var = line_split[5]
                elif target_type == "function:":
                    target_function = line_split[3]
                    target_line = line_split[5]
                    target_var = line_split[7]
                else:
                    raise ValueError("Unknown type: ", target_type)
                cur_line_dict = {
                    "function": target_function,
                    "line": target_line.replace(",", ""),
                    "var": target_var,
                }
                res_dict[dep_type].append(cur_line_dict)
    except FileNotFoundError as ex:
        raise ex
    return res_dict


def get_alias_information(
    pet: PEGraphX, suggestions: List[PatternInfo], source_code_files: Dict[str, str]
) -> Dict[TaskParallelismInfo, List[List[Tuple[str, str, LineID, LineID]]]]:
    """Generate and return alias information dictionary.
    :param pet: PET Graph
    :param suggestions: List[PatternInfo]
    :param source_code_files: File-Mapping dictionary
    :return: alias information dictionary
    """
    # iterate over task suggestions
    task_suggestions = [s for s in [e for e in suggestions if type(e) == TaskParallelismInfo] if s.type is TPIType.TASK]
    # collect alias information
    aliases: Dict[TaskParallelismInfo, List[List[Tuple[str, str, LineID, LineID]]]] = dict()
    called_function_cache: Dict[Any, Any] = dict()
    for ts in task_suggestions:
        current_alias_entry = []
        potential_parent_functions = __get_potential_parent_functions(pet, ts)
        # get parent function
        for parent_function in potential_parent_functions:
            # get recursive function call from original source code
            try:
                function_call_string = get_function_call_from_source_code(
                    source_code_files, int(ts.pragma_line), ts.node_id.split(":")[0]
                )
            except IndexError:
                continue
            # get function parameter names from recursive function call
            (
                function_name,
                parameter_names,
            ) = get_called_function_and_parameter_names_from_function_call(
                function_call_string, ts._node.recursive_function_calls[0], cast(CUNode, ts._node)
            )
            # get CU Node object of called function
            called_function_cu_id: Optional[NodeID] = None
            for recursive_function_call_entry in ts._node.recursive_function_calls:
                if recursive_function_call_entry is None:
                    continue
                if "," in recursive_function_call_entry:
                    recursive_function_call_entry = recursive_function_call_entry.split(",")[0]
                recursive_function_call_entry_split = recursive_function_call_entry.split(" ")
                recursive_function_call_line = recursive_function_call_entry_split[1]
                if int(recursive_function_call_line.split(":")[1]) == int(ts.pragma_line):
                    # correct function call found
                    # find corresponding function CU
                    for tmp_func_cu in all_nodes(pet, FunctionNode):
                        if tmp_func_cu.name == recursive_function_call_entry_split[0]:
                            called_function_cu_id = tmp_func_cu.id
            # get aliases for parameters
            for idx, param in enumerate(parameter_names):
                if param is None:
                    continue
                if called_function_cu_id is None:
                    continue
                current_alias = [
                    (
                        param,
                        parent_function.name,
                        parent_function.start_position(),
                        parent_function.end_position(),
                    )
                ]
                current_alias += get_alias_for_parameter_at_position(
                    pet,
                    cast(FunctionNode, pet.node_at(called_function_cu_id)),
                    idx,
                    source_code_files,
                    [],
                    called_function_cache,
                )
                current_alias_entry.append(current_alias)
        aliases[ts] = current_alias_entry
    # join aliases on first element (original identifier)
    for key in aliases:
        joined_aliases = []
        while aliases[key]:
            join_on = aliases[key].pop()
            join_indices = []
            for idx, alias_entry in enumerate(aliases[key]):
                if alias_entry[0] == join_on[0]:
                    join_indices.append(idx)
            # sort reversed to prevent errors due to popping elements
            join_indices.sort(reverse=True)
            for idx in join_indices:
                to_be_joined = aliases[key].pop(idx)
                to_be_joined.pop(0)
                join_on += to_be_joined
            joined_aliases.append(join_on)
        aliases[key] = joined_aliases
    return aliases


def get_function_internal_parameter_aliases(
    file_mapping_path: str, cu_xml_path: str, discopop_build_path: str
) -> Dict[str, List[Tuple[str, str]]]:
    """Wrapper to execute simple alias analysis and parse results into dict (function name to list of alias-tuples).
    :param file_mapping_path: path to filemapping file
    :param cu_xml_path: path to cu_xml file
    :param discopop_build_path: path to discopop build directory
    :result: function-internal alias detection results in dict form"""
    # execute simple alias detection
    alias_detection_temp_file = os.getcwd() + "/alias_detection_temp.txt"
    # get absolute file paths
    file_mapping_path = os.path.abspath(file_mapping_path)
    cu_xml_path = os.path.abspath(cu_xml_path)

    # execute simple alias detection
    alias_detection_result = get_alias_detection_result(
        file_mapping_path, cu_xml_path, alias_detection_temp_file, discopop_build_path
    )

    # check if alias_detection_result has contents
    if len(alias_detection_result) == 0:
        return dict()
    # create dict:
    alias_dict: Dict[str, List[Tuple[str, str]]] = dict()
    for line in alias_detection_result.split("\n"):
        line = line.replace("\n", "")
        if ";" not in line:
            continue
        line_split = line.split(";")
        fname = line_split[1]
        var_name = line_split[2]
        alias_name = line_split[3]
        if var_name == alias_name:
            continue
        if fname not in alias_dict:
            alias_dict[fname] = []
        alias_dict[fname].append((var_name, alias_name))
    return alias_dict


def identify_dependencies_for_different_functions(
    pet: PEGraphX,
    suggestions: List[PatternInfo],
    aliases: Dict[TaskParallelismInfo, List[List[Tuple[str, str, LineID, LineID]]]],
    source_code_files: Dict[str, str],
    raw_dependency_information: Dict[str, List[Tuple[str, str]]],
) -> List[PatternInfo]:
    """Identify dependency clauses for all combinations of suggested tasks concerning different called functions
     and supplement the suggestions.
    :param pet: PET Graph
    :param suggestions: List[PatternInfo]
    :param aliases: alias information dict
    :param source_code_files: File-Mapping dictionary
    :param raw_dependency_information: RAW information dict
    :return: List[PatternInfo]
    """
    # wrapper to start __check_dependence_of_task_pair for all viable combinations of suggested tasks
    result_suggestions: List[PatternInfo] = []
    task_suggestions: List[TaskParallelismInfo] = []
    for s in suggestions:
        if type(s) == TaskParallelismInfo:
            if s.type is TPIType.TASK:
                task_suggestions.append(s)
            else:
                result_suggestions.append(s)
        else:
            result_suggestions.append(s)
    # iterate over all combinations of tasks, ts_1 has to come before ts_2
    # get in and out dependencies to insert
    out_dep_updates: Dict[TaskParallelismInfo, List[str]] = dict()
    in_dep_updates: Dict[TaskParallelismInfo, List[str]] = dict()
    for ts_1 in task_suggestions:
        # get parent function
        potential_parent_functions_1 = __get_potential_parent_functions(pet, ts_1)
        while potential_parent_functions_1:
            potential_parent_functions_1.pop()
            # get recursive function call from original source code
            try:
                function_call_string_1 = get_function_call_from_source_code(
                    source_code_files, int(ts_1.pragma_line), ts_1.node_id.split(":")[0]
                )
            except IndexError:
                continue
            # get function parameter names from recursive function call
            (
                function_name_1,
                parameter_names_1,
            ) = get_called_function_and_parameter_names_from_function_call(
                function_call_string_1,
                ts_1._node.recursive_function_calls[0],
                cast(CUNode, ts_1._node),
            )
            for ts_2 in [s for s in task_suggestions if not s == ts_1]:
                # get parent function
                potential_parent_functions_2 = __get_potential_parent_functions(pet, ts_2)
                while potential_parent_functions_2:
                    potential_parent_functions_2.pop()
                    # get recursive function call from original source code
                    try:
                        function_call_string_2 = get_function_call_from_source_code(
                            source_code_files, int(ts_2.pragma_line), ts_2.node_id.split(":")[0]
                        )
                        (
                            function_name_2,
                            parameter_names_2,
                        ) = get_called_function_and_parameter_names_from_function_call(
                            function_call_string_2,
                            ts_2._node.recursive_function_calls[0],
                            cast(CUNode, ts_2._node),
                        )
                        # exclude pairs of same function from dependency detection
                        if function_name_1 == function_name_2:
                            continue
                    except IndexError:
                        continue
                    # get function parameter names from recursive function call
                    dependencies = check_dependence_of_task_pair(
                        aliases, raw_dependency_information, ts_1, parameter_names_1, ts_2
                    )

                    # check if task suggestion_1 occurs prior to task_suggestion_2
                    if ts_1._node.start_position().split(":")[0] == ts_2._node.start_position().split(":")[0]:
                        # same file id
                        ts_1_pragma_line = (
                            int(ts_1.pragma_line)
                            if ":" not in ts_1.pragma_line
                            else int(ts_1.pragma_line.split(":")[1])
                        )
                        ts_2_pragma_line = (
                            int(ts_2.pragma_line)
                            if ":" not in ts_2.pragma_line
                            else int(ts_2.pragma_line.split(":")[1])
                        )
                        # check line numbers
                        if ts_2_pragma_line < ts_1_pragma_line:
                            continue

                    for dependence_var in dependencies:
                        # Mark the variable as depend out for the first function and depend in for the second function.
                        if ts_1 not in out_dep_updates:
                            out_dep_updates[ts_1] = []
                        out_dep_updates[ts_1].append(dependence_var)
                        if ts_2 not in in_dep_updates:
                            in_dep_updates[ts_2] = []
                        in_dep_updates[ts_2].append(dependence_var)
    # perform updates of in and out dependencies
    for ts in task_suggestions:
        if ts in out_dep_updates:
            for out_dep_var in out_dep_updates[ts]:
                ts.out_dep.append(out_dep_var)
            ts.out_dep = list(dict.fromkeys(ts.out_dep))
        if ts in in_dep_updates:
            for in_dep_var in in_dep_updates[ts]:
                ts.in_dep.append(in_dep_var)
            ts.in_dep = list(dict.fromkeys(ts.in_dep))
        result_suggestions.append(ts)

    return result_suggestions


def __get_potential_parent_functions(pet: PEGraphX, sug: TaskParallelismInfo) -> List[Node]:
    """Helper function for identify_dependencies_for_same_functions.
    Creates a list of potential parents (Function CU Nodes) for a given suggestion.
    :param pet: PET Graph
    :param sug: target suggestion
    :return: List of potential parents of sug (Function CU Nodes)"""
    potential_parent_functions = [
        pet.node_at(e[0])
        for e in in_edges(pet, sug._node.id, EdgeType.CHILD)
        if isinstance(pet.node_at(e[0]), FunctionNode)
    ]
    if not potential_parent_functions:
        # perform BFS search on incoming CHILD edges to find closest parent function,
        # i.e. function which contains the CU.
        queue = [pet.node_at(e[0]) for e in in_edges(pet, sug._node.id, EdgeType.CHILD)]
        found_parent = None
        while len(queue) > 0 or not found_parent:
            current = queue.pop(0)
            if isinstance(current, FunctionNode):
                found_parent = current
                break
            queue += [pet.node_at(e[0]) for e in in_edges(pet, current.id, EdgeType.CHILD)]
        potential_parent_functions = [found_parent]
    return potential_parent_functions


def __get_potential_children_of_function(pet: PEGraphX, parent_function: Node) -> List[Node]:
    """Helper function for identify_dependencies_for_same_functions.
    Creates a list of CUNodes corresponding to the body of the given function.
    :param pet: PET Graph
    :param parent_function: function to be analyzed
    :return: List of CUNodes contained in functions body."""
    queue = direct_children_or_called_nodes(pet, parent_function)
    potential_children = []
    visited = []
    while queue:
        cur_potential_child = queue.pop()
        visited.append(cur_potential_child)
        # test if cur_potential_child is inside cur_potential_parent_functions scope
        if line_contained_in_region(
            cur_potential_child.start_position(),
            parent_function.start_position(),
            parent_function.end_position(),
        ) and line_contained_in_region(
            cur_potential_child.end_position(),
            parent_function.start_position(),
            parent_function.end_position(),
        ):
            potential_children.append(cur_potential_child)
        for tmp_child in direct_children_or_called_nodes(pet, cur_potential_child):
            if tmp_child not in queue and tmp_child not in potential_children and tmp_child not in visited:
                queue.append(tmp_child)
    return potential_children


def __get_recursive_calls_from_function(potential_children: List[Node], parent_function: Node) -> List[str]:
    """Helper function for identify_dependencies_for_same_functions.
    Creates a list of recursive function calls located inside the body of the given function.
    :param potential_children: List of CUs contained in function's body
    :param parent_function: Parent function
    :return: List of recursive function call contained in parent_function's body
    """
    recursive_function_calls = []
    for child in [
        c
        for c in potential_children
        if line_contained_in_region(
            c.start_position(), parent_function.start_position(), parent_function.end_position()
        )
        and line_contained_in_region(c.end_position(), parent_function.start_position(), parent_function.end_position())
    ]:
        for e in child.recursive_function_calls:
            if e is not None:
                recursive_function_calls.append(e)
    recursive_function_calls = list(dict.fromkeys(recursive_function_calls))
    return recursive_function_calls


def identify_dependencies_for_same_functions(
    pet: PEGraphX,
    suggestions: List[PatternInfo],
    source_code_files: Dict[str, str],
    cu_inst_result_dict: Dict[str, List[Dict[str, Optional[str]]]],
    function_parameter_alias_dict: Dict[str, List[Tuple[str, str]]],
) -> List[PatternInfo]:
    """Identify dependency clauses for all combinations of suggested tasks concerning equal called functions
    and supplement the suggestions.
    :param pet: PET Graph
    :param suggestions: List[PatternInfo]
    :param source_code_files: File-Mapping dictionary
    :param cu_inst_result_dict: CUInstResult.txt information dict
    :param function_parameter_alias_dict: results of function-internal alias detection in dict form
    :return: List[PatternInfo]"""
    # Idea:
    # 1. iterate over task suggestions
    # 2. get parent function (pf) and called function (cf)
    # 3. get R/W information for cf's parameters based on CUInstResult.txt
    # 4. iterate over successive calls to cf, named scf
    # 5. get R/W information for scf's parameters based on CUInstResult.txt
    # 6. check cf's R/W information against scf's R/W information and identify dependencies
    # 6.1 Intersect cf's parameters with scf's parameters
    # 6.2 get task suggestion corresponding to scf
    # 6.3 If intersecting parameter of cf is RAW, add dependency (scf:in, cf:out)

    result_suggestions: List[PatternInfo] = []
    task_suggestions: List[TaskParallelismInfo] = []
    for s in suggestions:
        if type(s) == TaskParallelismInfo:
            if s.type is TPIType.TASK:
                task_suggestions.append(s)
            else:
                result_suggestions.append(s)
        else:
            result_suggestions.append(s)

    out_dep_updates: Dict[TaskParallelismInfo, List[Tuple[str, bool]]] = dict()
    in_dep_updates: Dict[TaskParallelismInfo, List[Tuple[str, bool]]] = dict()
    function_raw_information_cache: Dict[str, List[Tuple[bool, bool]]] = dict()
    # 1. iterate over task suggestions
    for ts_1 in task_suggestions:
        # 2. get parent function (pf) and called function (cf)
        # get parent function
        potential_parent_functions_1 = __get_potential_parent_functions(pet, ts_1)
        while potential_parent_functions_1:
            cur_potential_parent_function = potential_parent_functions_1.pop()
            # get recursive function call from original source code
            try:
                get_function_call_from_source_code(source_code_files, int(ts_1.pragma_line), ts_1.node_id.split(":")[0])
            except IndexError:
                continue
            # get potential children by dfs enumerating children nodes inside cur_potential_parent_functions scope
            potential_children = __get_potential_children_of_function(pet, cur_potential_parent_function)

            cppf_recursive_function_calls = __get_recursive_calls_from_function(
                potential_children, cur_potential_parent_function
            )
            outer_breaker = False
            for rfce_idx_1, recursive_function_call_entry_1 in enumerate(cppf_recursive_function_calls):
                if outer_breaker:
                    break
                # 3. get R/W information for cf's parameters based on CUInstResult.txt
                called_function_name_1, call_line_1 = recursive_function_call_entry_1.split(",")[0].split(" ")
                lower_line_id_1 = ts_1.pragma_line
                if ":" in lower_line_id_1:
                    lower_line_num_str_1 = lower_line_id_1.split(":")[1]
                lower_line_num_1 = int(lower_line_num_str_1)
                ret_val_1 = get_function_call_parameter_rw_information(
                    pet,
                    call_line_1,
                    ts_1._node,
                    lower_line_num_1,
                    True,
                    False,
                    cu_inst_result_dict,
                    source_code_files,
                    [],
                    function_raw_information_cache,
                    function_parameter_alias_dict,
                    called_function_name=called_function_name_1,
                )
                if ret_val_1 is None:
                    continue
                (
                    recursive_function_call_line_1,
                    parameter_names_1_raw_information,
                    recursively_visited_1,
                    function_raw_information_cache,
                ) = ret_val_1
                # 4. iterate over successive calls to cf, named scf
                for rfce_idx_2, recursive_function_call_entry_2 in enumerate(cppf_recursive_function_calls):
                    if rfce_idx_2 == rfce_idx_1:
                        continue
                    if recursive_function_call_entry_2 is None:
                        continue
                    # 5. get R/W Information for scf
                    called_function_name_2, call_line_2 = recursive_function_call_entry_2.split(",")[0].split(" ")
                    lower_line_id_2 = ts_1.pragma_line
                    if ":" in lower_line_id_2:
                        lower_line_num_str_2 = lower_line_id_2.split(":")[1]
                    lower_line_num_2 = int(lower_line_num_str_2)
                    ret_val_2 = get_function_call_parameter_rw_information(
                        pet,
                        call_line_2,
                        ts_1._node,
                        lower_line_num_2,
                        False,
                        True,
                        cu_inst_result_dict,
                        source_code_files,
                        [],
                        function_raw_information_cache,
                        function_parameter_alias_dict,
                        called_function_name=called_function_name_2,
                    )
                    if ret_val_2 is None:
                        continue
                    (
                        recursive_function_call_line_2,
                        parameter_names_2_raw_information,
                        recursively_visited_2,
                        function_raw_information_cache,
                    ) = ret_val_2

                    # 6. check cf's R/W information against scf's R/W information and identify dependencies
                    # 6.1 Intersect cf's parameters with scf's parameters
                    intersection = []
                    for param_entry_1 in parameter_names_1_raw_information:
                        if param_entry_1[0] is None:
                            continue
                        for param_entry_2 in parameter_names_2_raw_information:
                            if param_entry_1[0] == param_entry_2[0]:
                                # filter out potential numbers as variable names
                                try:
                                    int(param_entry_1[0])
                                except ValueError:
                                    intersection.append(param_entry_1)
                    intersection = list(dict.fromkeys(intersection))
                    # 6.2 get task suggestion corresponding to scf
                    for ts_2 in task_suggestions:
                        if ts_2 == ts_1:
                            continue
                        if ts_2.pragma_line != recursive_function_call_line_2.split(":")[1]:
                            continue

                        # 6.3 If intersecting parameter of cf is RAW, add dependency (scf:in, cf:out)
                        for intersection_var, is_pessimistic in [(e[0], e[2]) for e in intersection if e[1]]:
                            if ts_1 not in out_dep_updates:
                                out_dep_updates[ts_1] = []
                            out_dep_updates[ts_1].append((intersection_var, is_pessimistic))
                            if ts_2 not in in_dep_updates:
                                in_dep_updates[ts_2] = []
                            in_dep_updates[ts_2].append((intersection_var, is_pessimistic))
                    outer_breaker = True
    # perform updates of in and out dependencies
    return __perform_dependency_updates(task_suggestions, in_dep_updates, out_dep_updates, result_suggestions)


def __perform_dependency_updates(
    task_suggestions: List[TaskParallelismInfo],
    in_dep_updates: Dict[TaskParallelismInfo, List[Tuple[str, bool]]],
    out_dep_updates: Dict[TaskParallelismInfo, List[Tuple[str, bool]]],
    result_suggestions: List[PatternInfo],
) -> List[PatternInfo]:
    """Helper function for identify_dependencies_for_same_functions.
    Applies the identified updates to the in and out dependency lists of each task suggestion.
    Returns the list of modified suggestions.
    :param task_suggestions: list of task suggestions
    :param in_dep_updates: updates to be done to in-dependencies
    :param out_dep_updates: updates to be done to out-dependencies
    :param result_suggestions: resulting suggestions as created by identify_dependencies_for_same_functions
        prior to calling this function
    :return: modified result_suggestions list"""
    for ts in task_suggestions:
        if ts in out_dep_updates:
            for out_dep_var, is_pessimistic in out_dep_updates[ts]:
                if out_dep_var not in ts.out_dep and is_pessimistic:
                    print(
                        "TPDet: Warning: Pessimistic Dependency:: CUid:",
                        ts.node_id,
                        " Type: OUT  VarName:",
                        out_dep_var,
                    )
                ts.out_dep.append(out_dep_var)
            ts.out_dep = list(dict.fromkeys(ts.out_dep))
        if ts in in_dep_updates:
            for in_dep_var, is_pessimistic in in_dep_updates[ts]:
                if in_dep_var not in ts.in_dep and is_pessimistic:
                    print(
                        "TPDet: Warning: Pessimistic Dependency:: CUid:",
                        ts.node_id,
                        " Type: IN  VarName:",
                        in_dep_var,
                    )
                ts.in_dep.append(in_dep_var)
            ts.in_dep = list(dict.fromkeys(ts.in_dep))
        result_suggestions.append(ts)
    return result_suggestions


def get_alias_for_parameter_at_position(
    pet: PEGraphX,
    function: FunctionNode,
    parameter_position: int,
    source_code_files: Dict[str, str],
    visited: List[Tuple[Node, int]],
    called_function_cache: Dict[Any, Any],
) -> List[Tuple[VarName, str, LineID, LineID]]:
    """Returns alias information for a parameter at a specific position.
    :param pet: PET Graph
    :param function: CUNode of called function
    :param parameter_position: position of the parameter to be analyzed
    :param source_code_files: File-Mapping dictionary
    :param visited: List of already traversed function-index-combinations
    :param called_function_cache: cache for results of tp_utils.get_called_functions_recursively()
    :return: alias information for the specified parameter
    """
    visited.append((function, parameter_position))
    parameter_name = function.args[parameter_position].name
    # append Alias information for parameter to result
    result = [(parameter_name, function.name, function.start_position(), function.end_position())]

    # find function calls which use the parameter
    # iterate over CUs
    for cu in [pet.node_at(cuid) for cuid in [e[1] for e in out_edges(pet, function.id)]]:
        # iterate over children of CU and retrieve called functions
        called_functions = get_called_functions_recursively(pet, cu, [], called_function_cache)
        called_functions = list(dict.fromkeys(called_functions))
        # iterate over called functions
        for called_function in called_functions:
            # read line from source code (iterate over lines of CU to search for function call)
            for line in range(cu.start_line, cu.end_line + 1):
                try:
                    source_code_line = get_function_call_from_source_code(source_code_files, line, cu.id.split(":")[0])
                except IndexError:
                    continue
                # get parameter names from call

                (
                    function_name,
                    call_parameters,
                ) = get_called_function_and_parameter_names_from_function_call(
                    source_code_line, called_function.name, cast(CUNode, cu)
                )
                # check if parameter_name is contained
                for idx, pn in enumerate(call_parameters):
                    if pn == parameter_name:
                        # check if same configuration for alias detection has been used:
                        if (called_function, idx) not in visited:
                            # if not, start recursion
                            result += get_alias_for_parameter_at_position(
                                pet,
                                cast(FunctionNode, called_function),
                                idx,
                                source_code_files,
                                visited,
                                called_function_cache,
                            )
    return result


def check_dependence_of_task_pair(
    aliases: Dict[TaskParallelismInfo, List[List[Tuple[str, str, LineID, LineID]]]],
    raw_dependency_information: Dict[str, List[Tuple[str, str]]],
    task_suggestion_1: TaskParallelismInfo,
    param_names_1: List[Optional[str]],
    task_suggestion_2: TaskParallelismInfo,
) -> List[str]:
    """Check if function calls specified by task_suggestion_1 and _2 are dependent and
    return a list of found dependencies. An empty list is returned if task_suggestion_2 occurs before task_suggestion_1.
    :param aliases: alias information dict
    :param raw_dependency_information: RAW information dict
    :param task_suggestion_1: first suggestion for the check
    :param param_names_1: List of parameter names used in the function call specified by task_suggestion_1
    :param task_suggestion_2: second suggestion for the check
    :return: List of found dependencies
    """
    dependencies = []
    # iterate over parameters of task_1
    for parameter in param_names_1:
        if parameter is None:
            continue
        # get aliases for parameter
        for alias_entry in aliases[task_suggestion_1]:
            # skip wrong alias entries
            if not alias_entry[0][0] == parameter:
                continue
            # intersect alias_entry of task_suggestion_1 with entries of task_suggestion_2
            alias_entries_2 = []
            for alias_entry_2 in aliases[task_suggestion_2]:
                alias_entries_2 += alias_entry_2
            intersection = list(dict.fromkeys([ae for ae in alias_entry if ae in alias_entries_2]))
            # get sink lines
            # (start and end line of task_sug_1's parent func)
            sink_lines_start = alias_entry[0][2].split(":")
            sink_lines_end = alias_entry[0][3].split(":")
            sink_lines = []
            for ln in range(int(sink_lines_start[1]), int(sink_lines_end[1]) + 1):
                sink_lines.append("" + sink_lines_start[0] + ":" + str(ln))
            # check if there is a RAW on the variable within sink lines and source lines.
            for intersection_entry in intersection:
                # get intersection variable and source lines
                intersecting_variable = intersection_entry[0]
                source_lines_start = intersection_entry[2].split(":")
                source_lines_end = intersection_entry[3].split(":")
                source_lines = []
                for ln in range(int(source_lines_start[1]), int(source_lines_end[1]) + 1):
                    source_lines.append("" + source_lines_start[0] + ":" + str(ln))
                # check if there is a RAW on the variable within sink lines and source lines.
                if source_lines == sink_lines:
                    continue
                for source_line in source_lines:
                    if source_line not in raw_dependency_information:
                        continue
                    for raw_dep_entry in raw_dependency_information[source_line]:
                        if raw_dep_entry[1] == intersecting_variable:
                            if raw_dep_entry[0] in sink_lines:
                                dependencies.append(parameter)
    dependencies = list(dict.fromkeys(dependencies))
    # check if task suggestion_1 occurs prior to task_suggestion_2
    if task_suggestion_1._node.start_position().split(":")[0] == task_suggestion_2._node.start_position().split(":")[0]:
        # same file id
        ts_1_pragma_line = (
            int(task_suggestion_1.pragma_line)
            if ":" not in task_suggestion_1.pragma_line
            else int(task_suggestion_1.pragma_line.split(":")[1])
        )
        ts_2_pragma_line = (
            int(task_suggestion_2.pragma_line)
            if ":" not in task_suggestion_2.pragma_line
            else int(task_suggestion_2.pragma_line.split(":")[1])
        )
        # check line numbers
        if ts_2_pragma_line < ts_1_pragma_line:
            return []
    return dependencies


def get_function_call_parameter_rw_information(
    pet: PEGraphX,
    call_position: str,
    parent_cu_node: Node,
    lower_line_num: int,
    equal_lower_line_num: bool,
    greater_lower_line_num: bool,
    cu_inst_result_dict: Dict[str, List[Dict[str, Optional[str]]]],
    source_code_files: Dict[str, str],
    recursively_visited: List[Node],
    function_raw_information_cache: Dict[str, List[Tuple[bool, bool]]],
    function_parameter_alias_dict: Dict[str, List[Tuple[str, str]]],
    called_cu_id: Optional[str] = None,
    called_function_name: Optional[str] = None,
) -> Optional[Tuple[str, List[Tuple[str, bool, bool]], List[Node], Dict[str, List[Tuple[bool, bool]]]]]:
    """Retrieves the call_position and information whether the parameters of the target function are modified
    within the respective function, based on the contents of cu_inst_result_dict.
    Either called_cu_id, called_function_name or both need to be set.
    :param pet: PET Graph
    :param call_position: position of function call in source code (e.g. 14:275)
    :param parent_cu_node: CUNode corresponding to the CU Node containing the target function
    :param lower_line_num: called_function_cu_id detections is restricted to
        source code lines >= / > / == lower_line_num to ignore prior function calls.
        Different behavior is achieved by combining equal_lower_line and greater_lower_line
    :param equal_lower_line_num: allow called_function_cu_id detection for lines == lower_line_num
    :param greater_lower_line_num: allow called_function_cu_id detection for lines >= lower_line_num
    :param cu_inst_result_dict: Contents of the CUInst_Result.txt, converted into a dict.
    :param source_code_files: File Mapping dictionary
    :param recursively_visited: List of already visited CU Nodes to prevent endless recursions
    :param function_raw_information_cache: Cache containing a mapping of function names to a list of booleans,
        representing the parameters of a given function and the information
        whether a specific parameter is modified by the respective function.
    :param function_parameter_alias_dict: results of function-internal alias detection in dict form
    :param called_cu_id: ID of the called function´s CU node
    :param called_function_name: Name of the called function
    :return: None, if anything unpredicted happens.
             Otherwise, (call_position, parameter_names_raw_information,
             recursively_visited, function_raw_information_cache),
             with parameter_names_raw_infotation being a list of Tuples containing the parameter names of the
             called function and the information wheter the respective parameter is modified by the function.
    """
    ###############
    # 5. get R/W information for called function´s (cf) parameters based on CUInstResult.txt
    # 5.1.get CU object corresponding to cf
    # 5.2. get R/W information for cf's parameters based on CUInstResult.txt
    # 5.3 get function call corresponding to scf from source code
    # 5.4 start recursion step
    # 5.5 match variable names with gathered R/W information
    ################

    if called_cu_id is None and called_function_name is None:
        raise ValueError("Unsufficient information!")
    # 5. get R/W information for scf's parameters based on CUInstResult.txt
    # 5.1. get CU object corresponding to called function
    called_function_cu_id: Optional[NodeID] = None
    if called_cu_id is not None:
        called_function_cu_id = cast(NodeID, called_cu_id)
        if called_function_name is None:
            called_function_name = pet.node_at(called_function_cu_id).name
    else:
        # get cu id of called function
        if equal_lower_line_num and not greater_lower_line_num:
            if int(call_position.split(":")[1]) == lower_line_num:
                # correct function call found
                # find corresponding function CU
                for tmp_func_cu in all_nodes(pet, FunctionNode):
                    if tmp_func_cu.name == called_function_name:
                        called_function_cu_id = tmp_func_cu.id
        elif not equal_lower_line_num and greater_lower_line_num:
            if int(call_position.split(":")[1]) > lower_line_num:
                # correct function call found
                # find corresponding function CU
                for tmp_func_cu in all_nodes(pet, FunctionNode):
                    if tmp_func_cu.name == called_function_name:
                        called_function_cu_id = tmp_func_cu.id
        else:
            if int(call_position.split(":")[1]) >= lower_line_num:
                # correct function call found
                # find corresponding function CU
                for tmp_func_cu in all_nodes(pet, FunctionNode):
                    if tmp_func_cu.name == called_function_name:
                        called_function_cu_id = tmp_func_cu.id
        if called_function_cu_id is None:
            return None
    if called_function_name is None:
        raise ValueError("No valid called function could be found!")
    # 5.2. get R/W information for successive called function's parameters based on CUInstResult.txt
    called_function_cu = cast(FunctionNode, pet.node_at(called_function_cu_id))
    # get raw info concerning the scope of called_function_cu
    raw_info = cu_inst_result_dict["RAW"]
    filtered_raw_info = [
        e
        for e in raw_info
        if line_contained_in_region(
            cast(str, e["line"]),
            called_function_cu.start_position(),
            called_function_cu.end_position(),
        )
    ]
    # iterate over args positions and check if RAW is reported
    raw_reported_for_param_positions: List[Tuple[bool, bool]] = []
    for arg_var in called_function_cu.args:
        raw_reported = False
        for raw_entry in filtered_raw_info:
            if raw_entry["var"] is None:
                continue
            raw_entry_var = raw_entry["var"]
            if raw_entry_var.replace(".addr", "") == arg_var.name.replace(".addr", ""):
                raw_reported = True
        raw_reported_for_param_positions.append((raw_reported, False))
    # store results in cache
    if called_function_cu.name not in function_raw_information_cache:
        function_raw_information_cache[called_function_cu.name] = raw_reported_for_param_positions
    else:
        # perform update
        new_cache_line = []
        for idx in range(0, len(function_raw_information_cache[called_function_cu.name])):
            old_cache_line = function_raw_information_cache[called_function_cu.name]
            new_cache_line.append(old_cache_line[idx] or raw_reported_for_param_positions[idx])
        function_raw_information_cache[called_function_cu.name] = new_cache_line

    # 5.3 get function call corresponding to scf from source code
    try:
        function_call_string = get_function_call_from_source_code(
            source_code_files,
            int(call_position.split(":")[1]),
            call_position.split(":")[0],
            called_function_name=demangle(called_function_name).split("(")[0],
        )
    except IndexError:
        return None
    # get function parameter names from recursive function call
    function_name, parameter_names = get_called_function_and_parameter_names_from_function_call(
        function_call_string, called_function_name, cast(CUNode, parent_cu_node)
    )

    # 5.4. start recursion step
    res_called_function_raw_information: List[Tuple[bool, bool]] = []
    if called_function_cu not in recursively_visited:
        (
            recursively_visited,
            res_called_function_name,
            res_called_function_raw_information,
            function_raw_information_cache,
        ) = get_function_call_parameter_rw_information_recursion_step(
            pet,
            called_function_cu,
            recursively_visited,
            function_raw_information_cache,
            cu_inst_result_dict,
            function_parameter_alias_dict,
            source_code_files,
        )
        function_raw_information_cache[called_function_cu.name] = res_called_function_raw_information
    else:
        # read cache
        if called_function_cu.name in function_raw_information_cache:
            res_called_function_raw_information = function_raw_information_cache[called_function_cu.name]

    # 5.5 match parameter_names with gathered R/W information of argument positions
    if len(raw_reported_for_param_positions) != len(parameter_names):
        return None
    parameter_names_raw_information: List[Tuple[str, bool, bool]] = []
    if len(raw_reported_for_param_positions) == len(res_called_function_raw_information):
        for idx in range(0, len(parameter_names)):
            tmp = (
                parameter_names[idx],
                (raw_reported_for_param_positions[idx][0] or res_called_function_raw_information[idx][0]),
                res_called_function_raw_information[idx][1],
            )
            if tmp[0] is None:
                continue
            tmp_not_none = cast(Tuple[str, bool, bool], tmp)
            parameter_names_raw_information.append(tmp_not_none)
        # overwrite cache
        new_cache_line = []
        for idx in range(0, len(function_raw_information_cache[called_function_cu.name])):
            old_cache_line = function_raw_information_cache[called_function_cu.name]
            update = [elem[1] for elem in parameter_names_raw_information]
            new_cache_line.append(old_cache_line[idx] or update[idx])
        function_raw_information_cache[called_function_cu.name] = new_cache_line
    else:
        # ignore recursion results
        for idx in range(0, len(parameter_names)):
            tmp = (parameter_names[idx], raw_reported_for_param_positions[idx][0], False)
            if tmp[0] is None:
                continue
            tmp_not_none = cast(Tuple[str, bool, bool], tmp)
            parameter_names_raw_information.append(tmp_not_none)

    return (
        call_position,
        parameter_names_raw_information,
        recursively_visited,
        function_raw_information_cache,
    )


def get_function_call_parameter_rw_information_recursion_step(
    pet: PEGraphX,
    called_function_cu: FunctionNode,
    recursively_visited: List[Node],
    function_raw_information_cache: Dict[str, List[Tuple[bool, bool]]],
    cu_inst_result_dict: Dict[str, List[Dict[str, Optional[str]]]],
    function_parameter_alias_dict: Dict[str, List[Tuple[str, str]]],
    source_code_files: Dict[str, str],
) -> Tuple[List[Node], str, List[Tuple[bool, bool]], Dict[str, List[Tuple[bool, bool]]]]:
    """Wrapper to execute __get_function_call_parameter_rw_information recursively,
    i.e. for every function call in called functions body.
    The gathered information is aggregated via a logical disjunction on a per-variable level.
    Results only contain the information whether a given variable is modified at some point,
    the specific location is not included.
    :param pet: PET Graph
    :param called_function_cu: CU Node corresponding to the called function to be checked
    :param recursively_visited: List of already visited CU Nodes to prevent endless recursions
    :param function_raw_information_cache: Cache containing a mapping of function names to a list of booleans,
        representing the parameters of a given function and the information
        whether a specific parameter is modified by the respective function.
    :param cu_inst_result_dict: Contents of the CUInst_Result.txt, converted into a dict.
    :param function_parameter_alias_dict: results of function-internal alias detection in dict form
    :param source_code_files: File-Mapping dictionary
    :return: (recursively_visited, called_function_name,
              called_function_args_raw_information, function_raw_information_cache)
    """

    # get potential children of called function
    recursively_visited.append(called_function_cu)
    queue_1 = direct_children_or_called_nodes(pet, called_function_cu)
    potential_children = []
    visited = []
    while queue_1:
        cur_potential_child = queue_1.pop()
        visited.append(cur_potential_child)
        # test if cur_potential_child is inside cur_potential_parent_functions scope
        if line_contained_in_region(
            cur_potential_child.start_position(),
            called_function_cu.start_position(),
            called_function_cu.end_position(),
        ) and line_contained_in_region(
            cur_potential_child.end_position(),
            called_function_cu.start_position(),
            called_function_cu.end_position(),
        ):
            if cur_potential_child not in potential_children:
                potential_children.append(cur_potential_child)
        for tmp_child in direct_children_or_called_nodes(pet, cur_potential_child):
            if tmp_child not in queue_1 and tmp_child not in potential_children and tmp_child not in visited:
                queue_1.append(tmp_child)

    called_function_args_raw_information = []
    for var in called_function_cu.args:
        called_function_args_raw_information.append((var.name, False, False))

    for child in [
        c
        for c in potential_children
        if line_contained_in_region(
            c.start_position(),
            called_function_cu.start_position(),
            called_function_cu.end_position(),
        )
        and line_contained_in_region(
            c.end_position(), called_function_cu.start_position(), called_function_cu.end_position()
        )
    ]:
        # find called functions
        for child_func in direct_children_or_called_nodes_of_type(pet, child, FunctionNode):
            # apply __get_function_call_parameter_rw_information
            if child not in recursively_visited:
                ret_val = get_function_call_parameter_rw_information(
                    pet,
                    child.start_position(),
                    child,
                    int(child.start_position().split(":")[1]),
                    True,
                    True,
                    cu_inst_result_dict,
                    source_code_files,
                    recursively_visited,
                    function_raw_information_cache,
                    function_parameter_alias_dict,
                    called_function_name=child_func.name,
                )
                if ret_val is None:
                    continue
                (
                    recursive_function_call_line,
                    parameter_names_raw_information,
                    recursively_visited,
                    function_raw_information_cache,
                ) = ret_val
                # perform or-conjunction of RAW information parent <> child
                for (
                    child_var_name,
                    child_raw_info,
                    child_is_pessimistic,
                ) in parameter_names_raw_information:
                    for idx, (var_name, raw_info, is_pessimistic) in enumerate(called_function_args_raw_information):
                        if var_name == child_var_name:
                            called_function_args_raw_information[idx] = (
                                var_name,
                                raw_info or child_raw_info,
                                child_is_pessimistic or is_pessimistic,
                            )

    # if parameter alias entry for parent function exists:
    if called_function_cu.name in function_parameter_alias_dict:
        alias_entries = function_parameter_alias_dict[called_function_cu.name]
        for var_name_str, alias_name in alias_entries:
            var_name_2: VarName = VarName(var_name_str)
            var_name_is_modified = False
            # check if alias_name occurs in any depencendy in any of called_function_cu's children,
            # recursively visits all children cu nodes in function body.
            function_internal_cu_nodes: List[Node] = []
            queue: List[Node] = [called_function_cu]
            while len(queue) > 0:
                cur: Node = queue.pop(0)
                # check if cur inside function body, append to function_internal_cu_nodes if so
                if line_contained_in_region(
                    cur.start_position(),
                    called_function_cu.start_position(),
                    called_function_cu.end_position(),
                ) and line_contained_in_region(
                    cur.end_position(),
                    called_function_cu.start_position(),
                    called_function_cu.end_position(),
                ):
                    function_internal_cu_nodes.append(cur)
                # add children to queue
                for cur_child in direct_children_or_called_nodes(pet, cur):
                    if cur_child not in function_internal_cu_nodes and cur_child not in queue:
                        queue.append(cur_child)
            for child_cu in function_internal_cu_nodes:
                child_in_deps = in_edges(pet, child_cu.id, EdgeType.DATA)
                child_out_deps = out_edges(pet, child_cu.id, EdgeType.DATA)
                dep_var_names = [x[2].var_name for x in child_in_deps + child_out_deps]
                dep_var_names_not_none = [x for x in dep_var_names if x is not None]
                dep_var_names_not_none = [x.replace(".addr", "") for x in dep_var_names_not_none]
                if alias_name in dep_var_names_not_none:
                    var_name_is_modified = True
                    break
            if var_name_is_modified:
                # update RAW information
                for idx, (old_var_name, raw_info, _) in enumerate(called_function_args_raw_information):
                    if old_var_name == var_name_2:
                        if not raw_info:
                            called_function_args_raw_information[idx] = (old_var_name, True, True)
                            # second True denotes the pessimistic nature of a potential created dependency
    # remove names from called_function_args_raw_information
    called_function_args_raw_information_bools = [(e[1], e[2]) for e in called_function_args_raw_information]
    return (
        recursively_visited,
        called_function_cu.name,
        called_function_args_raw_information_bools,
        function_raw_information_cache,
    )

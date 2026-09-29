# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Dict, cast, Optional, Union

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.functions.PEGraph.queries.edges import in_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.pattern_detectors.task_parallelism.classes import (
    TaskParallelismInfo,
    ParallelRegionInfo,
    TPIType,
)
from discopop_explorer.pattern_detectors.task_parallelism.tp_utils import (
    line_contained_in_region,
    get_parent_of_type,
    get_cus_inside_function,
    check_reachability,
)
from discopop_explorer.utils import is_loop_index2


def filter_data_sharing_clauses(
    pet: PEGraphX, suggestions: List[PatternInfo], var_def_line_dict: Dict[str, List[str]]
) -> List[PatternInfo]:
    """Wrapper to filter data sharing clauses according to the included steps.
    :param pet: PET graph
    :param suggestions: List[PatternInfo]
    :param var_def_line_dict: Dictionary containing: var_name -> [definition lines]
    :return: List[PatternInfo]"""
    suggestions = __filter_data_sharing_clauses_by_function(pet, suggestions, var_def_line_dict)
    suggestions = __filter_data_sharing_clauses_by_scope(pet, suggestions, var_def_line_dict)
    suggestions = __filter_data_sharing_clauses_suppress_shared_loop_index(pet, suggestions)
    return suggestions


def __filter_data_sharing_clauses_suppress_shared_loop_index(
    pet: PEGraphX, suggestions: List[PatternInfo]
) -> List[PatternInfo]:
    """Removes clauses for shared loop indices.
    :param pet: PET graph
    :param suggestions: List[PatternInfo]
    :return: List[PatternInfo]"""
    for suggestion in suggestions:
        # only consider task suggestions
        if type(suggestion) != TaskParallelismInfo:
            continue
        if suggestion.type is not TPIType.TASK:
            continue
        # get parent loops of suggestion
        parent_loops_plus_last_node = get_parent_of_type(pet, suggestion._node, NodeType.LOOP, EdgeType.CHILD, True)
        parent_loops = [e[0] for e in parent_loops_plus_last_node]
        # consider only loops which enclose the suggestion
        parent_loops = [
            loop
            for loop in parent_loops
            if line_contained_in_region(suggestion._node.start_position(), loop.start_position(), loop.end_position())
        ]
        to_be_removed = []
        for var in suggestion.shared:
            for parent_loop in parent_loops:
                if is_loop_index2(pet, parent_loop, var):
                    to_be_removed.append(var)
        to_be_removed = list(dict.fromkeys(to_be_removed))
        suggestion.shared = [v for v in suggestion.shared if v not in to_be_removed]
    return suggestions


def __filter_data_sharing_clauses_by_function(
    pet: PEGraphX, suggestions: List[PatternInfo], var_def_line_dict: Dict[str, List[str]]
) -> List[PatternInfo]:
    """Removes superfluous variables (not known in parent function of suggestion) from the data sharing clauses
    of task suggestions.
    Removes .addr suffix from variable names
    Removes entries if Variable occurs in different classes. Removes in following order:
    firstprivate, private, shared
    :param pet: PET graph
    :param suggestions: List[PatternInfo]
    :param var_def_line_dict: Dictionary containing: var_name -> [definition lines]
    :return: List[PatternInfo]
    """
    for suggestion in suggestions:
        # only consider task suggestions
        if type(suggestion) != TaskParallelismInfo:
            continue
        if suggestion.type not in [TPIType.TASK, TPIType.TASKLOOP]:
            continue
        # get function containing the task cu
        parent_function, last_node = get_parent_of_type(pet, suggestion._node, NodeType.FUNC, EdgeType.CHILD, True)[0]
        # filter firstprivate
        __filter_firstprivate_clauses(suggestion, parent_function, var_def_line_dict)
        # filter private
        __filter_private_clauses(suggestion, parent_function, var_def_line_dict)
        # filter shared
        __filter_shared_clauses(suggestion, parent_function, var_def_line_dict)

        # remove duplicates and .addr suffix from variable names
        suggestion.shared = list(dict.fromkeys([v.replace(".addr", "") for v in suggestion.shared]))
        suggestion.private = list(dict.fromkeys([v.replace(".addr", "") for v in suggestion.private]))
        suggestion.first_private = list(dict.fromkeys([v.replace(".addr", "") for v in suggestion.first_private]))

        # remove duplicates (variable occurring in different classes)
        remove_from_first_private = []
        remove_from_private = []
        for var in suggestion.shared:
            if var in suggestion.private:
                remove_from_private.append(var)
            if var in suggestion.first_private:
                remove_from_first_private.append(var)
        for var in suggestion.private:
            if var in suggestion.first_private:
                remove_from_first_private.append(var)
        remove_from_first_private = list(dict.fromkeys(remove_from_first_private))
        remove_from_private = list(dict.fromkeys(remove_from_private))
        remove_from_private = [var for var in remove_from_private if var not in remove_from_first_private]
        suggestion.private = [var for var in suggestion.private if var not in remove_from_private]
        suggestion.first_private = [var for var in suggestion.first_private if var not in remove_from_first_private]
    return suggestions


def __filter_shared_clauses(
    suggestion: TaskParallelismInfo, parent_function: Node, var_def_line_dict: Dict[str, List[str]]
) -> None:
    """helper function for filter_data_sharing_clauses_by_function.
    Filters shared clauses.
    :param suggestion: Suggestion to be checked
    :param parent_function: parent function CU Node
    :param var_def_line_dict: Dictionary containing: var_name -> [definition lines]
    """
    to_be_removed = []
    for var in suggestion.shared:
        var = var.replace(".addr", "")
        is_valid = False
        try:
            for def_line in var_def_line_dict[var]:
                # ensure backwards compatibility (no definition line present in cu_xml
                if def_line == "GlobalVar" or def_line == "LineNotFound":
                    is_valid = False
                    break
                if def_line is None:
                    is_valid = True
                # check if var is defined in parent function
                if line_contained_in_region(def_line, parent_function.start_position(), parent_function.end_position()):
                    is_valid = True
                else:
                    pass
        except ValueError as ve:
            raise ve
            pass
        if not is_valid:
            to_be_removed.append(var)
    to_be_removed = list(dict.fromkeys(to_be_removed))
    suggestion.shared = [v for v in suggestion.shared if not v.replace(".addr", "") in to_be_removed]


def __filter_private_clauses(
    suggestion: TaskParallelismInfo, parent_function: Node, var_def_line_dict: Dict[str, List[str]]
) -> None:
    """helper function for filter_data_sharing_clauses_by_function.
    Filters private clauses.
    :param suggestion: Suggestion to be checked
    :param parent_function: parent function CU Node
    :param var_def_line_dict: Dictionary containing: var_name -> [definition lines]
    """
    to_be_removed = []
    for var in suggestion.private:
        var = var.replace(".addr", "")
        is_valid = False
        try:
            for defLine in var_def_line_dict[var]:
                # catch GlobalVar and LineNotFound
                if defLine == "GlobalVar":
                    is_valid = True
                    continue
                if defLine == "LineNotFound":
                    continue
                # ensure backwards compatibility (no definition line present in cu_xml
                if defLine is None:
                    is_valid = True
                # check if var is defined in parent function
                elif line_contained_in_region(
                    defLine, parent_function.start_position(), parent_function.end_position()
                ):
                    is_valid = True
                else:
                    pass
        except ValueError:
            pass
        if not is_valid:
            to_be_removed.append(var)
    to_be_removed = list(dict.fromkeys(to_be_removed))
    suggestion.private = [v for v in suggestion.private if not v.replace(".addr", "") in to_be_removed]


def __filter_firstprivate_clauses(
    suggestion: TaskParallelismInfo, parent_function: Node, var_def_line_dict: Dict[str, List[str]]
) -> None:
    """helper function for filter_data_sharing_clauses_by_function.
    Filters firstprivate clauses.
    :param suggestion: Suggestion to be checked
    :param parent_function: parent function CU Node
    :param var_def_line_dict: Dictionary containing: var_name -> [definition lines]
    """
    to_be_removed = []
    for var in suggestion.first_private:
        var = var.replace(".addr", "")
        is_valid = False
        try:
            for defLine in var_def_line_dict[var]:
                # ensure backwards compatibility (no definition line present in cu_xml
                if defLine is None:
                    is_valid = True
                # check if var is defined in parent function
                if line_contained_in_region(defLine, parent_function.start_position(), parent_function.end_position()):
                    is_valid = True
                else:
                    pass
        except ValueError:
            pass
        if not is_valid:
            to_be_removed.append(var)
    to_be_removed = list(dict.fromkeys(to_be_removed))
    suggestion.first_private = [v for v in suggestion.first_private if not v.replace(".addr", "") in to_be_removed]


def __reverse_reachable_w_o_breaker(
    pet: PEGraphX, root: Node, target: Node, breaker_cu: Node, visited: List[Node]
) -> bool:
    """Helper function for filter_data_sharing_clauses_by_scope.
    Checks if target is reachable by traversing the successor graph in reverse, starting from root,
    without visiting breaker_cu.
    :param pet: PET Graph
    :param root: root node
    :param target: target node
    :param breaker_cu: breaker cu
    :param visited: list of already visited CUNodes
    :return: True, if target is reachable without visiting breaker_cu. False, otherwise."""
    if root in visited:
        return False
    visited.append(root)
    if root == target:
        return True
    if root == breaker_cu:
        return False
    recursion_result = False
    # start recursion for each incoming edge
    for tmp_e in in_edges(pet, root.id, EdgeType.SUCCESSOR):
        recursion_result = recursion_result or __reverse_reachable_w_o_breaker(
            pet, pet.node_at(tmp_e[0]), target, breaker_cu, visited
        )
    return recursion_result


def __filter_data_sharing_clauses_by_scope(
    pet: PEGraphX, suggestions: List[PatternInfo], var_def_line_dict: Dict[str, List[str]]
) -> List[PatternInfo]:
    """Filters out such data sharing clauses which belong to unknown variables at the source location of a given
    suggestion.
    Idea (per shared variable / suggestion):
    1.  Validate based on control flow:
        check if reverse path through successor graph from Task Suggestion CU to parent function CU exists,
        which doesn't cross the CU containing variable definition line (i.e. definition and task suggestion in separate
        branches of control flow graph).
    2.  Validate based on Scoping:
        If var-def has an incoming child-edge from X,
        check if task suggestions CU is reachable from X by traversing the child graph (i.e. TS CU is inside or
        below scope of X, thus var might be known).
    :param pet: PET graph
    :param suggestions: List[PatternInfo]
    :param var_def_line_dict: Dictionary containing: var_name -> [definition lines]
    :return: List[PatternInfo]
    """
    for suggestion in suggestions:
        # only consider task suggestions
        if type(suggestion) != TaskParallelismInfo:
            continue
        if suggestion.type is not TPIType.TASK:
            continue
        # get function containing the task cu
        parent_function_cu, last_node = get_parent_of_type(pet, suggestion._node, NodeType.FUNC, EdgeType.CHILD, True)[
            0
        ]
        # filter firstprivate
        __filter_sharing_clause(pet, suggestion, var_def_line_dict, parent_function_cu, "FP")
        # filter private
        __filter_sharing_clause(pet, suggestion, var_def_line_dict, parent_function_cu, "PR")
        # filter shared
        __filter_sharing_clause(pet, suggestion, var_def_line_dict, parent_function_cu, "SH")
    return suggestions


def __filter_sharing_clause(
    pet: PEGraphX,
    suggestion: TaskParallelismInfo,
    var_def_line_dict: Dict[str, List[str]],
    parent_function_cu: Node,
    target_clause_list: str,
) -> None:
    """Helper function for filter_data_sharing_clauses_by_scope.
    Filters a given suggestions private, firstprivate or shared variables list,
    depending on the specific value of target_clause_list.
    :param pet: PET Graph
    :param suggestion: suggestion to be checked
    :param var_def_line_dict: dictionary containing: var_name -> [definition lines]
    :param parent_function_cu: CUNode corresponding to the function which contains the suggestion
    :param target_clause_list: One of: ['FP', 'PR', 'SH'], used to control which list of variables is filtered
    """
    to_be_removed = []
    if target_clause_list == "FP":
        sharing_clause_list = suggestion.first_private
    elif target_clause_list == "PR":
        sharing_clause_list = suggestion.private
    else:
        sharing_clause_list = suggestion.shared

    for var in sharing_clause_list:
        for var_def_line in var_def_line_dict[var]:
            if var_def_line == "GlobalVar":
                # accept global vars
                continue
            # get CU which contains var_def_line
            var_def_cu: Optional[Node] = None
            for child_cu in get_cus_inside_function(pet, parent_function_cu):
                if line_contained_in_region(var_def_line, child_cu.start_position(), child_cu.end_position()):
                    var_def_cu = child_cu
            if var_def_cu is None:
                continue
            # 1. check control flow (reverse BFS from suggestion._node to parent_function
            if __reverse_reachable_w_o_breaker(
                pet, pet.node_at(suggestion.node_id), parent_function_cu, var_def_cu, []
            ):
                # remove var as it may not be known
                to_be_removed.append(var)
                continue
            # 2. check if task suggestion is child of same nodes as var_def_cu
            for in_child_edge in in_edges(pet, var_def_cu.id, [EdgeType.CHILD, EdgeType.CALLSNODE]):
                parent_cu = pet.node_at(in_child_edge[0])
                # check if task suggestion cu is reachable from parent via child edges
                if not check_reachability(pet, suggestion._node, parent_cu, [EdgeType.CHILD]):
                    to_be_removed.append(var)
        to_be_removed = list(dict.fromkeys(to_be_removed))
        if target_clause_list == "FP":
            suggestion.first_private = [v for v in suggestion.first_private if v not in to_be_removed]
        elif target_clause_list == "PR":
            suggestion.private = [v for v in suggestion.private if v not in to_be_removed]
        else:
            suggestion.shared = [v for v in suggestion.shared if v not in to_be_removed]


def remove_useless_barrier_suggestions(
    pet: PEGraphX, suggestions: List[TaskParallelismInfo]
) -> List[TaskParallelismInfo]:
    """remove suggested barriers which are not contained in the same
    function body with at least one suggested task.
    Returns the filtered version of the list given as a parameter.
    :param pet: PET graph
    :param suggestions: List[TaskParallelismInfo]
    :return: List[TaskParallelismInfo]
    """
    # split suggestions into task and taskwait suggestions
    taskwait_suggestions = []
    task_suggestions = []
    result_suggestions = []
    for single_suggestion in suggestions:
        if single_suggestion.type is TPIType.TASKWAIT:
            taskwait_suggestions.append(single_suggestion)
        elif single_suggestion.type is TPIType.TASK:
            task_suggestions.append(single_suggestion)
        else:
            result_suggestions.append(single_suggestion)
    # get map of function body cus containing task suggestions to line number
    # of task pragmas
    relevant_function_bodies: Dict[Node, List[str]] = {}
    for ts in task_suggestions:
        # get first parent cu with type function using bfs
        parent: Node = get_parent_of_type(pet, ts._node, NodeType.FUNC, EdgeType.CHILD, True)[0][0]
        if parent not in relevant_function_bodies:
            relevant_function_bodies[parent] = [ts.pragma_line]
        else:
            relevant_function_bodies[parent].append(ts.pragma_line)
    # remove suggested barriers which are no descendants of relevant functions
    result_suggestions += task_suggestions
    for tws in taskwait_suggestions:
        tws_line_id = tws.pragma_line
        tws_line_number = tws_line_id[tws_line_id.index(":") + 1 :]
        for rel_func_body in relevant_function_bodies.keys():
            if check_reachability(pet, tws._node, rel_func_body, [EdgeType.CHILD]):
                # remove suggested barriers where line number smaller than
                # pragma line number of task
                for line_number in relevant_function_bodies[rel_func_body]:
                    if line_number <= tws_line_number:
                        result_suggestions.append(tws)
                        break
    return result_suggestions


def remove_duplicate_data_sharing_clauses(suggestions: List[PatternInfo]) -> List[PatternInfo]:
    """removes duplicates from in, out and in-out dependency lists.
    Mainly needed for printing purposes.
    :param suggestions: List[PatternInfo]
    :return: Modified List of PatternInfos
    """
    result: List[PatternInfo] = []
    for s in suggestions:
        if not type(s) == TaskParallelismInfo:
            result.append(s)
        else:
            s.in_dep = list(dict.fromkeys(s.in_dep))
            s.out_dep = list(dict.fromkeys(s.out_dep))
            s.in_out_dep = list(dict.fromkeys(s.in_out_dep))
            result.append(s)
    return result


def __filter_in_dependencies(
    pet: PEGraphX,
    suggestion: TaskParallelismInfo,
    var_def_line_dict: Dict[str, List[str]],
    parent_function: Node,
    out_dep_vars: Dict[str, List[str]],
) -> bool:
    """Helper function for filter_data_depend_clauses.
    Filters in-dependencies of the given suggestion.
    :param pet: PET Graph
    :param suggestion: suggestion to be filtered
    :param var_def_line_dict: Dictionary containing: var_name -> [definition lines]
    :param parent_function: parent function containing suggestion
    :param out_dep_vars: variables used in outgoing dependencies
    :return: True, if a modification of suggestion.out_dep has been made. False, otherwise."""
    to_be_removed = []
    modification_found = False
    for var in suggestion.in_dep:
        var = var.replace(".addr", "")
        is_valid = False
        try:
            for defLine in var_def_line_dict[var]:
                # ensure backwards compatibility (no definition line present in cu_xml
                if defLine is None:
                    is_valid = True
                # check if var is defined in parent function
                if line_contained_in_region(defLine, parent_function.start_position(), parent_function.end_position()):
                    # check if var is contained in out_dep_vars and a previous out_dep exists
                    if var in out_dep_vars:
                        for line_num in out_dep_vars[var]:
                            line_num = str(line_num)
                            if ":" in line_num:
                                line_num = line_num.split(":")[1]
                            # check validity of the dependence by reachability checking on
                            # successor + child graph

                            # get CU containing line_num
                            for cu_node in all_nodes(pet, CUNode):
                                file_id = suggestion._node.start_position().split(":")[0]
                                test_line = file_id + ":" + line_num
                                # check if line_num is contained in cu_node
                                if not line_contained_in_region(
                                    test_line, cu_node.start_position(), cu_node.end_position()
                                ):
                                    continue
                                # check if path from cu_node to suggestion._node exists
                                if check_reachability(
                                    pet,
                                    suggestion._node,
                                    cu_node,
                                    [EdgeType.SUCCESSOR, EdgeType.CHILD],
                                ):
                                    is_valid = True
                else:
                    pass
        except ValueError:
            pass
        if not is_valid:
            modification_found = True
            to_be_removed.append(var)
    to_be_removed = list(dict.fromkeys(to_be_removed))
    suggestion.in_dep = [v for v in suggestion.in_dep if not v.replace(".addr", "") in to_be_removed]
    return modification_found


def __filter_out_dependencies(
    pet: PEGraphX,
    suggestion: TaskParallelismInfo,
    var_def_line_dict: Dict[str, List[str]],
    parent_function: Node,
    in_dep_vars: Dict[str, List[str]],
) -> bool:
    """Helper function for filter_data_depend_clauses.
    Filters out-dependencies of the given suggestion.
    :param pet: PET Graph
    :param suggestion: suggestion to be filtered
    :param var_def_line_dict: Dictionary containing: var_name -> [definition lines]
    :param parent_function: parent function containing suggestion
    :param in_dep_vars: variables used in incoming dependencies
    :return: True, if a modification of suggestion.out_dep has been made. False, otherwise."""
    modification_found = False
    to_be_removed = []
    for var in suggestion.out_dep:
        var = var.replace(".addr", "")
        is_valid = False
        try:
            for defLine in var_def_line_dict[var]:
                # ensure backwards compatibility (no definition line present in cu_xml
                if defLine is None:
                    is_valid = True
                # check if var is defined in parent function
                if line_contained_in_region(defLine, parent_function.start_position(), parent_function.end_position()):
                    # check if var is contained in in_dep_vars and a successive in_dep exists
                    if var in in_dep_vars:
                        for line_num in in_dep_vars[var]:
                            line_num = str(line_num)
                            if ":" in line_num:
                                line_num = line_num.split(":")[1]
                            # check validity of the dependence by reachability checking on
                            # successor + child graph

                            # get CU containing line_num
                            for cu_node in all_nodes(pet, CUNode):
                                file_id = suggestion._node.start_position().split(":")[0]
                                test_line = file_id + ":" + line_num
                                # check if line_num is contained in cu_node
                                if not line_contained_in_region(
                                    test_line, cu_node.start_position(), cu_node.end_position()
                                ):
                                    continue
                                # check if path from suggestion._node to cu_node exists
                                if check_reachability(
                                    pet,
                                    cu_node,
                                    suggestion._node,
                                    [EdgeType.SUCCESSOR, EdgeType.CHILD],
                                ):
                                    is_valid = True
                else:
                    pass
        except ValueError:
            pass
        if not is_valid:
            to_be_removed.append(var)
            modification_found = True
    to_be_removed = list(dict.fromkeys(to_be_removed))
    suggestion.out_dep = [v for v in suggestion.out_dep if not v.replace(".addr", "") in to_be_removed]
    return modification_found


def __filter_in_out_dependencies(
    pet: PEGraphX,
    suggestion: TaskParallelismInfo,
    var_def_line_dict: Dict[str, List[str]],
    parent_function: Node,
    in_dep_vars: Dict[str, List[str]],
    out_dep_vars: Dict[str, List[str]],
) -> bool:
    """Helper function for filter_data_depend_clauses.
    Filters in_out-dependencies of the given suggestion.
    :param pet: PET Graph
    :param suggestion: suggestion to be filtered
    :param var_def_line_dict: Dictionary containing: var_name -> [definition lines]
    :param parent_function: parent function containing suggestion
    :param in_dep_vars: variables used in incoming dependencies
    :param out_dep_vars: variables used in incoming dependencies
    :return: True, if a modification of suggestion.in_out_dep has been made. False, otherwise."""
    modification_found = False
    to_be_removed = []
    for var in suggestion.in_out_dep:
        var = var.replace(".addr", "")
        is_valid = False
        try:
            for defLine in var_def_line_dict[var]:
                # ensure backwards compatibility (no definition line present in cu_xml
                if defLine is None:
                    is_valid = True
                # check if var is defined in parent function
                if line_contained_in_region(defLine, parent_function.start_position(), parent_function.end_position()):
                    # check if var occurs more than once as in or out, i.e. at least an actual in or out
                    # dependency exists
                    if len(in_dep_vars[var]) > 1 or len(out_dep_vars[var]) > 1:
                        # check if out dep prior an in dep afterwards exist
                        prior_out_exists = False
                        successive_in_exists = False
                        for line_num in out_dep_vars[var]:
                            line_num = str(line_num)
                            if ":" in line_num:
                                line_num = line_num.split(":")[1]
                            # check validity of the dependence by reachability checking on
                            # successor + child graph

                            # get CU containing line_num
                            for cu_node in all_nodes(pet, CUNode):
                                file_id = suggestion._node.start_position().split(":")[0]
                                test_line = file_id + ":" + line_num
                                # check if line_num is contained in cu_node
                                if not line_contained_in_region(
                                    test_line, cu_node.start_position(), cu_node.end_position()
                                ):
                                    continue
                                # check if path from cu_node to suggestion._node exists
                                if check_reachability(
                                    pet,
                                    suggestion._node,
                                    cu_node,
                                    [EdgeType.SUCCESSOR, EdgeType.CHILD],
                                ):
                                    prior_out_exists = True
                        for line_num in in_dep_vars[var]:
                            line_num = str(line_num)
                            if ":" in line_num:
                                line_num = line_num.split(":")[1]
                            # check validity of the dependence by reachability checking on
                            # successor + child graph

                            # get CU containing line_num
                            for cu_node in all_nodes(pet, CUNode):
                                file_id = suggestion._node.start_position().split(":")[0]
                                test_line = file_id + ":" + line_num
                                # check if line_num is contained in cu_node
                                if not line_contained_in_region(
                                    test_line, cu_node.start_position(), cu_node.end_position()
                                ):
                                    continue
                                # check if path from suggestion._node to cu_node exists
                                if check_reachability(
                                    pet,
                                    cu_node,
                                    suggestion._node,
                                    [EdgeType.SUCCESSOR, EdgeType.CHILD],
                                ):
                                    successive_in_exists = True
                        # check and treat conditions
                        if prior_out_exists and successive_in_exists:
                            # proper in_out_dep
                            is_valid = True
                        elif prior_out_exists and not successive_in_exists:
                            # depend in
                            suggestion.in_dep.append(var)
                            suggestion.in_dep = list(dict.fromkeys(suggestion.in_dep))
                        elif not prior_out_exists and successive_in_exists:
                            # depend out
                            suggestion.out_dep.append(var)
                            suggestion.out_dep = list(dict.fromkeys(suggestion.out_dep))
                else:
                    pass
        except ValueError:
            pass
        if not is_valid:
            to_be_removed.append(var)
            modification_found = True
    to_be_removed = list(dict.fromkeys(to_be_removed))
    suggestion.in_out_dep = [v for v in suggestion.in_out_dep if not v.replace(".addr", "") in to_be_removed]
    return modification_found


def filter_data_depend_clauses(
    pet: PEGraphX, suggestions: List[PatternInfo], var_def_line_dict: Dict[str, List[str]]
) -> List[PatternInfo]:
    """Removes superfluous variables from the data depend clauses
    of task suggestions.
    :param pet: PET graph
    :param suggestions: List[PatternInfo]
    :param var_def_line_dict: Dictionary containing mapping from var_name to [definition lines]
    :return: List[PatternInfo]
    """
    modification_found = True
    while modification_found:
        # get list of used variabled by dependency type
        in_dep_vars: Dict[str, List[str]] = dict()
        out_dep_vars: Dict[str, List[str]] = dict()
        for suggestion in suggestions:
            # only consider task suggestions
            if type(suggestion) != TaskParallelismInfo:
                continue
            if suggestion.type not in [TPIType.TASK, TPIType.TASKLOOP]:
                continue
            for var in suggestion.in_dep:
                if var not in in_dep_vars:
                    in_dep_vars[var] = []
                in_dep_vars[var].append(suggestion.pragma_line)
            for var in suggestion.out_dep:
                if var not in out_dep_vars:
                    out_dep_vars[var] = []
                out_dep_vars[var].append(suggestion.pragma_line)
            for var in suggestion.in_out_dep:
                if var not in in_dep_vars:
                    in_dep_vars[var] = []
                in_dep_vars[var].append(suggestion.pragma_line)
                if var not in out_dep_vars:
                    out_dep_vars[var] = []
                out_dep_vars[var].append(suggestion.pragma_line)

        # filter dependency clauses
        modification_found = False
        for suggestion in suggestions:
            # only consider task suggestions
            if type(suggestion) != TaskParallelismInfo:
                continue
            if suggestion.type not in [TPIType.TASK, TPIType.TASKLOOP]:
                continue
            # get function containing the task cu
            parent_function, last_node = get_parent_of_type(pet, suggestion._node, NodeType.FUNC, EdgeType.CHILD, True)[
                0
            ]
            # filter in_dep
            modification_found = modification_found or __filter_in_dependencies(
                pet, suggestion, var_def_line_dict, parent_function, out_dep_vars
            )
            # filter out_dep
            modification_found = modification_found or __filter_out_dependencies(
                pet, suggestion, var_def_line_dict, parent_function, in_dep_vars
            )
            # filter in_out_dep
            modification_found = modification_found or __filter_in_out_dependencies(
                pet, suggestion, var_def_line_dict, parent_function, in_dep_vars, out_dep_vars
            )

            # correct in_out_vars (find in_out vars if not already detected)
            overlap = [v for v in suggestion.in_dep if v in suggestion.out_dep]
            for v in overlap:
                if v not in suggestion.in_out_dep:
                    modification_found = True
                suggestion.in_dep.remove(v)
                suggestion.out_dep.remove(v)
                suggestion.in_out_dep.append(v)
            suggestion.in_out_dep = list(dict.fromkeys(suggestion.in_out_dep))
            # correct in_out vars (remove from in and out)
            for v in suggestion.in_out_dep:
                if v in suggestion.in_dep:
                    suggestion.in_dep.remove(v)
                    modification_found = True
                if v in suggestion.out_dep:
                    suggestion.out_dep.remove(v)
                    modification_found = True

    return suggestions


def remove_duplicates(suggestions: List[PatternInfo]) -> List[PatternInfo]:
    """removes duplicates from the list of suggestions and return the modified
    list.
    CU-ID is not considered.
    Removes a suggestion, if one with identical region_start_line,
    region_end_line and pragma exists.
    :param suggestions: List[PatternInfo]
    :return: List[PatternInfo]
    """
    buffer = []  # list of tuples containing region_start_line,
    # region_end_line and pragma, representing suggestions
    result: List[PatternInfo] = []
    for sug in suggestions:
        if type(sug) == ParallelRegionInfo:
            sug_tmp = cast(Union[TaskParallelismInfo, ParallelRegionInfo], sug)
        elif type(sug) == TaskParallelismInfo:
            sug_tmp = cast(Union[TaskParallelismInfo, ParallelRegionInfo], sug)
        else:
            continue
        representing_tuple = (sug_tmp.region_start_line, sug_tmp.region_end_line, sug_tmp.pragma)
        if representing_tuple in buffer:
            continue
        else:
            buffer.append(representing_tuple)
            result.append(sug)
    return result

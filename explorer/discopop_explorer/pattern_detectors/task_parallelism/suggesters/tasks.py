# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Dict, cast

from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.enums.MWType import MWType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.traversal.children import direct_children_or_called_nodes
from discopop_explorer.functions.PEGraph.traversal.successors import direct_successors
from discopop_explorer.pattern_detectors.task_parallelism.classes import (
    TaskParallelismInfo,
    TPIType,
)
from discopop_explorer.pattern_detectors.task_parallelism.tp_utils import (
    recursive_function_call_contained_in_worker_cu,
    line_contained_in_region,
    contains_reduction,
)
from discopop_explorer.utils import classify_task_vars


def detect_task_suggestions(pet: PEGraphX) -> List[PatternInfo]:
    """creates task parallelism suggestions and returns them as a list of
    TaskParallelismInfo objects.
    Currently relies on previous processing steps and suggests WORKER CUs
    as Tasks and BARRIER/BARRIER_WORKER as Taskwaits.
    :param pet: PET graph
    :return: List[TaskParallelismInfo]
    """
    # suggestions contains a map from LID to a set of suggestions. This is required to
    # detect multiple suggestions for a single line of source code.
    suggestions: Dict[str, List[TaskParallelismInfo]] = dict()  # LID -> List[TaskParallelismInfo]

    # get a list of cus classified as WORKER
    worker_cus: List[Node] = []
    barrier_cus: List[Node] = []
    barrier_worker_cus: List[Node] = []

    func_cus: List[Node] = []

    for v in all_nodes(pet):
        if v.mw_type == MWType.WORKER:
            worker_cus.append(v)
        if v.mw_type == MWType.BARRIER:
            barrier_cus.append(v)
        if v.mw_type == MWType.BARRIER_WORKER:
            barrier_worker_cus.append(v)
        if isinstance(v, FunctionNode):
            func_cus.append(v)

    worker_cus = worker_cus + barrier_worker_cus + func_cus

    # SUGGEST TASKWAIT
    for v in barrier_cus:
        # get line number of first dependency. suggest taskwait prior to that
        first_dependency_line = v.end_position()
        first_dependency_line_number = first_dependency_line[first_dependency_line.index(":") + 1 :]
        for s, t, e in out_edges(pet, v.id):
            if e.etype == EdgeType.DATA:
                dep_line = cast(LineID, e.sink_line)
                dep_line_number = dep_line[dep_line.index(":") + 1 :]
                if dep_line_number < first_dependency_line_number:
                    first_dependency_line = dep_line
        tmp_suggestion = TaskParallelismInfo(v, TPIType.TASKWAIT, ["taskwait"], first_dependency_line, [], [], [])
        if v.start_position() not in suggestions:
            # no entry for source code line contained in suggestions
            suggestions[v.start_position()] = []
            suggestions[v.start_position()].append(tmp_suggestion)
        else:
            # entry for source code line already contained in suggestions
            suggestions[v.start_position()].append(tmp_suggestion)

    # SUGGEST TASKS
    for vx in all_nodes(pet):
        # iterate over all entries in recursiveFunctionCalls
        # in order to find task suggestions
        for i in range(0, len(vx.recursive_function_calls)):
            function_call_string = vx.recursive_function_calls[i]
            if not type(function_call_string) == str:
                continue
            contained_in = recursive_function_call_contained_in_worker_cu(function_call_string, worker_cus)
            if contained_in is not None:
                current_suggestions = None
                # recursive Function call contained in worker cu
                # -> issue task suggestion
                pragma_line = function_call_string[function_call_string.index(":") + 1 :]
                pragma_line = pragma_line.replace(",", "").replace(" ", "")

                # only include cu and func nodes
                if not isinstance(contained_in, (FunctionNode, CUNode)):
                    continue
                if (
                    contained_in.mw_type == MWType.WORKER
                    or contained_in.mw_type == MWType.BARRIER_WORKER
                    or isinstance(contained_in, FunctionNode)
                ):
                    # suggest task
                    fpriv, priv, shared, in_dep, out_dep, in_out_dep, red = classify_task_vars(
                        pet, contained_in, "", [], [], used_in_task_parallelism_detection=True
                    )
                    current_suggestions = TaskParallelismInfo(
                        vx,
                        TPIType.TASK,
                        ["task"],
                        pragma_line,
                        [v.name for v in fpriv],
                        [v.name for v in priv],
                        [v.name for v in shared],
                    )

                # insert current_suggestions into suggestions
                # check, if current_suggestions contains an element
                if current_suggestions is not None:
                    # current_suggestions contains something
                    if pragma_line not in suggestions:
                        # LID not contained in suggestions
                        suggestions[pragma_line] = []
                        suggestions[pragma_line].append(current_suggestions)
                    else:
                        # LID already contained in suggestions
                        suggestions[pragma_line].append(current_suggestions)
    # end of for loop

    # construct return value (list of TaskParallelismInfo)
    result: List[PatternInfo] = []
    for key in suggestions:
        for single_suggestion in suggestions[key]:
            result.append(single_suggestion)
    return result


def correct_task_suggestions_in_loop_body(pet: PEGraphX, suggestions: List[PatternInfo]) -> List[PatternInfo]:
    """Separate treatment of task suggestions at loop increment CUs.
    If regular loop: move taskwait suggested at loop increment line to end of loop body.
    If do-all loop: move taskwait suggested at loop increment line outside of loop body.
    If critical CUs are detected in the process, they will be appended to the critical_sections
    of the respective task suggestion.
    If atomic CUs are detected in the process, they will be appended to the atomic_sections
    of the respective task suggestion.
    :param pet: PET graph
    :param suggestions: Found suggestions
    :return: Updated suggestions"""
    task_suggestions = [s for s in [e for e in suggestions if type(e) == TaskParallelismInfo] if s.type is TPIType.TASK]
    for ts in task_suggestions:
        found_critical_cus: List[Node] = []
        found_atomic_cus: List[Node] = []
        for loop_cu in all_nodes(pet, LoopNode):
            # check if task suggestion inside do-all loop exists
            if line_contained_in_region(ts._node.start_position(), loop_cu.start_position(), loop_cu.end_position()):

                def find_taskwaits(cu_node: Node, visited: List[Node]) -> List[Node]:
                    if cu_node.tp_contains_taskwait:
                        return [cu_node]
                    result = []
                    visited.append(cu_node)
                    for succ_cu_node in [
                        pet.node_at(t)
                        for s, t, e in out_edges(pet, cu_node.id)
                        if e.etype == EdgeType.SUCCESSOR and pet.node_at(t) != cu_node
                    ]:
                        if succ_cu_node not in visited:
                            result += find_taskwaits(succ_cu_node, visited)
                    return result

                # find successive taskwaits
                successive_taskwait_cus = cast(List[CUNode], find_taskwaits(ts._node, []))
                for stws_cu in successive_taskwait_cus:
                    if loop_cu.do_all:
                        # check if stws is suggested at loop increment
                        if stws_cu.basic_block_id != "for.inc":
                            continue
                        # Do-all loop, move taskwait to the outside
                        print(
                            "TPDet: correct_task_suggestions_in_loop_body: Task in do-all loop ",
                            ts.pragma_line,
                            ". Moving Taskwait ",
                            stws_cu.start_line,
                            " to: ",
                            int(loop_cu.end_position().split(":")[1]) + 1,
                        )
                        for s in suggestions:
                            if type(s) == TaskParallelismInfo:
                                if s.type is TPIType.TASKWAIT and s._node == stws_cu:
                                    s.pragma_line = LineID(
                                        str(loop_cu.file_id) + ":" + str(int(loop_cu.end_position().split(":")[1]) + 1)
                                    )

                    else:
                        # Regular loop: task = loop body, move taskwait to the end of the loop body
                        # protect RAW to shared with critical section around CU (general)  or atomic (reduction)
                        print(
                            "TPDet: correct_task_suggestions_in_loop_body: Task in regular loop ",
                            ts.pragma_line,
                            ". Moving Taskwait ",
                            stws_cu.start_line,
                            " to: ",
                            int(loop_cu.end_position().split(":")[1]),
                            ".",
                        )
                        # move pragma taskwait line
                        for s in suggestions:
                            if type(s) == TaskParallelismInfo:
                                if s.type is TPIType.TASKWAIT and s._node == stws_cu:
                                    s.pragma_line = loop_cu.end_position()
                        # move pragma task line to beginning of loop body (i.e. make the entire loop body a task)
                        # set task region lines accordingly
                        # if ts._node is a direct child of loop_cu
                        if loop_cu.id in [e[0] for e in in_edges(pet, ts._node.id, EdgeType.CHILD)]:
                            print(
                                "Moving Pragma from: ",
                                ts.pragma_line,
                                " to: ",
                                int(loop_cu.start_position().split(":")[1]) + 1,
                            )
                            ts.pragma_line = LineID(
                                str(loop_cu.file_id) + ":" + str(int(loop_cu.start_position().split(":")[1]) + 1)
                            )
                            ts.region_start_line = str(ts.pragma_line)
                            ts.region_end_line = loop_cu.end_position()

                            # protect RAW-Writes to shared variables with critical section
                            # i.e. find in-deps to shared variables and suggest critical section around CUs
                            # containing such cases
                            for loop_cu_child in direct_children_or_called_nodes(pet, loop_cu):
                                for in_dep_var_name in list(
                                    set([e[2].var_name for e in in_edges(pet, loop_cu_child.id, EdgeType.DATA)])
                                ):
                                    if in_dep_var_name in ts.shared:
                                        # check if the found dependency occurs in the scope of the suggested task
                                        if (
                                            loop_cu_child.file_id == ts._node.file_id
                                            and loop_cu_child.start_line >= int(ts.region_start_line)
                                            and loop_cu_child.end_line <= int(ts.region_end_line)
                                        ):
                                            # seperate between critical and atomic CUs
                                            if contains_reduction(pet, loop_cu_child):
                                                # split cu lines on reduction, mark surrounding lines as critical
                                                file_idx = loop_cu_child.start_position().split(":")[0]
                                                start_line = int(loop_cu_child.start_position().split(":")[1])
                                                end_line = int(loop_cu_child.end_position().split(":")[1])
                                                critical_lines_range = range(start_line, end_line + 1)
                                                atomic_lines = []
                                                # seperate between critical and atomic lines
                                                for red_var in pet.reduction_vars:
                                                    if line_contained_in_region(
                                                        red_var["reduction_line"],
                                                        loop_cu_child.start_position(),
                                                        loop_cu_child.end_position(),
                                                    ):
                                                        atomic_lines.append(
                                                            int(red_var["reduction_line"].split(":")[1])
                                                        )
                                                critical_lines = [
                                                    e for e in critical_lines_range if e not in atomic_lines
                                                ]
                                                # combine successive critical lines if possible
                                                combined_critical_lines = [
                                                    (e, e) for e in critical_lines
                                                ]  # (start, end)
                                                found_combination = True
                                                while found_combination and len(combined_critical_lines) > 1:
                                                    found_combination = False
                                                    for outer_idx, outer in enumerate(combined_critical_lines):
                                                        for inner_idx, inner in enumerate(combined_critical_lines):
                                                            if inner_idx == outer_idx:
                                                                continue
                                                            if outer[1] + 1 == inner[0]:
                                                                # inner is direct successor of outer
                                                                combined_critical_lines[outer_idx] = (
                                                                    outer[0],
                                                                    inner[1],
                                                                )
                                                                combined_critical_lines.pop(inner_idx)
                                                                found_combination = True
                                                                break
                                                        if found_combination:
                                                            break
                                                # append critical and atomic to ts.atomic_sections/ts.critical_sections
                                                for e in combined_critical_lines:
                                                    ts.critical_sections.append(
                                                        ""
                                                        + str(file_idx)
                                                        + ":"
                                                        + str(e[0])
                                                        + "-"
                                                        + str(file_idx)
                                                        + ":"
                                                        + str(e[1])
                                                    )
                                                for a in atomic_lines:
                                                    ts.atomic_sections.append(
                                                        ""
                                                        + str(file_idx)
                                                        + ":"
                                                        + str(a)
                                                        + "-"
                                                        + str(file_idx)
                                                        + ":"
                                                        + str(a)
                                                    )
                                            else:
                                                # append loop_cu_child to list of critical CUs
                                                found_critical_cus.append(loop_cu_child)
        # CRITICAL SECTIONS
        __identify_atomic_or_critical_sections(pet, ts, found_critical_cus, False)
        # ATOMIC SECTIONS
        __identify_atomic_or_critical_sections(pet, ts, found_atomic_cus, True)
    return suggestions


def __identify_atomic_or_critical_sections(
    pet: PEGraphX, ts: TaskParallelismInfo, found_cus: List[Node], selector: bool
) -> None:
    """Identifies and marks atomic or critical sections.
    :param pet: PET Graph
    :param ts: task suggestion
    :param found_cus: list of previously identified atomic or critical cus.
    :param selector: True: identify atomic sections. False: identify critical sections
    """
    # remove potential duplicates from found cus
    found_cus = list(dict.fromkeys(found_cus))
    # get lists of combinable cus by checking successor relation
    combinations = []
    for cu in found_cus:
        combinations.append([cu])
    found_combination = True
    while found_combination:
        found_combination = False
        for parent_idx in range(0, len(combinations)):
            if found_combination:
                break
            for child_idx in range(0, len(combinations)):
                if found_combination:
                    break
                if parent_idx == child_idx:
                    continue
                if combinations[child_idx][0] in direct_successors(pet, combinations[parent_idx][-1]):
                    combinations[parent_idx] += combinations[child_idx]
                    combinations.pop(child_idx)
                    found_combination = True
    # remove entries from combinations, if they are already covered by another combination
    # occurs, if line numbers are overlapping although CUs are not direct successors of each other.
    removed_entry = True
    while removed_entry:
        removed_entry = False
        for parent_idx in range(0, len(combinations)):
            if removed_entry:
                break
            # check that parent is a single-entry list
            if len(combinations[parent_idx]) != 1:
                continue
            for child_idx in range(0, len(combinations)):
                if removed_entry:
                    break
                if parent_idx == child_idx:
                    continue
                # check if parent is covered by child
                parent = combinations[parent_idx]
                child = combinations[child_idx]
                if line_contained_in_region(
                    parent[0].start_position(), child[0].start_position(), child[-1].end_position()
                ) and line_contained_in_region(
                    parent[-1].end_position(), child[0].start_position(), child[-1].end_position()
                ):
                    combinations.pop(parent_idx)
                    removed_entry = True
    # create a string from the gathered information and append to ts.critical_sections
    for combination_list in combinations:
        section_str = ""
        section_str += combination_list[0].start_position()
        section_str += "-"
        section_str += combination_list[-1].end_position()
        if selector:
            ts.atomic_sections.append(section_str)
        else:
            ts.critical_sections.append(section_str)

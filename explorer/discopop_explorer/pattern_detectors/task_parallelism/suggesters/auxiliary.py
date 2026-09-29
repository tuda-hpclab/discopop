# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import copy
from typing import List, Tuple, Optional, cast, Dict

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.functions.PEGraph.queries.edges import in_edges
from discopop_explorer.pattern_detectors.task_parallelism.classes import (
    TaskParallelismInfo,
    ParallelRegionInfo,
    OmittableCuInfo,
    TPIType,
)
from discopop_explorer.pattern_detectors.task_parallelism.tp_utils import (
    get_parent_of_type,
    task_contained_in_reduction_loop,
)


def suggest_parallel_regions(pet: PEGraphX, suggestions: List[TaskParallelismInfo]) -> List[ParallelRegionInfo]:
    """create suggestions for parallel regions based on suggested tasks.
    Parallel regions are suggested aroung each outer-most function call
    possibly leading to the creation of tasks.
    To obtain these, the child-graph is traversed in reverse,
    starting from each suggested task.
    :param pet: PET graph
    :param suggestions: List[TaskParallelismInfo]
    :return: List[ParallelRegionInfo]"""
    # get task suggestions from suggestions
    task_suggestions = [s for s in suggestions if s.type is TPIType.TASK]
    # start search for each suggested task
    parents: List[Tuple[Node, Optional[Node]]] = []
    for ts in task_suggestions:
        parents += get_parent_of_type(pet, ts._node, NodeType.FUNC, EdgeType.CHILD, False)
    # remove duplicates
    parents = list(dict.fromkeys(parents))
    # get outer-most parents of suggested tasks
    outer_parents: List[Tuple[Node, Optional[Node]]] = []
    # iterate over entries in parents.
    while len(parents) > 0:
        p, last_node = parents.pop(0)
        p_parents = get_parent_of_type(pet, p, NodeType.FUNC, EdgeType.CHILD, False)
        if not p_parents:  # p_parents is empty
            # p is outer
            # get last cu before p
            outer_parents.append((p, last_node))
        else:
            # append p´s parents to queue, filter out entries if already
            # present in outer_parents
            first_elements = [x[0] for x in outer_parents]
            parents += [x for x in p_parents if x[0] not in first_elements]

    # create region suggestions based on detected outer parents
    region_suggestions = []
    for parent, last_node in outer_parents:
        if last_node is None:
            continue
        last_node = last_node
        region_suggestions.append(
            ParallelRegionInfo(parent, TPIType.PARALLELREGION, last_node.start_line, last_node.end_line)
        )
    return region_suggestions


def set_task_contained_lines(suggestions: List[TaskParallelismInfo]) -> List[TaskParallelismInfo]:
    """set region_end_line property of TaskParallelismInfo objects
    in suggestions and return the modified list.
    Regions are determined by checking if a CU contains multiple Tasks or
    Barriers and splitting up the contained source code lines accordingly.
    :param suggestions: List[TaskParallelismInfo]
    :return: List[TaskParallelismInfo]"""
    # group suggestions by parent CU
    output = []
    cu_to_suggestions_map: Dict[str, List[TaskParallelismInfo]] = dict()
    for s in suggestions:
        # fill cu_to_suggestions_map
        if s.node_id in cu_to_suggestions_map:
            cu_to_suggestions_map[s.node_id].append(s)
        else:
            cu_to_suggestions_map[s.node_id] = [s]
    # order suggestions for each CU by first affected line
    for cu in cu_to_suggestions_map:
        sorted_suggestions = cu_to_suggestions_map[cu]
        sorted_suggestions.sort(key=lambda x: x.region_start_line)
        cu_to_suggestions_map[cu] = sorted_suggestions
    # iterate over suggestions. set region_end_line to end of cu or
    # beginning of next suggestion
    for cu in cu_to_suggestions_map:
        for idx, s in enumerate(cu_to_suggestions_map[cu]):
            # check if next element exists
            if idx + 1 < len(cu_to_suggestions_map[cu]):
                # if so, set end to line prior to start of next suggestion
                end = int(cu_to_suggestions_map[cu][idx + 1].region_start_line)
                end = end - 1
                s.region_end_line = str(end)
            else:
                # if not, set end to end of cu
                s.region_end_line = s.end_line[s.end_line.index(":") + 1 :]
            # overwrite entry in cu_to_suggestions_map for s
            cu_to_suggestions_map[cu][idx] = s
    # append suggestions to output
    for cu in cu_to_suggestions_map:
        for s in cu_to_suggestions_map[cu]:
            output.append(s)
    return output


def detect_taskloop_reduction(pet: PEGraphX, suggestions: List[TaskParallelismInfo]) -> List[TaskParallelismInfo]:
    """detect suggested tasks which can and should be replaced by
    taskloop reduction.
    return the modified list of suggestions.
    Idea:   1. check if suggested task inside loop body
            2. check if outer loop is reduction loop
                3. if so, build reduction clause and modify suggested task
    :param pet: PET graph
    :param suggestions: List[TaskParallelismInfo]
    :return: List[TaskParallelismInfo]
    """
    output = []
    # iterate over suggestions
    for s in suggestions:
        # ignore others than tasks
        if s.type is not TPIType.TASK:
            continue
        # check if s contained in reduction loop body
        red_vars_entry, red_loop = task_contained_in_reduction_loop(pet, s)
        if red_vars_entry is None or red_loop is None:
            # s not contained in reduction loop body
            output.append(s)
        else:
            red_vars_entry = red_vars_entry
            red_loop = red_loop
            # s contained in reduction loop body
            # modify task s
            reduction_clause = "reduction("
            reduction_clause += red_vars_entry["operation"] + ":"
            reduction_clause += red_vars_entry["name"].replace(".addr", "")
            reduction_clause += ")"
            s.pragma = ["taskloop", reduction_clause]
            s.type = TPIType.TASKLOOP
            # update pragma line to parent reduction loop
            s.pragma_line = red_loop.start_position()
            # update pragma region
            s.region_start_line = red_loop.start_position()
            s.region_end_line = red_loop.end_position()
            # append modified task to output
            output.append(s)
    return output


def combine_omittable_cus(pet: PEGraphX, suggestions: List[PatternInfo]) -> List[PatternInfo]:
    """execute combination of tasks suggestions with omittable cus.
    Adds modified version of the respective Parent suggestions to the list.
    Returns the modified list of suggestions.
    Omittable CU suggetions are removed from the list.
    Removes duplicates in in/out/in_out dependency lists.
    :param pet: PET graph
    :param suggestions: List [PatternInfo]
    :return: List[PatternInfo]
    """
    omittable_suggestions: List[OmittableCuInfo] = []
    task_suggestions: List[TaskParallelismInfo] = []
    result: List[PatternInfo] = []
    for single_suggestion in suggestions:
        if type(single_suggestion) == OmittableCuInfo:
            omittable_suggestions.append(single_suggestion)
        else:
            if type(single_suggestion) == TaskParallelismInfo:
                try:
                    if single_suggestion.type is TPIType.TASK:
                        task_suggestions.append(single_suggestion)
                    else:
                        result.append(single_suggestion)
                except AttributeError:
                    result.append(single_suggestion)
            else:
                result.append(single_suggestion)

    # remove omittable suggestion if cu is no direct child in the
    # successor graph of a node containing a task suggestion
    useful_omittable_suggestions = []
    for oms in omittable_suggestions:
        in_succ_edges = [(s, t, e) for s, t, e in in_edges(pet, oms._node.id) if e.etype == EdgeType.SUCCESSOR]
        parent_task_nodes = [pet.node_at(e[0]) for e in in_succ_edges if pet.node_at(e[0]).tp_contains_task is True]
        if len(parent_task_nodes) != 0:
            useful_omittable_suggestions.append(oms)
        else:
            # un-mark node as omittable
            oms._node.tp_omittable = False
    omittable_suggestions = useful_omittable_suggestions

    # create copies of original Task suggestion versions
    for omit_s in omittable_suggestions:
        for ts in task_suggestions:
            if omit_s.combine_with_node == ts._node:
                result.append(copy.copy(ts))

    # prepare dict to find target suggestions for combination
    task_suggestions_dict: Dict[Node, List[TaskParallelismInfo]] = dict()
    for ts in task_suggestions:
        if ts._node in task_suggestions_dict:
            task_suggestions_dict[ts._node].append(ts)
        else:
            task_suggestions_dict[ts._node] = [ts]

    for omit_s in omittable_suggestions:
        # process in_out dependencies of omit_s
        # -> lazy, let following statements take care
        for omit_in_out_var in omit_s.in_out_dep:
            omit_s.in_dep.append(omit_in_out_var)
            omit_s.out_dep.append(omit_in_out_var)

        # find target task_suggestion for omit_s, based on in / out dep matches
        omit_target_task_indices = []
        if omit_s.combine_with_node in task_suggestions_dict:
            if len(task_suggestions_dict[omit_s.combine_with_node]) != 1:
                # search for matching in/out dependency pair
                for idx, ts in enumerate(task_suggestions_dict[omit_s.combine_with_node]):
                    intersect = [v for v in omit_s.in_dep if v in ts.out_dep]
                    if len(intersect) == len(omit_s.in_dep):
                        # all in_deps covered
                        omit_target_task_indices.append(idx)
            else:
                omit_target_task_indices = [0]

            for omit_target_task_idx in omit_target_task_indices:
                # note: dependencies of task nodes can contain multiples
                # process out dependencies of omit_s
                for omit_out_var in omit_s.out_dep:
                    if omit_out_var is None:
                        continue
                    task_suggestions_dict[omit_s.combine_with_node][omit_target_task_idx].out_dep.append(omit_out_var)
                    # omit_s.combine_with_node.out_dep.append(omit_out_var)
                # process in dependencies of omit_s
                for omit_in_var in omit_s.in_dep:
                    # note: only dependencies to target node allowed
                    if omit_in_var in task_suggestions_dict[omit_s.combine_with_node][omit_target_task_idx].out_dep:
                        task_suggestions_dict[omit_s.combine_with_node][omit_target_task_idx].out_dep.remove(
                            omit_in_var
                        )
                    # omit_s.combine_with_node.out_dep.remove(omit_in_var)

                # increase size of pragma region if needed
                if ":" not in cast(
                    str,
                    task_suggestions_dict[omit_s.combine_with_node][omit_target_task_idx].region_end_line,
                ):
                    if int(omit_s.end_line[omit_s.end_line.index(":") + 1 :]) > int(
                        cast(
                            str,
                            task_suggestions_dict[omit_s.combine_with_node][omit_target_task_idx].region_end_line,
                        )
                    ):
                        task_suggestions_dict[omit_s.combine_with_node][
                            omit_target_task_idx
                        ].region_end_line = omit_s.end_line
                else:
                    cut_region_end_line = cast(
                        str,
                        task_suggestions_dict[omit_s.combine_with_node][omit_target_task_idx].region_end_line,
                    )
                    cut_region_end_line = cut_region_end_line[cut_region_end_line.index(":") + 1 :]
                    if int(omit_s.end_line[omit_s.end_line.index(":") + 1 :]) > int(cut_region_end_line):
                        task_suggestions_dict[omit_s.combine_with_node][
                            omit_target_task_idx
                        ].region_end_line = omit_s.end_line

    # remove duplicates from dependency lists and append to result
    for key in task_suggestions_dict:
        for ts in task_suggestions_dict[key]:
            # remove duplicates
            ts.in_dep = list(dict.fromkeys(ts.in_dep))
            ts.out_dep = list(dict.fromkeys(ts.out_dep))
            # reset in_out_dep, might have changed due to combination
            if len(ts.in_dep) < len(ts.out_dep):  # just for performance
                ts.in_out_dep = [var for var in ts.in_dep if var in ts.out_dep]
            else:
                ts.in_out_dep = [var for var in ts.out_dep if var in ts.in_dep]
            ts.in_out_dep = list(dict.fromkeys(ts.in_out_dep))
            result.append(ts)

    return result

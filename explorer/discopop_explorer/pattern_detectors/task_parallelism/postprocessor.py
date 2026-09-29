# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, cast, Dict, Optional, Tuple

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.pattern_detectors.task_parallelism.classes import (
    TaskParallelismInfo,
    ParallelRegionInfo,
    TPIType,
)


def group_task_suggestions(pet: PEGraphX, suggestions: List[PatternInfo]) -> List[PatternInfo]:
    """Group task and taskwait suggestions by traversing the successor graph and marking.
    Starting from each taskwait suggestion, the successor graph is traversed in reverse order.
    Visited task suggestions are marked using it's id. The traversal stops if either another taskwait suggestion or the
    end of the graph has been reached.
    After marking, task suggestions which are marked with more than one id denote the presence of a non-trivial
    task group. In a postprocessing step, such tasks are used to combine multiple task groups into a single group.
    The intuition of the result is simple: if any task suggestion within a task group is implemented by the user,
    it is recommended to implement all related suggestions, as they belong together and,
    e.g. in case of missing taskwaits, might influence the correctness of the resulting program.
    :param pet: PET Graph
    :param suggestions: Found suggestions
    :return: Updated suggestions"""
    task_suggestions = [s for s in [e for e in suggestions if type(e) == TaskParallelismInfo] if s.type is TPIType.TASK]
    taskwait_suggestions = [
        s for s in [e for e in suggestions if type(e) == TaskParallelismInfo] if s.type is TPIType.TASKWAIT
    ]
    # mark preceeding suggestions for each taskwait suggestion
    for task_group_id, tws in enumerate(taskwait_suggestions):
        # mark taskwait suggestion with own id
        tws.task_group.append(task_group_id)
        relatives: List[Node] = [tws._node]
        queue: List[Node] = [pet.node_at(in_e[0]) for in_e in in_edges(pet, tws._node.id, EdgeType.SUCCESSOR)]
        while len(queue) > 0:
            cur = queue.pop(0)
            if cur.tp_contains_taskwait:
                continue
            relatives.append(cur)
            for in_edge in in_edges(pet, cur.id, EdgeType.SUCCESSOR):
                if pet.node_at(in_edge[0]) not in relatives + queue:
                    queue.append(pet.node_at(in_edge[0]))
            for out_edge in out_edges(pet, cur.id, EdgeType.SUCCESSOR):
                if pet.node_at(out_edge[1]) not in relatives + queue:
                    queue.append(pet.node_at(out_edge[1]))

        # mark intersection of relatives and task_suggestions
        for intersect in [sug for sug in task_suggestions if sug._node in relatives]:
            intersect.task_group.append(task_group_id)
    # combine groups by replacing taskgroup ids (higher replaced by lower id)
    # get replacements to be done
    replacements: Dict[int, int] = dict()  # [target_id :  replacement_id)]
    for ts in task_suggestions:
        if len(ts.task_group) <= 1:
            continue
        # multiple task_group entries. get smallest id as replacement, add others as targets
        replacement_id = min(ts.task_group)
        for target_id in [tid for tid in ts.task_group]:
            # will lead to identity replacements, required for later replacement
            replacements[target_id] = replacement_id
    # refine replacement list (check for and simplify transitivities)
    modification_found = True
    while modification_found:
        modification_found = False
        for target_id in replacements:
            replacement_id = replacements[target_id]
            if replacement_id == target_id:
                # necessary for completeness of later replacement
                continue
            if replacement_id in replacements:
                # transitive replacement found, simplify
                if replacements[target_id] != replacements[replacement_id]:
                    replacements[target_id] = replacements[replacement_id]
                    modification_found = True
                    break
    # execute replacement
    for sug in task_suggestions + taskwait_suggestions:
        sug.task_group = [replacements[tg_elem] if tg_elem in replacements else tg_elem for tg_elem in sug.task_group]
        # validate and combine results
        # valid, if all entries in sug.task_group are equal. Replace by single entry if valid.
        value: Optional[int] = None
        for tg_elem in sug.task_group:
            if value is None:
                value = tg_elem
                continue
            if tg_elem != value:
                # not valid, raise exception
                raise ValueError(
                    "Task Group creation led to erroneous results: NodeId:",
                    sug._node.id,
                    "  Task Group: ",
                    sug.task_group,
                )
        # valid, overwrite sug.task_group if value is not None
        if value is not None:
            sug.task_group = [value]
    return suggestions


def sort_output(suggestions: List[PatternInfo]) -> List[PatternInfo]:
    """orders the list of suggestions by the respective properties:
    order by: file-id, then line-number (descending).
    Returns the sorted list of suggestions
    :param suggestions: List[PatternInfo]
    :return: List[PatternInfo]
    """
    sorted_suggestions = []
    tmp_dict: Dict[str, List[Tuple[str, PatternInfo]]] = dict()
    for sug in suggestions:
        if isinstance(sug, (ParallelRegionInfo, TaskParallelismInfo)):
            # get start_line and file_id for sug
            if ":" not in sug.region_start_line:
                start_line = sug.region_start_line
                file_id = sug.start_line[0 : sug.start_line.index(":")]
            else:
                start_line = sug.region_start_line
                file_id = start_line[0 : start_line.index(":")]
                start_line = start_line[start_line.index(":") + 1 :]
            # split suggestions by file-id
            if file_id not in tmp_dict:
                tmp_dict[file_id] = []
            tmp_dict[file_id].append((start_line, sug))
        else:
            continue
    # sort suggestions by line-number (descending)
    for key in tmp_dict:
        sorted_list = cast(
            List[Tuple[str, PatternInfo]],
            sorted(tmp_dict[key], key=lambda x: int(x[0]), reverse=True),
        )
        sorted_list_pruned = cast(List[PatternInfo], [elem[1] for elem in sorted_list])
        sorted_suggestions += sorted_list_pruned
    return sorted_suggestions

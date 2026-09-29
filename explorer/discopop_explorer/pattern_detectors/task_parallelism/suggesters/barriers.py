# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, cast, Tuple, Any

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.traversal.successors import direct_successors
from discopop_explorer.pattern_detectors.task_parallelism.classes import (
    ParallelRegionInfo,
    OmittableCuInfo,
    TaskParallelismInfo,
    TPIType,
)
from discopop_explorer.pattern_detectors.task_parallelism.tp_utils import (
    check_reachability,
    line_contained_in_region,
    get_predecessor_nodes,
)


def detect_barrier_suggestions(pet: PEGraphX, suggestions: List[PatternInfo]) -> List[PatternInfo]:
    """detect barriers which have not been detected by __detect_mw_types,
    especially marks WORKER as BARRIER_WORKER if it has depencies to two or
    more CUs which are contained in a path to a CU containing at least one
    suggested Task.
    If omittable CUs are found in the process, they will be marked in the
    pet graph and an intermediate entry in suggestions will be created.
    function executed is repeated until convergence.
    steps:
    1.) mark node as Barrier, if dependences only to task-containing-paths
    :param pet: PET Graph
    :param suggestions: List[TaskParallelismInfo]
    :return List[PatternInfo]
    """
    # split suggestions into task and taskwait suggestions
    taskwait_suggestions: List[TaskParallelismInfo] = []
    task_suggestions: List[TaskParallelismInfo] = []
    omittable_suggestions: List[PatternInfo] = []
    __split_suggestions(suggestions, taskwait_suggestions, task_suggestions, omittable_suggestions)

    for s in task_suggestions:
        s._node.tp_contains_task = True
    for s in taskwait_suggestions:
        s._node.tp_contains_taskwait = True
    task_nodes = [t._node for t in task_suggestions]
    barrier_nodes = [t._node for t in taskwait_suggestions]
    omittable_nodes: List[Tuple[Node, List[Node]]] = []

    transformation_happened = True
    # let run until convergence
    queue = list(all_nodes(pet))
    while transformation_happened or len(queue) > 0:
        transformation_happened = False
        v = queue.pop(0)
        # check step 1
        out_dep_edges = [
            (s, t, e) for s, t, e in out_edges(pet, v.id) if e.etype == EdgeType.DATA and pet.node_at(t) != v
        ]
        # ignore cyclic dependencies on the same variable
        to_remove = []
        for dep_edge in out_dep_edges:
            targets_cyclic_dep_edges = [
                (s, t, e)
                for s, t, e in out_edges(pet, dep_edge[1])
                if e.etype == EdgeType.DATA and t == dep_edge[0] and e.var_name == dep_edge[2].var_name
            ]
            if len(targets_cyclic_dep_edges) != 0:
                to_remove.append(dep_edge)
        for e in to_remove:
            out_dep_edges.remove(e)

        v_first_line = v.start_position()
        v_first_line = LineID(v_first_line[v_first_line.index(":") + 1 :])

        task_count, barrier_count, omittable_count, normal_count = __count_adjacent_nodes(
            pet, suggestions, out_dep_edges, task_nodes, barrier_nodes, omittable_nodes
        )
        if task_count == 1 and barrier_count == 0:
            if not v.tp_omittable:
                # actual change
                v.tp_omittable = True
                combine_with_node_list = [pet.node_at(e[1]) for e in out_dep_edges if pet.node_at(e[1]) in task_nodes]
                if len(combine_with_node_list) < 1:
                    raise ValueError("length combine_with_node < 1!")
                combine_with_node = combine_with_node_list[0]
                omittable_nodes.append((v, [combine_with_node]))
                suggestions.append(OmittableCuInfo(v, combine_with_node))
                transformation_happened = True
        elif barrier_count != 0 and task_count != 0:
            # check if child barrier(s) cover each child task
            child_barriers = [e[1] for e in out_dep_edges if pet.node_at(e[1]).tp_contains_taskwait is True]
            child_tasks = [pet.node_at(e[1]) for e in out_dep_edges if pet.node_at(e[1]).tp_contains_task is True]
            uncovered_task_exists = False
            for ct in child_tasks:
                ct_start_line = ct.start_position()
                ct_start_line = LineID(ct_start_line[ct_start_line.index(":") + 1 :])
                ct_end_line = ct.end_position()
                ct_end_line = LineID(ct_end_line[ct_end_line.index(":") + 1 :])
                # check if ct covered by a barrier
                for cb_id in child_barriers:
                    cb = pet.node_at(cb_id)
                    cb_start_line = cb.start_position()
                    cb_start_line = LineID(cb_start_line[cb_start_line.index(":") + 1 :])
                    cb_end_line = cb.end_position()
                    cb_end_line = LineID(cb_end_line[cb_end_line.index(":") + 1 :])
                    if not (cb_start_line > ct_start_line and cb_end_line > ct_end_line):
                        uncovered_task_exists = True
            if uncovered_task_exists:
                # suggest barrier
                if v.tp_contains_taskwait is False:
                    # actual change
                    v.tp_contains_taskwait = True
                    barrier_nodes.append(v)
                    transformation_happened = True
                    tmp_suggestion = TaskParallelismInfo(v, TPIType.TASKWAIT, ["taskwait"], v_first_line, [], [], [])
                    suggestions.append(tmp_suggestion)
            else:
                # no barrier needed
                pass
        elif omittable_count == 0 and task_count > 1:  # connected to at least two distinct task nodes
            if v.tp_contains_taskwait is False:
                # actual change
                v.tp_contains_taskwait = True
                barrier_nodes.append(v)
                transformation_happened = True
                tmp_suggestion = TaskParallelismInfo(v, TPIType.TASKWAIT, ["taskwait"], v_first_line, [], [], [])
                suggestions.append(tmp_suggestion)
        if omittable_count == 1 and v.tp_contains_task is False and v.tp_contains_taskwait is False:
            # omittable node appended to prior omittable node
            # get parent task
            #            parent_task: Optional[CUNode] = None
            for e in out_dep_edges:
                if pet.node_at(e[1]).tp_omittable is True:
                    # if tp_omittable is set, a omittable_suggestion has to exists.
                    # find this suggestion and extract combine_with_node
                    found_cwn = False
                    for tmp_omit, tmp_cwn in omittable_nodes:
                        if pet.node_at(e[1]) == tmp_omit:
                            if len(tmp_cwn) == 1:
                                parent_task = tmp_cwn[0]
                                found_cwn = True

                    if not found_cwn:
                        raise Exception("No parent task for omittable node found!")
            violation = __check_dependences_and_predecessors(pet, out_dep_edges, parent_task, v)
            # suggest omittable cu if no violation occured
            if not violation:
                if v.tp_omittable is False:
                    # actual change
                    v.tp_omittable = True
                    omittable_nodes.append((v, [parent_task]))
                    suggestions.append(OmittableCuInfo(v, parent_task))
                    transformation_happened = True

        # append neighbors of modified node to queue
        if transformation_happened:
            in_dep_edges = [
                (s, t, e) for s, t, e in in_edges(pet, v.id) if e.etype == EdgeType.DATA and pet.node_at(s) != v
            ]
            for e in out_dep_edges:
                queue.append(pet.node_at(e[1]))
            for e in in_dep_edges:
                queue.append(pet.node_at(e[0]))
            queue = list(dict.fromkeys(queue))

    return suggestions


def __count_adjacent_nodes(
    pet: PEGraphX,
    suggestions: List[PatternInfo],
    out_dep_edges: List[Tuple[Any, Any, Any]],
    task_nodes: List[Node],
    barrier_nodes: List[Node],
    omittable_nodes: List[Tuple[Node, List[Node]]],
) -> Tuple[int, int, int, int]:
    """Checks the types of nodes pointed to by out_dep_edges and increments the respective counters.
    :param pet: PET Graph
    :param suggestions: List[TaskParallelismInfo]
    :param out_dep_edges: list of outgoing edges
    :param task_nodes: list of cu nodes containing task suggestions
    :param barrier_nodes: list of cu nodes containing barrier suggestions
    :param omittable_nodes: list of cu nodes containing omittable suggestions
    :return: Tuple consisting of (task_count, barrier_count, omittable_count, normal_count)
    """
    task_count = 0
    barrier_count = 0
    omittable_count = 0
    normal_count = 0
    task_buffer = []
    barrier_buffer = []
    omittable_parent_buffer = []
    for e in out_dep_edges:
        if pet.node_at(e[1]) in task_nodes:
            # only count distinct tasks
            if pet.node_at(e[1]) not in task_buffer:
                task_buffer.append(pet.node_at(e[1]))
                task_count += 1
            else:
                pass
        elif pet.node_at(e[1]) in barrier_nodes:
            # only count distinct barriers
            if pet.node_at(e[1]) not in barrier_buffer:
                barrier_buffer.append(pet.node_at(e[1]))
                barrier_count += 1
            else:
                pass
        elif pet.node_at(e[1]) in [tmp[0] for tmp in omittable_nodes]:
            # treat omittable cus like their parent tasks
            tmp_omit_suggestions: List[OmittableCuInfo] = cast(
                List[OmittableCuInfo], [s for s in suggestions if type(s) == OmittableCuInfo]
            )
            parent_task = [tos for tos in tmp_omit_suggestions if tos._node == pet.node_at(e[1])][0].combine_with_node
            if parent_task.id not in omittable_parent_buffer:
                omittable_parent_buffer.append(parent_task.id)
                omittable_count += 1
            else:
                pass
        else:
            normal_count += 1
    return task_count, barrier_count, omittable_count, normal_count


def __check_dependences_and_predecessors(
    pet: PEGraphX, out_dep_edges: List[Tuple[Any, Any, Any]], parent_task: Node, cur_cu: Node
) -> bool:
    """Checks if only dependences to self, parent omittable node or path to target task exists.
    Checks if node is a direct successor of an omittable node or a task node.
    :param pet: PET Graph
    :param out_dep_edges: list of outgoing edges
    :param parent_task: parent cu of cur_cu
    :param cur_cu: current cu node
    :return True, if a violation has been found. False, otherwise.
    """
    violation = False
    # check if only dependencies to self, parent omittable node or path to target task exists
    for e in out_dep_edges:
        if pet.node_at(e[1]) == cur_cu:
            continue
        elif pet.node_at(e[1]).tp_omittable is True:
            continue
        elif check_reachability(pet, parent_task, cur_cu, [EdgeType.DATA]):
            continue
        else:
            violation = True
    # check if node is a direct successor of an omittable node or a task node
    in_succ_edges = [(s, t, e) for (s, t, e) in in_edges(pet, cur_cu.id) if e.etype == EdgeType.SUCCESSOR]
    is_successor = False
    for e in in_succ_edges:
        if pet.node_at(e[0]).tp_omittable is True:
            is_successor = True
        elif pet.node_at(e[0]).tp_contains_task is True:
            is_successor = True
    if not is_successor:
        violation = True
    return violation


def __split_suggestions(
    suggestions: List[PatternInfo],
    taskwait_suggestions: List[TaskParallelismInfo],
    task_suggestions: List[TaskParallelismInfo],
    omittable_suggestions: List[PatternInfo],
) -> None:
    """Split suggestions into taskwait, task and omittable suggestions.
    :param suggestions: list of suggestions to be split
    :param taskwait_suggestions: list to store taskwait suggestions
    :param task_suggestions: list to store task suggestions
    :param omittable_suggestions: list to store omittable suggestions"""
    for single_suggestion in suggestions:
        if type(single_suggestion) == ParallelRegionInfo:
            continue
        elif type(single_suggestion) == OmittableCuInfo:
            omittable_suggestions.append(single_suggestion)
        elif type(single_suggestion) == TaskParallelismInfo:
            if single_suggestion.type is TPIType.TASKWAIT:
                taskwait_suggestions.append(single_suggestion)
            elif single_suggestion.type is TPIType.TASK:
                task_suggestions.append(single_suggestion)
        else:
            raise TypeError("Unknown Type: ", type(single_suggestion))


def suggest_barriers_for_uncovered_tasks_before_return(
    pet: PEGraphX, suggestions: List[PatternInfo]
) -> List[PatternInfo]:
    """enforces taskwait or similar pragmas before return statements to ensure, that no unfinished tasks exist
    when the parent function returns.
    :param pet: PET graph
    :param suggestions; List[PatternInfo]
    :return: List[PatternInfo]"""
    # iterate over task suggestions
    for suggestion in suggestions:
        if type(suggestion) != TaskParallelismInfo:
            continue
        if suggestion.type is not TPIType.TASK:
            continue
        # if task is covered by a parallel region, ignore it due to the present, implicit barrier
        covered_by_parallel_region = False
        for tmp in suggestions:
            if type(tmp) == ParallelRegionInfo:
                if line_contained_in_region(suggestion.start_line, tmp.region_start_line, tmp.region_end_line):
                    covered_by_parallel_region = True
                    break
        if covered_by_parallel_region:
            continue
        # check, if barrier in successor - path between task and return (same cu -> no barrier contained)
        queue = [suggestion._node]
        visited = []
        targets = []
        while len(queue) != 0:
            current_node = queue.pop()
            visited.append(current_node)
            if current_node.tp_contains_taskwait:
                # stop search on this path
                continue
            # check if returnInstructionCount > 0
            if isinstance(current_node, CUNode) and current_node.return_instructions_count > 0:
                # taskwait missing -> add current node to targets
                targets.append(current_node)
                continue
            # append direct successors to targets, if not in visited
            successors = direct_successors(pet, current_node)
            successors = [ds for ds in successors if ds not in visited]
            queue = queue + successors
        # suggest taskwait prior to return if needed
        for cu in targets:
            # actual change
            cu.tp_contains_taskwait = True
            pragma_line = cu.end_position()  # since return has to be the last statement in a CU
            pragma_line = LineID(pragma_line[pragma_line.index(":") + 1 :])
            tmp_suggestion = TaskParallelismInfo(cu, TPIType.TASKWAIT, ["taskwait"], pragma_line, [], [], [])
            print(
                "TPDet:suggest_barriers_for_uncovered_tasks_before_return: added taskwait suggestion at line: ",
                cu.end_position(),
            )
            suggestions.append(tmp_suggestion)
    return suggestions


def validate_barriers(pet: PEGraphX, suggestions: List[PatternInfo]) -> List[PatternInfo]:
    """Checks if >= 2 dependencies exist from same successor path or
    node that contains the barrier is of type loop.
    Eliminate those barrier suggestions that violate this requirement.
    A successor path is represented by a list of nodes reachable by traversing
    the successor edges inside a single function in reverse direction.
    Note, that nodes with multiple outgoing successor edges
    (multiple control flow options) lead to a separation of the created
    successor paths to support the desired behavior.
    :param pet: PET graph
    :param suggestions: List[PatternInfo]
    :return: List[PatternInfo]
    """
    barrier_suggestions: List[TaskParallelismInfo] = []
    result: List[PatternInfo] = []
    for single_suggestion in suggestions:
        if type(single_suggestion) == TaskParallelismInfo:
            try:
                if single_suggestion.type is TPIType.TASKWAIT:
                    barrier_suggestions.append(single_suggestion)
                else:
                    result.append(single_suggestion)
            except AttributeError:
                result.append(single_suggestion)
        else:
            result.append(single_suggestion)

    for bs in barrier_suggestions:
        # check if type of bs node is loop and accept the suggestion if so
        # reason: if task is spawned inside a loop, paths are irrelevant
        if bs._node.type == NodeType.LOOP:
            result.append(bs)
            continue

        # create "path lists" for each incoming successor edge
        in_succ_edges = [
            (s, t, e)
            for s, t, e in in_edges(pet, bs._node.id)
            if e.etype == EdgeType.SUCCESSOR and pet.node_at(s) != bs._node
        ]
        predecessors_dict = dict()
        for e in in_succ_edges:
            visited_nodes: List[Node] = []
            tmp, visited_nodes = get_predecessor_nodes(pet, pet.node_at(e[0]), visited_nodes)
            predecessors_dict[e] = tmp
        # iterate over outgoing dependence edges and increase dependence counts
        # for those paths that contain the dependence target CU
        out_dep_edges = [
            (s, t, e)
            for s, t, e in out_edges(pet, bs._node.id)
            if e.etype == EdgeType.DATA and pet.node_at(t) != bs._node
        ]
        dependence_count_dict = dict()

        for key in predecessors_dict:
            dependence_count_dict[key] = 0

        for key in predecessors_dict:
            for e in out_dep_edges:
                if pet.node_at(e[1]) in predecessors_dict[key]:
                    dependence_count_dict[key] += 1

        # if validated, append bs to result
        validation_successful = False
        for key in dependence_count_dict:
            if dependence_count_dict[key] > 1:
                result.append(bs)
                validation_successful = True
                break
        # if not validated, unmark node as containing a taskwait in the graph
        if not validation_successful:
            bs._node.tp_contains_taskwait = False

    return result


def suggest_missing_barriers_for_global_vars(pet: PEGraphX, suggestions: List[PatternInfo]) -> List[PatternInfo]:
    """Suggests a barrier if a node is a successor of a task CU
    which is not covered by an existing barrier and the set of global variables
    of the CU and the task are overlapping
    (i.e. both CUs access common global variables).
    If the cu which would be suggested as a barrier contains a Task suggestion
    already, ignore the barrier suggestion
    (reason: false positives due to copying of global / local variables in preprocessor).
    :param pet: PET graph
    :param suggestions: List[PatternInfo]
    :return: List[PatternInfo]
    """
    # split suggestions into task and taskwait suggestions
    taskwait_suggestions = []
    task_suggestions = []
    for single_suggestion in suggestions:
        if type(single_suggestion) == ParallelRegionInfo or type(single_suggestion) == OmittableCuInfo:
            continue
        if type(single_suggestion) == TaskParallelismInfo:
            if single_suggestion.type is TPIType.TASKWAIT:
                taskwait_suggestions.append(single_suggestion)
            elif single_suggestion.type is TPIType.TASK:
                task_suggestions.append(single_suggestion)
        else:
            raise TypeError("Unsupported Type: ", type(single_suggestion))

    # iterate over task suggestions
    for task_sug in task_suggestions:
        visited_nodes = [task_sug._node]
        out_succ_edges = [
            (s, t, e)
            for s, t, e in out_edges(pet, task_sug._node.id)
            if e.etype == EdgeType.SUCCESSOR and pet.node_at(t) != task_sug._node
        ]
        queue = out_succ_edges
        # iterate over queued successor-edges
        while len(queue) > 0:
            succ_edge = queue.pop()
            if not pet.node_at(succ_edge[1]) in visited_nodes:
                visited_nodes.append(pet.node_at(succ_edge[1]))
            else:
                continue
            # if barrier is encountered, stop
            if pet.node_at(succ_edge[1]).tp_contains_taskwait is True:
                continue
            # if edge.target has common global variable with task
            succ = pet.node_at(succ_edge[1])
            common_vars = [
                var
                for var in (succ.global_vars if isinstance(succ, CUNode) else [])
                if var in cast(CUNode, task_sug._node).global_vars
            ]
            if len(common_vars) > 0:
                # if cu is a task suggestion, continue
                if pet.node_at(succ_edge[1]).tp_contains_task is True:
                    continue
                # check if any element of common vars is not contained in task_sug.out_dep
                if len([v for v in task_sug.out_dep if v not in [e.name for e in common_vars]]) > 0:
                    # suggest taskwait
                    if pet.node_at(succ_edge[1]).tp_contains_taskwait is False:
                        # actual change
                        pet.node_at(succ_edge[1]).tp_contains_taskwait = True
                        first_line = pet.node_at(succ_edge[1]).start_position()
                        first_line = LineID(first_line[first_line.index(":") + 1 :])
                        tmp_suggestion = TaskParallelismInfo(
                            pet.node_at(succ_edge[1]),
                            TPIType.TASKWAIT,
                            ["taskwait"],
                            first_line,
                            [],
                            [],
                            [],
                        )
                        suggestions.append(tmp_suggestion)
                    continue
            # append current nodes outgoing successor edges to queue
            target_out_succ_edges = [
                (s, t, e)
                for s, t, e in out_edges(pet, pet.node_at(succ_edge[1]).id)
                if e.etype == EdgeType.SUCCESSOR and pet.node_at(t) != pet.node_at(succ_edge[1])
            ]
            queue = list(dict.fromkeys(queue + target_out_succ_edges))
    return suggestions

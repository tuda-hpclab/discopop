# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import subprocess
from typing import Union, cast, Dict, List, Set, Tuple, Optional, Any

from lxml import objectify  # type: ignore

from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.DummyNode import DummyNode
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.enums.MWType import MWType
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.traversal.children import direct_children_or_called_nodes
from discopop_explorer.pattern_detectors.task_parallelism.classes import Task, TaskParallelismInfo
from discopop_explorer.utils import depends

__workloadThreshold = 10000
__minParallelism = 3
__forks: Set[Task] = set()
__global_llvm_cxxfilt_path: str = ""
demangling_cache: Dict[str, str] = dict()


def demangle(mangled_name: str) -> str:
    """Demangles the given mangled function name and returns the resulting string after demangling.
    :param mangled_name: mangled function name
    :return: demangled function name and type information"""
    global demangling_cache
    global __global_llvm_cxxfilt_path
    if mangled_name in demangling_cache:
        return demangling_cache[mangled_name]
    if __global_llvm_cxxfilt_path == "None":
        # set default llvm-cxxfilt executable
        llvm_cxxfilt_path = "llvm-cxxfilt"
    else:
        llvm_cxxfilt_path = __global_llvm_cxxfilt_path
    try:
        process = subprocess.Popen([llvm_cxxfilt_path, mangled_name], stdout=subprocess.PIPE)
        process.wait()
        if process.stdout is not None:
            out_bytes = process.stdout.readline()
            out = out_bytes.decode("UTF-8")
            out = out.replace("\n", "")
            demangling_cache[mangled_name] = out
            return str(out)
    except FileNotFoundError:
        raise ValueError(
            "Executable '" + llvm_cxxfilt_path + "' not found." + " Check or supply --llvm-cxxfilt-path parameter."
        )
    raise ValueError("Demangling of " + mangled_name + " not possible!")


def line_contained_in_region(test_line: str, start_line: str, end_line: str) -> bool:
    """check if test_line is contained in [startLine, endLine].
    Return True if so. False else.
    :param test_line: <fileID>:<line>
    :param start_line: <fileID>:<line>
    :param end_line: <fileID>:<line>
    :return: bool
    """
    test_line_file_id = int(test_line.split(":")[0])
    test_line_line = int(test_line.split(":")[1])
    start_line_file_id = int(start_line.split(":")[0])
    start_line_line = int(start_line.split(":")[1])
    end_line_file_id = int(end_line.split(":")[0])
    end_line_line = int(end_line.split(":")[1])
    if (
        test_line_file_id == start_line_file_id == end_line_file_id
        and start_line_line <= test_line_line <= end_line_line
    ):
        return True
    return False


def get_parent_of_type(
    pet: PEGraphX, node: Node, parent_type: NodeType, edge_type: EdgeType, only_first: bool
) -> List[Tuple[Node, Optional[Node]]]:
    """return parent cu nodes and the last node of the path to them as a tuple
    for the given node with type parent_type
    accessible via edges of type edge_type.
    :param pet: PET graph
    :param node: CUNode, root for the search
    :param parent_type: NodeType, type of target node
    :param edge_type: EdgeType, type of usable edges
    :param only_first: Bool, if true, return only first parent.
        Else, return first parent for each incoming edge of node.
    :return: [(CUNode, CUNode)]"""
    visited = []
    queue: List[Tuple[Node, Optional[Node]]] = [(node, None)]
    res: List[Tuple[Node, Optional[Node]]] = []
    while len(queue) > 0:
        tmp = queue.pop(0)
        cur_node, last_node = tmp
        last_node = cur_node
        visited.append(cur_node)
        tmp_list = [
            (s, t, e)
            for s, t, e in in_edges(pet, cur_node.id)
            if pet.node_at(s) not in visited and e.etype == edge_type
        ]
        for e in tmp_list:
            if pet.node_at(e[0]).type == parent_type:
                if only_first is True:
                    return [(pet.node_at(e[0]), last_node)]
                else:
                    res.append((pet.node_at(e[0]), last_node))
                    visited.append(pet.node_at(e[0]))
            else:
                if pet.node_at(e[0]) not in visited:
                    queue.append((pet.node_at(e[0]), last_node))
    return res


def get_cus_inside_function(pet: PEGraphX, function_cu: Node) -> List[Node]:
    """Returns cus contained in function-body as a list.
    :param pet: PET Graph
    :param function_cu: target function node
    :return: List[CUNode]"""
    queue: List[Node] = [function_cu]
    result_list: List[Node] = []
    while len(queue) > 0:
        cur_cu = queue.pop(0)
        if cur_cu not in result_list:
            result_list.append(cur_cu)
        # append children to queue
        for e in out_edges(pet, cur_cu.id, [EdgeType.CHILD]):
            queue.append(pet.node_at(e[1]))
    return result_list


def check_reachability(pet: PEGraphX, target: Node, source: Node, edge_types: List[EdgeType]) -> bool:
    """check if target is reachable from source via edges of types edge_type.
    :param pet: PET graph
    :param source: CUNode
    :param target: CUNode
    :param edge_types: List[EdgeType]
    :return: Boolean"""
    if source == target:
        return True
    visited: List[str] = []
    queue = [target]
    while len(queue) > 0:
        cur_node = queue.pop(0)
        visited.append(cur_node.id)
        tmp_list = [(s, t, e) for s, t, e in in_edges(pet, cur_node.id) if s not in visited and e.etype in edge_types]
        for e in tmp_list:
            if pet.node_at(e[0]) == source:
                return True
            else:
                if e[0] not in visited:
                    queue.append(pet.node_at(e[0]))
    return False


def get_predecessor_nodes(pet: PEGraphX, root: Node, visited_nodes: List[Node]) -> Tuple[List[Node], List[Node]]:
    """return a list of reachable predecessor nodes.
    generate list recursively.
    stop recursion if a node of type "function" is found or root is a barrier
    (predecessing barrier of the original root node, further predecessors are
    already covered by this barrier and thus can be ignored).
    :param pet: PET Graph
    :param root: root node of the search
    :param visited_nodes: list of visited nodes
    :return: Tuple[[predecessor nodes], [visited nodes]]"""
    result = [root]
    visited_nodes.append(root)
    if isinstance(root, FunctionNode) or root.tp_contains_taskwait is True:
        # root of type "function" or root is a barrier
        return result, visited_nodes
    in_succ_edges = [
        (s, t, e)
        for s, t, e in in_edges(pet, root.id)
        if e.etype == EdgeType.SUCCESSOR and pet.node_at(s) != root and pet.node_at(s) not in visited_nodes
    ]
    for e in in_succ_edges:
        tmp, visited_nodes = get_predecessor_nodes(pet, pet.node_at(e[0]), visited_nodes)
        result += tmp
    return result, visited_nodes


def check_neighbours(first: Task, second: Task) -> bool:
    """Checks if second task immediately follows first task

    :param first: predecessor task
    :param second: successor task
    :return: true if second task immediately follows first task
    """
    fel = int(first.end_line.split(":")[1])
    ssl = int(second.start_line.split(":")[1])
    return fel == ssl or fel + 1 == ssl or fel + 2 == ssl


# NOTE: left, as it may become relevant in the near future
# We decided to omit the information that computes the workload and the relevant codes. For large programs (e.g., ffmpeg), the generated Data.xml file becomes very large. However, we keep the code here because we would like to integrate a hotspot detection algorithm (TODO: Bertin) with the parallelism discovery. Then, we need to retrieve the information to decide which code sections (loops or functions) are worth parallelizing.
# def merge_tasks(pet: PETGraphX, task: Task):
#    """Merges the tasks into having required workload.
#
#    :param pet: PET graph
#    :param task: task node
#    """
#    for i in range(len(task.child_tasks)):
#        child_task: Task = task.child_tasks[i]
#        if child_task.workload < __workloadThreshold:
#            if i > 0:
#                pred: Task = task.child_tasks[i - 1]
#                if check_neighbours(pred, child_task):
#                    pred.aggregate(child_task)
#                    pred.child_tasks.remove(child_task)
#                    merge_tasks(pet, task)
#                    return
#            if i + 1 < len(task.child_tasks) - 1:
#                succ: Task = task.child_tasks[i + 1]
#                if check_neighbours(child_task, succ):
#                    child_task.aggregate(succ)
#                    task.child_tasks.remove(succ)
#                    merge_tasks(pet, task)
#                    return
#            task.child_tasks.remove(child_task)
#            merge_tasks(pet, task)
#            return
#
#    if task.child_tasks and len(task.child_tasks) < __minParallelism:
#        max_workload_task = max(task.child_tasks, key=lambda t: t.workload)
#        task.child_tasks.extend(max_workload_task.child_tasks)
#        task.child_tasks.remove(max_workload_task)
#        merge_tasks(pet, task)
#        return
#
#    for child in task.child_tasks:
#        if child.nodes[0].type == NodeType.LOOP:
#            pass


def create_task_tree(pet: PEGraphX, root: Node) -> None:
    """generates task tree data from root node

    :param pet: PET graph
    :param root: root node
    """
    root_task = Task(pet, root)
    __forks.add(root_task)
    create_task_tree_helper(pet, root, root_task, [])


def create_task_tree_helper(pet: PEGraphX, current: Node, root: Task, visited_func: List[Node]) -> None:
    """generates task tree data recursively

    :param pet: PET graph
    :param current: current vertex to process
    :param root: root task for subtree
    :param visited_func: visited function nodes
    """
    if isinstance(current, FunctionNode):
        if current in visited_func:
            return
        else:
            visited_func.append(current)

    for child in direct_children_or_called_nodes(pet, current):
        mw_type = child.mw_type

        if mw_type in [MWType.BARRIER, MWType.BARRIER_WORKER, MWType.WORKER]:
            task = Task(pet, child)
            root.child_tasks.append(task)
            create_task_tree_helper(pet, child, task, visited_func)
        elif mw_type == MWType.FORK and not child.start_position().endswith("16383"):
            task = Task(pet, child)
            __forks.add(task)
            create_task_tree_helper(pet, child, task, visited_func)
        else:
            create_task_tree_helper(pet, child, root, visited_func)


def recursive_function_call_contained_in_worker_cu(function_call_string: str, worker_cus: List[Node]) -> Node:
    """check if submitted function call is contained in at least one WORKER cu.
    Returns the vertex identifier of the containing cu.
    If no cu contains the function call, None is returned.
    Note: The Strings stored in recursiveFunctionCalls might contain multiple function calls at once.
          in order to apply this function correctly, make sure to split Strings in advance and supply
          one call at a time.
    :param function_call_string: String representation of the recursive function call to be checked
            Ex.: fib 7:35,  (might contain ,)
    :param worker_cus: List of vertices
    :return: CUNode
    """
    # remove , and whitespaces at start / end
    function_call_string = function_call_string.replace(",", "")
    while function_call_string.startswith(" "):
        function_call_string = function_call_string[1:]
    while function_call_string.endswith(" "):
        function_call_string = function_call_string[:-1]
    # function_call_string looks now like like: 'fib 7:52'

    # split String into function_name. file_id and line_number
    file_id = function_call_string[function_call_string.index(" ") + 1 : function_call_string.index(":")]
    line_number = function_call_string[function_call_string.index(":") + 1 :]

    # get tightest surrounding cu
    tightest_worker_cu = None
    # iterate over worker_cus
    for cur_w in worker_cus:
        cur_w_starts_at_line = cur_w.start_position()
        cur_w_ends_at_line = cur_w.end_position()
        cur_w_file_id = cur_w_starts_at_line[: cur_w_starts_at_line.index(":")]
        # check if file_id is equal
        if file_id == cur_w_file_id:
            # trim to line numbers only
            cur_w_starts_at_line = LineID(cur_w_starts_at_line[cur_w_starts_at_line.index(":") + 1 :])
            cur_w_ends_at_line = LineID(cur_w_ends_at_line[cur_w_ends_at_line.index(":") + 1 :])
            # check if line_number is contained
            if int(cur_w_starts_at_line) <= int(line_number) <= int(cur_w_ends_at_line):
                # check if cur_w is tighter than last result
                if tightest_worker_cu is None:
                    tightest_worker_cu = cur_w
                    continue
                if line_contained_in_region(
                    cur_w.start_position(),
                    tightest_worker_cu.start_position(),
                    tightest_worker_cu.end_position(),
                ) and line_contained_in_region(
                    cur_w.end_position(),
                    tightest_worker_cu.start_position(),
                    tightest_worker_cu.end_position(),
                ):
                    tightest_worker_cu = cur_w
    if tightest_worker_cu is None:
        raise ValueError("No surrounding worker CU could be found.")
    return tightest_worker_cu


def task_contained_in_reduction_loop(
    pet: PEGraphX, task: TaskParallelismInfo
) -> Tuple[Optional[Dict[str, str]], Optional[Node]]:
    """detect if task is contained in loop body of a reduction loop.
    return None, if task is not contained in reduction loop.
    else, return reduction_vars entry of parent reduction loop and loop CU Node.
    :param pet: PET graph
    :param task: TaskParallelismInfo
    :return: None / ({loop_line, name, reduction_line, operation}, CUNode)
    """
    # check if task contained in loop body
    parents = get_parent_of_type(pet, task._node, NodeType.LOOP, EdgeType.CHILD, False)
    contained_in = []
    if len(parents) == 0:
        return None, None
    else:
        # check if task is actually contained in one of the parents
        for parent_loop, last_node in parents:
            p_start_line = parent_loop.start_position()
            p_start_line = LineID(p_start_line[p_start_line.index(":") + 1 :])
            p_end_line = parent_loop.end_position()
            p_end_line = LineID(p_end_line[p_end_line.index(":") + 1 :])
            t_start_line = task.start_line
            t_start_line = LineID(t_start_line[t_start_line.index(":") + 1 :])
            t_end_line = task.end_line
            t_end_line = LineID(t_end_line[t_end_line.index(":") + 1 :])
            if p_start_line <= t_start_line and p_end_line >= t_end_line:
                contained_in.append(parent_loop)
    # check if task is contained in a reduction loop
    for parent in contained_in:
        if parent.reduction:
            # get correct entry for loop from pet.reduction_vars
            for rv in pet.reduction_vars:
                if rv["loop_line"] == parent.start_position():
                    return rv, parent
    return None, None


def get_function_call_from_source_code(
    source_code_files: Dict[str, str],
    line_number: int,
    file_id: str,
    called_function_name: Optional[str] = None,
) -> str:
    """Extract code snippet from original source code which contains a function call.
    :param source_code_files: File-Mapping dictionary
    :param line_number: original source code line number to start searching at
    :param file_id: file id of the original source code file
    :param called_function_name: optional parameter, if value is set, it needs to be included in returned code snippet.
    :return: source code snippet
    """
    source_code = open(source_code_files[file_id])
    source_code_lines = source_code.readlines()
    offset = -1
    function_call_string = source_code_lines[line_number + offset]
    if ")" in function_call_string and "(" in function_call_string:
        if function_call_string.index(")") < function_call_string.index("("):
            function_call_string = function_call_string[function_call_string.index(")") + 1 :]
    if ")" in function_call_string and "(" not in function_call_string:
        function_call_string = function_call_string[function_call_string.index(")") + 1 :]

    def __get_word_prior_to_bracket(string: str) -> Optional[str]:
        if "(" not in string:
            return None
        string = string[: string.index("(")]
        split_string = string.split(" ")
        split_string = [e for e in split_string if len(e) > 0]
        string = split_string[-1]
        return string

    called_function_name_contained = called_function_name is None

    while (
        function_call_string.count("(") > function_call_string.count(")")
        or function_call_string.count("(") < 1
        or function_call_string.count(")") < 1
        or __get_word_prior_to_bracket(function_call_string) == "while"
        or __get_word_prior_to_bracket(function_call_string) == "for"
        or __get_word_prior_to_bracket(function_call_string) == "if"
        or not called_function_name_contained
    ):
        # if ) prior to (, cut first part away
        if ")" in function_call_string and "(" in function_call_string:
            if function_call_string.index(")") < function_call_string.index("("):
                function_call_string = function_call_string[function_call_string.index(")") + 1 :]
        # if word prior to ( is "while", "for" or "if", cut away until (
        word_prior_to_bracket = __get_word_prior_to_bracket(function_call_string)
        if word_prior_to_bracket is not None:
            if word_prior_to_bracket == "while" or word_prior_to_bracket == "for" or word_prior_to_bracket == "if":
                function_call_string = function_call_string[function_call_string.index("(") + 1 :]
        # check if called_function_name is contained in function_call_string
        if not called_function_name_contained:
            called_function_name_str = cast(str, called_function_name)
            if called_function_name_str in function_call_string:
                called_function_name_contained = True
        offset += 1
        function_call_string += source_code_lines[line_number + offset]
    function_call_string = function_call_string.replace("\n", "")
    # if called_function_name is set and contained more than once in function_call_string, split function_call_string
    if called_function_name is not None:
        while function_call_string.count(called_function_name) > 1:
            function_call_string = function_call_string[: function_call_string.rfind(called_function_name)]

    return function_call_string


def get_called_function_and_parameter_names_from_function_call(
    source_code_line: str, mangled_function_name: str, node: CUNode
) -> Tuple[Optional[str], List[Optional[str]]]:
    """Returns the name of the called function and the names of the variables used as parameters in a list,
    if any are used.
    If parameter is a complex expression (e.g. addition, or function call, None is used at the respective position.
    Returns None if function name not in source_code_line
    :param source_code_line: string, source code snippet which contains the function call
    :param mangled_function_name: mangled name of the called function
    :param node: CUNode
    :return: function and parameter names. None instead of specific parameter, if no respective variable could be found.
    """
    global __global_llvm_cxxfilt_path
    # find function name by finding biggest match between function call line and recursive call
    try:
        mangled_function_name = mangled_function_name.split(" ")[0]  # ignore line if present
        function_name = demangle(mangled_function_name).split("(")[0]
    except ValueError:
        return None, []
    except AttributeError:
        return None, []
    if function_name not in source_code_line:
        return None, []

    # get parameters in brackets
    # parameter_string = source_code_line[function_position:]
    parameter_string = source_code_line[source_code_line.find(function_name) + len(function_name) :]
    parameter_string = parameter_string.replace("\t", "")
    if ";" in parameter_string:
        parameter_string = parameter_string[: parameter_string.index(";")]
    # prune left
    while "(" in parameter_string and not parameter_string.startswith("("):
        parameter_string = parameter_string[parameter_string.find("(") :]
    # prune right
    while ")" in parameter_string and not parameter_string.endswith(")"):
        parameter_string = parameter_string[: parameter_string.rfind(")") + 1]
    # prune to correct amount of closing brackets
    while not parameter_string.count("(") == parameter_string.count(")"):
        parameter_string = parameter_string[:-1]
        parameter_string = parameter_string[: parameter_string.rfind(")") + 1]
    parameter_string = parameter_string[1:-1]
    # intersect parameters with set of known variables to prevent errors
    parameters = parameter_string.split(",")
    result_parameters: List[Optional[str]] = []
    for param in parameters:
        param = param.replace("\t", "")
        if "+" in param or "-" in param or "*" in param or "/" in param or "(" in param or ")" in param:
            param_expression = param.replace("+", "$$").replace("-", "$$").replace("/", "$$")
            param_expression = param_expression.replace("*", "$$").replace("(", "$$").replace(")", "$$")
            split_param_expression = param_expression.split("$$")
            split_param_expression = [ex.replace(" ", "") for ex in split_param_expression]
            # check if any of the parameters is in list of known variables
            split_param_expression = [
                ex
                for ex in split_param_expression
                if ex in [var.replace(".addr", "") for var in [v.name for v in node.local_vars + node.global_vars]]
            ]
            # check if type of any of them contains * (i.e. is a pointer)
            found_entry = False
            for var_name_to_check in split_param_expression:
                if found_entry:
                    break
                for known_var in node.local_vars + node.global_vars:
                    if found_entry:
                        break
                    if known_var.name.replace(".addr", "") == var_name_to_check:
                        if "*" in known_var.type:
                            result_parameters.append(var_name_to_check)
                            found_entry = True
            if not found_entry:
                result_parameters.append(None)
        else:
            # check if param in known variables:
            result_parameters.append(param.replace(" ", ""))
    return cast(Optional[str], function_name), result_parameters


def set_global_llvm_cxxfilt_path(value: str) -> None:
    """setter for __global_llvm_cxxfilt_path
    :param value: value to place in __global_llvm_cxxfilt_path"""
    global __global_llvm_cxxfilt_path
    __global_llvm_cxxfilt_path = value


def get_called_functions_recursively(
    pet: PEGraphX, root: Node, visited: List[Node], cache: Dict[Any, Any]
) -> List[Union[FunctionNode, DummyNode]]:
    """returns a recursively generated list of called functions, started at root."""
    visited.append(root)
    called_functions: List[Union[FunctionNode, DummyNode]] = []
    for child in [pet.node_at(cuid) for cuid in [e[1] for e in out_edges(pet, root.id)]]:
        # check if type is Func or Dummy
        if isinstance(child, (FunctionNode, DummyNode)):
            # CU contains a function call
            # if Dummy, map to Func
            if isinstance(child, DummyNode):
                for function_cu in all_nodes(pet, FunctionNode):
                    if child.name == function_cu.name:
                        child = function_cu
            called_functions.append(cast(FunctionNode, child))
        elif child not in visited:
            if child in cache:
                called_functions += cache[child]
            else:
                # recursion step
                called_functions += get_called_functions_recursively(pet, child, visited, cache)
    if root not in cache:
        cache[root] = called_functions
    return called_functions


def contains_reduction(pet: PEGraphX, node: Node) -> bool:
    """Checks if node contains a reduction operation.
    :param pet: PET Graph
    :param node: CUNode
    :return: bool"""
    for red_var in pet.reduction_vars:
        if line_contained_in_region(red_var["reduction_line"], node.start_position(), node.end_position()):
            return True
    return False


def detect_mw_types(pet: PEGraphX, main_node: Node) -> None:
    """The mainNode we want to compute the Task Parallelism Pattern for it
    use Breadth First Search (BFS) to detect all barriers and workers.
    1.) all child nodes become first worker if they are not marked as worker before
    2.) if a child has dependence to more than one parent node, it will be marked as barrier
    Returns list of BARRIER_WORKER pairs 2
    :param pet: PET graph
    :param main_node: root node
    """

    # first insert all the direct children of main node in a queue to use it for the BFS
    for node in direct_children_or_called_nodes(pet, main_node):
        # a child node can be set to NONE or ROOT due a former detectMWNode call where it was the mainNode
        if node.mw_type == MWType.NONE or node.mw_type == MWType.ROOT:
            node.mw_type = MWType.FORK

        # while using the node as the base child, we copy all the other children in a copy vector.
        # we do that because it could be possible that two children of the current node (two dependency)
        # point to two different children of another child node which results that the child node becomes BARRIER
        # instead of WORKER
        # so we copy the whole other children in another vector and when one of the children of the current node
        # does point to the other child node, we just adjust mw_type and then we remove the node from the vector
        # Thus we prevent changing to BARRIER due of two dependencies pointing to two different children of
        # the other node

        # create the copy vector so that it only contains the other nodes
        other_nodes = direct_children_or_called_nodes(pet, main_node)
        other_nodes.remove(node)

        for other_node in other_nodes:
            if depends(pet, other_node, node):
                if other_node.mw_type == MWType.WORKER:
                    other_node.mw_type = MWType.BARRIER
                else:
                    other_node.mw_type = MWType.WORKER

                    # check if other_node has > 1 RAW dependencies to node
                    # -> not detected in previous step, since other_node is only
                    #    dependent of a single CU
                    raw_targets = []
                    for s, t, d in out_edges(pet, other_node.id):
                        if pet.node_at(t) == node:
                            if d.dtype == DepType.RAW:
                                raw_targets.append(t)
                    # remove entries which occur less than two times
                    raw_targets = [t for t in raw_targets if raw_targets.count(t) > 1]
                    # remove duplicates from list
                    raw_targets = list(dict.fromkeys(raw_targets))
                    # if elements remaining, mark other_node as BARRIER
                    if len(raw_targets) > 0:
                        other_node.mw_type = MWType.BARRIER

    pairs = []
    # check for Barrier Worker pairs
    # if two barriers don't have any dependency to each other then they create a barrierWorker pair
    # so check every barrier pair that they don't have a dependency to each other -> barrierWorker
    direct_subnodes = direct_children_or_called_nodes(pet, main_node)
    for n1 in direct_subnodes:
        if n1.mw_type == MWType.BARRIER:
            for n2 in direct_subnodes:
                if n2.mw_type == MWType.BARRIER and n1 != n2:
                    if n2 in [pet.node_at(t) for s, t, d in out_edges(pet, n1.id)] or n2 in [
                        pet.node_at(s) for s, t, d in in_edges(pet, n1.id)
                    ]:
                        break
                    # so these two nodes are BarrierWorker, because there is no dependency between them
                    pairs.append((n1, n2))
                    n1.mw_type = MWType.BARRIER_WORKER
                    n2.mw_type = MWType.BARRIER_WORKER
    # return pairs


def get_var_definition_line_dict(cu_xml: str) -> Dict[str, List[str]]:
    """creates a dictionary {varname: [definitionLines]} based on cu_xml
    and return the dictionary.
    Removes .addr suffix if present.
    :param cu_xml: Path (string) to the CU xml file to be used
    :return: dictionary, containing information on variable definition lines
    """
    xml_fd = open(cu_xml)
    xml_content = ""
    for line in xml_fd.readlines():
        if not (line.rstrip().endswith("</Nodes>") or line.rstrip().endswith("<Nodes>")):
            xml_content = xml_content + line
    xml_content = "<Nodes>{0}</Nodes>".format(xml_content)
    parsed_cu = objectify.fromstring(xml_content)

    var_def_line_dict = dict()
    for node in parsed_cu.Node:
        # only consider cu nodes
        if node.get("type") == "0":
            # add global variables
            for idx, global_variables_entry in enumerate(node.globalVariables):
                try:
                    for i in global_variables_entry["global"]:
                        # insert mapping into var_def_line_dict
                        if not i.text.replace(".addr", "") in var_def_line_dict:
                            var_def_line_dict[i.text.replace(".addr", "")] = [i.get("defLine")]
                        else:
                            var_def_line_dict[i.text.replace(".addr", "")].append(i.get("defLine"))
                            var_def_line_dict[i.text.replace(".addr", "")] = list(
                                set(var_def_line_dict[i.text.replace(".addr", "")])
                            )
                except AttributeError:
                    pass
            # add local variables
            for idx, global_variables_entry in enumerate(node.localVariables):
                try:
                    for i in global_variables_entry["local"]:
                        # insert mapping into var_def_line_dict
                        if not i.text.replace(".addr", "") in var_def_line_dict:
                            var_def_line_dict[i.text.replace(".addr", "")] = [i.get("defLine")]
                        else:
                            var_def_line_dict[i.text.replace(".addr", "")].append(i.get("defLine"))
                            var_def_line_dict[i.text.replace(".addr", "")] = list(
                                set(var_def_line_dict[i.text.replace(".addr", "")])
                            )
                except AttributeError:
                    pass
    return var_def_line_dict

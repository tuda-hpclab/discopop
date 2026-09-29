# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from copy import deepcopy
from typing import List

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.properties.depends_ignore_readonly import depends_ignore_readonly
from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.utils import correlation_coefficient

total = 0
before: List[float] = []
after: List[float] = []


def run_before(pet: PEGraphX) -> PEGraphX:
    return pet


def run_after(pet: PEGraphX) -> PEGraphX:
    for node in all_nodes(pet, LoopNode):
        check_pipeline(pet, node)

    print(f"Total: {total}")
    print(" ".join([str(x) for x in before]))
    print(" ".join([str(x) for x in after]))
    return pet


def check_pipeline(pet: PEGraphX, root: Node) -> None:
    """Tries to optimize dependencies for pipeline detection
    1. Deletes independent lines, that do not contribute to the pipeline
    2. Deletes similar CU (that have same dependencies), as those can be one step in the pipeline

    :param pet: PET graph
    :param root: current node
    :return: Pipeline scalar value
    """
    global total
    global before
    global after

    children_start_lines = [v.start_position() for v in subtree_of_type(pet, root, LoopNode)]

    loop_subnodes = [
        pet.node_at(t)
        for s, t, d in out_edges(pet, root.id, [EdgeType.CHILD, EdgeType.CALLSNODE])
        if is_pipeline_subnode(root, pet.node_at(t), children_start_lines)
    ]

    if len(loop_subnodes) < 3:
        return

    matrix = get_matrix(pet, root, loop_subnodes)
    initial_matrix = deepcopy(matrix)
    initial_coef = get_correlation_coefficient(matrix)

    if initial_coef < 0.999:
        total += 1
    independent_cus = get_independent_lines(matrix)
    delete_lines(matrix, loop_subnodes, independent_cus)

    no_indep_matrix = deepcopy(matrix)

    mergeable_cus = get_mergeable_nodes(matrix)
    delete_lines(matrix, loop_subnodes, mergeable_cus)

    new_coef = get_correlation_coefficient(matrix)
    if new_coef > initial_coef:
        before.append(initial_coef)
        after.append(new_coef)
        print("Pipeline improvement opportunity:")
        print("Node: " + root.id)
        print("Lines: " + root.start_position() + "-" + root.end_position())
        print("Independent lines:")
        independent_cus.sort()
        print(" ".join([str(x) for x in independent_cus]))
        print("Similar nodes:")
        mergeable_cus.sort()
        print(" ".join([str(x) for x in mergeable_cus]))
        print(f"matrix before: {initial_coef}")
        for i in range(0, len(initial_matrix)):
            print(" ".join([str(x) for x in initial_matrix[i]]))
        print(f"matrix after independent removed:")
        for i in range(0, len(no_indep_matrix)):
            print(" ".join([str(x) for x in no_indep_matrix[i]]))
        print(f"matrix after merged: {new_coef}")
        for i in range(0, len(matrix)):
            print(" ".join([str(x) for x in matrix[i]]))


def delete_lines(matrix: List[List[int]], loop_nodes: List[Node], lines: List[int]) -> None:
    if lines:
        lines.sort(reverse=True)
        for i in range(0, len(lines)):
            del loop_nodes[lines[i]]
            del matrix[lines[i]]
            for j in range(0, len(matrix)):
                del matrix[j][lines[i]]


def get_independent_lines(matrix: List[List[int]]) -> List[int]:
    res: List[int] = []
    for i in range(0, len(matrix)):
        indep = True
        for j in range(0, len(matrix)):
            if i != j and (matrix[i][j] != 0 or matrix[j][i] != 0):
                indep = False
        if indep:
            res.append(i)
    return res


def get_mergeable_nodes(matrix: List[List[int]]) -> List[int]:
    res: List[int] = []
    for i in reversed(range(1, len(matrix))):
        if matrix[i] == matrix[i - 1]:
            same = True
            for j in range(1, len(matrix)):
                if matrix[j][i] != matrix[j][i - 1]:
                    same = False
            if same:
                res.append(i)
    return res


def get_matrix(pet: PEGraphX, root: Node, loop_subnodes: List[Node]) -> List[List[int]]:
    res: List[List[int]] = []
    for i in range(0, len(loop_subnodes)):
        res.append([])
        for j in range(0, len(loop_subnodes)):
            res[i].append(int(depends_ignore_readonly(pet, loop_subnodes[i], loop_subnodes[j], root)))
    return res


def get_correlation_coefficient(matrix: List[List[int]]) -> float:
    graph_vector: List[float] = []
    for i in range(0, len(matrix) - 1):
        graph_vector.append(matrix[i + 1][i])

    pipeline_vector: List[float] = []
    for i in range(0, len(matrix) - 1):
        pipeline_vector.append(1.0)

    min_weight = 1.0
    for i in range(0, len(matrix) - 1):
        for j in range(i + 1, len(matrix)):
            if matrix[i][j] == 1:
                node_weight = 1 - (j - i) / (len(matrix) - 1)
                if min_weight > node_weight > 0:
                    min_weight = node_weight

    if min_weight == 1:
        graph_vector.append(0)
        pipeline_vector.append(0.0)
    else:
        graph_vector.append(1)
        pipeline_vector.append(min_weight)
    return round(correlation_coefficient(graph_vector, pipeline_vector), 2)


def is_pipeline_subnode(root: Node, current: Node, children_start_lines: List[LineID]) -> bool:
    """Checks if node is a valid subnode for pipeline

    :param root: root node
    :param current: current node
    :param children_start_lines: start lines of children loops
    :return: true if valid
    """
    r_start = root.start_position()
    r_end = root.end_position()
    c_start = current.start_position()
    c_end = current.end_position()
    return not (
        c_start == r_start
        and c_end == r_start
        or c_start == r_end
        and c_end == r_end
        or c_start == c_end
        and c_start in children_start_lines
    )

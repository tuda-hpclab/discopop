# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


import math
from typing import Dict, List, Tuple, Optional, cast

from discopop_explorer.functions.PEGraph.queries.edges import in_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.functions.PEGraph.traversal.children import direct_children_or_called_nodes_of_type
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType  # type: ignore

from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.utils import classify_task_vars, filter_for_hotspots, get_child_loops
from discopop_explorer.classes.variable import Variable

__loop_iterations: Dict[NodeID, int] = {}


class GDInfo(PatternInfo):
    """Class, that contains geometric decomposition detection result"""

    def __init__(self, pet: PEGraphX, node: Node, min_iter: int):
        """
        :param pet: PET graph
        :param node: node, where geometric decomposition was detected
        """
        PatternInfo.__init__(self, node)

        self.do_all_children, self.reduction_children = get_child_loops(pet, node)

        self.min_iter_number = min_iter
        mi_sqrt = math.sqrt(min_iter)
        wl = math.sqrt(self.get_workload(pet))
        nt = 1.1 * mi_sqrt + 0.0002 * wl - 0.0000002 * mi_sqrt * wl - 10

        if nt >= 1000:
            self.num_tasks = math.floor(nt / 100) * 100
        elif nt >= 100:
            self.num_tasks = math.floor(nt / 10) * 10
        elif nt < 0:
            self.num_tasks = 2
        else:
            self.num_tasks = math.floor(nt)

        self.pragma = "for (i = 0; i < num-tasks; i++) #pragma omp task"
        lp: List[Variable] = []
        fp, p, s, in_dep, out_dep, in_out_dep, r = classify_task_vars(pet, node, "GeometricDecomposition", [], [])
        fp.append(Variable("int", VarName("i"), "", sizeInByte=4))

        self.first_private = fp
        self.private = p
        self.last_private = lp
        self.shared = s
        self.reduction = r

    def __str__(self) -> str:
        return (
            f"Geometric decomposition at: {self.node_id}\n"
            f"Start line: {self.start_line}\n"
            f"End line: {self.end_line}\n"
            f"Do-All loops: {[n.id for n in self.do_all_children]}\n"
            f"Reduction loops: {[n.id for n in self.reduction_children]}\n"
            f"\tNumber of tasks: {self.num_tasks}\n"
            f"\tChunk limits: {self.min_iter_number}\n"
            f"\tpragma: {self.pragma}]\n"
            f"\tprivate: {[v.name for v in self.private]}\n"
            f"\tshared: {[v.name for v in self.shared]}\n"
            f"\tfirst private: {[v.name for v in self.first_private]}\n"
            f"\treduction: {[v for v in self.reduction]}\n"
            f"\tlast private: {[v.name for v in self.last_private]}"
        )


global_pet = None


def run_detection(
    pet: PEGraphX, hotspots: Optional[Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]]
) -> List[GDInfo]:
    """Detects geometric decomposition

    :param pet: PET graph
    :return: List of detected pattern info
    """
    import tqdm  # type: ignore
    from multiprocessing import Pool

    global global_pet
    global_pet = pet

    result: List[GDInfo] = []
    global __loop_iterations
    __loop_iterations = {}
    nodes = all_nodes(pet, FunctionNode)

    nodes = cast(List[FunctionNode], filter_for_hotspots(pet, cast(List[Node], nodes), hotspots))

    param_list = [(node) for node in nodes]

    for param_tpl in param_list:
        result += __check_node(param_tpl)
    print("GLOBAL RES: ", result)

    for pattern in result:
        pattern.get_workload(pet)

    return result


def __initialize_worker(pet: PEGraphX) -> None:
    global global_pet
    global_pet = pet


def __check_node(param_tuple: Node) -> List[GDInfo]:
    global global_pet
    local_result: List[GDInfo] = []
    node = param_tuple
    if global_pet is None:
        raise ValueError("global_pet is None!")

    if __detect_geometric_decomposition(global_pet, node):
        node.geometric_decomposition = True
        test, min_iter = __test_chunk_limit(global_pet, node)
        if test and min_iter is not None:
            local_result.append(GDInfo(global_pet, node, min_iter))

    return local_result


def __test_chunk_limit(pet: PEGraphX, node: Node) -> Tuple[bool, Optional[int]]:
    """Tests, whether or not the node has inner loops with and none of them have 0 iterations

    :param pet: PET graph
    :param node: the node
    :return: true if node satisfies condition, min iteration number
    """
    min_iterations_count = None
    inner_loop_iter = {}

    children = direct_children_or_called_nodes_of_type(pet, node, LoopNode)

    for func_child in direct_children_or_called_nodes_of_type(pet, node, FunctionNode):
        children.extend(direct_children_or_called_nodes_of_type(pet, func_child, LoopNode))

    for child in children:
        inner_loop_iter[child.start_position()] = __iterations_count(pet, child)

    for k, v in inner_loop_iter.items():
        if min_iterations_count is None or v < min_iterations_count:
            min_iterations_count = v
    return (
        bool(inner_loop_iter) and (min_iterations_count is None or min_iterations_count > 0),
        min_iterations_count,
    )


def __iterations_count(pet: PEGraphX, node: LoopNode) -> int:
    """Counts the iterations in the specified node

    :param pet: PET graph
    :param node: the loop node
    :return: number of iterations
    """
    if not (node in __loop_iterations):
        loop_iter = node.loop_iterations
        parent_iter = __get_parent_iterations(pet, node)

        if loop_iter < parent_iter:
            __loop_iterations[node.id] = loop_iter
        elif loop_iter <= 0 or parent_iter <= 0:
            __loop_iterations[node.id] = 0
        else:
            __loop_iterations[node.id] = loop_iter // parent_iter

    return __loop_iterations[node.id]


def __get_parent_iterations(pet: PEGraphX, node: Node) -> int:
    """Calculates the number of iterations in parent of loop

    :param pet: PET graph
    :param node: current node
    :return: number of iterations
    """
    parent = in_edges(pet, node.id, [EdgeType.CHILD, EdgeType.CALLSNODE])

    max_iter = 1
    visited = []  # used to prevent looping
    while parent:
        node = pet.node_at(parent[0][0])
        # prevent looping
        if node in visited:
            break
        if isinstance(node, LoopNode):
            max_iter = max(1, node.loop_iterations)
            break
        visited.append(node)
        parent = in_edges(pet, node.id, [EdgeType.CHILD, EdgeType.CALLSNODE])

    return max_iter


def __detect_geometric_decomposition(pet: PEGraphX, root: Node) -> bool:
    """Detects geometric decomposition pattern

    :param pet: PET graph
    :param root: root node
    :return: true if GD pattern was discovered
    """
    for loop_child in subtree_of_type(pet, root, LoopNode):
        if not (loop_child.reduction or loop_child.do_all):
            return False

    for child in direct_children_or_called_nodes_of_type(pet, root, FunctionNode):
        for child2 in direct_children_or_called_nodes_of_type(pet, child, LoopNode):
            if not (child2.reduction or child2.do_all):
                return False

    return True

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


from typing import List, Optional, Tuple, Dict, cast

from discopop_explorer.functions.PEGraph.properties.depends_ignore_readonly import depends_ignore_readonly
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType  # type: ignore

from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.utils import correlation_coefficient, classify_task_vars, filter_for_hotspots

__pipeline_threshold = 0.9


class PipelineStage(object):
    def __init__(
        self,
        pet: PEGraphX,
        node: Node,
        in_dep: List[Tuple[NodeID, NodeID, Dependency]],
        out_dep: List[Tuple[NodeID, NodeID, Dependency]],
    ):
        self.node = node.id
        self.startsAtLine = node.start_position()
        self.endsAtLine = node.end_position()

        fp, p, s, in_deps, out_deps, in_out_deps, r = classify_task_vars(pet, node, "Pipeline", in_dep, out_dep)

        self.first_private = fp
        self.private = p
        self.shared = s
        self.reduction = r
        self.in_deps = in_deps
        self.out_deps = out_deps
        self.in_out_deps = in_out_deps

    def __str__(self) -> str:
        return (
            f"\tNode: {self.node}\n"
            f"\tStart line: {self.startsAtLine}\n"
            f"\tEnd line: {self.endsAtLine}\n"
            f'\tpragma: "#pragma omp task"\n'
            f"\tfirst private: {[v.name for v in self.first_private]}\n"
            f"\tprivate: {[v.name for v in self.private]}\n"
            f"\tshared: {[v.name for v in self.shared]}\n"
            f"\treduction: {[v for v in self.reduction]}\n"
            f"\tInDeps: {[v.name for v in self.in_deps]}\n"
            f"\tOutDeps: {[v.name for v in self.out_deps]}\n"
            f"\tInOutDeps: {[v.name for v in self.in_out_deps]}"
        )


class PipelineInfo(PatternInfo):
    """Class, that contains pipeline detection result"""

    coefficient: float

    def __init__(self, pet: PEGraphX, node: Node):
        """
        :param pet: PET graph
        :param node: node, where pipeline was detected
        """
        PatternInfo.__init__(self, node)
        self._pet = pet
        self.coefficient = round(node.pipeline, 3)

        children_start_lines = [v.start_position() for v in subtree_of_type(pet, node, LoopNode)]

        self._stages = [
            pet.node_at(t)
            for s, t, d in out_edges(pet, node.id, [EdgeType.CHILD, EdgeType.CALLSNODE])
            if is_pipeline_subnode(node, pet.node_at(t), children_start_lines)
        ]

        self.stages = [self.__output_stage(s) for s in self._stages]

    def __in_dep(self, node: Node) -> List[Tuple[NodeID, NodeID, Dependency]]:
        raw: List[Tuple[NodeID, NodeID, Dependency]] = []
        for n in subtree_of_type(self._pet, node, CUNode):
            raw.extend((s, t, d) for s, t, d in out_edges(self._pet, n.id, EdgeType.DATA) if d.dtype == DepType.RAW)

        nodes_before = [node]
        for i in range(self._stages.index(node)):
            nodes_before.extend(subtree_of_type(self._pet, self._stages[i], CUNode))

        return [dep for dep in raw if dep[1] in [n.id for n in nodes_before]]

    def __out_dep(self, node: Node) -> List[Tuple[NodeID, NodeID, Dependency]]:
        raw: List[Tuple[NodeID, NodeID, Dependency]] = []
        for n in subtree_of_type(self._pet, node, CUNode):
            raw.extend((s, t, d) for s, t, d in in_edges(self._pet, n.id, EdgeType.DATA) if d.dtype == DepType.RAW)

        nodes_after = [node]
        for i in range(self._stages.index(node) + 1, len(self._stages)):
            nodes_after.extend(subtree_of_type(self._pet, self._stages[i], CUNode))

        return [dep for dep in raw if dep[0] in [n.id for n in nodes_after]]

    def __output_stage(self, node: Node) -> PipelineStage:
        in_d = self.__in_dep(node)
        out_d = self.__out_dep(node)

        return PipelineStage(self._pet, node, in_d, out_d)

    def __str__(self) -> str:
        s = "\n\n".join([str(s) for s in self.stages])
        return (
            f"Pipeline at: {self.node_id}\n"
            # f"Coefficient: {round(self.coefficient, 3)}\n"
            f"Start line: {self.start_line}\n"
            f"End line: {self.end_line}\n"
            f"Stages:\n{s}"
        )


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


global_pet = None


def run_detection(
    pet: PEGraphX, hotspots: Optional[Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]]
) -> List[PipelineInfo]:
    """Search for pipeline pattern on all the loops in the graph
    except for doall loops

    :param pet: PET graph
    :return: List of detected pattern info
    """
    import tqdm  # type: ignore
    from multiprocessing import Pool

    global global_pet
    global_pet = pet

    result: List[PipelineInfo] = []
    nodes = all_nodes(pet, LoopNode)

    nodes = cast(List[LoopNode], filter_for_hotspots(pet, cast(List[Node], nodes), hotspots))

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


def __check_node(param_tuple: LoopNode) -> List[PipelineInfo]:
    global global_pet
    local_result = []

    node = param_tuple

    if global_pet is None:
        raise ValueError("global_pet is None!")

    node.pipeline = __detect_pipeline(global_pet, node)
    if node.pipeline > __pipeline_threshold:
        local_result.append(PipelineInfo(global_pet, node))

    return local_result


def __detect_pipeline(pet: PEGraphX, root: Node) -> float:
    """Calculate pipeline value for node

    :param pet: PET graph
    :param root: current node
    :return: Pipeline scalar value
    """

    children_start_lines = [v.start_position() for v in subtree_of_type(pet, root, LoopNode)]

    loop_subnodes = [
        pet.node_at(t)
        for s, t, d in out_edges(pet, root.id, [EdgeType.CHILD, EdgeType.CALLSNODE])
        if is_pipeline_subnode(root, pet.node_at(t), children_start_lines)
    ]

    # No chain of stages found
    if len(loop_subnodes) < 2:
        return 0

    graph_vector = []
    for i in range(0, len(loop_subnodes) - 1):
        graph_vector.append(1.0 if depends_ignore_readonly(pet, loop_subnodes[i + 1], loop_subnodes[i], root) else 0.0)

    pipeline_vector = []
    for i in range(0, len(loop_subnodes) - 1):
        pipeline_vector.append(1.0)

    min_weight = 1.0
    for i in range(0, len(loop_subnodes) - 1):
        for j in range(i + 1, len(loop_subnodes)):
            if depends_ignore_readonly(pet, loop_subnodes[i], loop_subnodes[j], root):
                # TODO whose corresponding entry in the graph matrix is nonzero?
                node_weight = 1 - (j - i) / (len(loop_subnodes) - 1)
                if min_weight > node_weight > 0:
                    min_weight = node_weight

    if min_weight == 1.0:
        graph_vector.append(0.0)
        pipeline_vector.append(0)
    else:
        graph_vector.append(1.0)
        pipeline_vector.append(min_weight)

    return correlation_coefficient(graph_vector, pipeline_vector)

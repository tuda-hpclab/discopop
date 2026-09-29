# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.properties.is_loop_index import is_loop_index
from discopop_explorer.functions.PEGraph.properties.is_readonly_inside_loop_body import is_readonly_inside_loop_body
from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type


def depends_ignore_readonly(self: PEGraphX, source: Node, target: Node, root_loop: Node) -> bool:
    """Detects if source node or one of it's children has a RAW dependency to target node or one of it's children
    The loop index and readonly variables are ignored.

    :param source: source node for dependency detection (later occurrence in the source code)
    :param target: target of dependency (prior occurrence in the source code)
    :param root_loop: root loop
    :return: true, if there is RAW dependency"""
    if source == target:
        return False

    # get recursive children of source and target
    source_children_ids = [node.id for node in subtree_of_type(self, source, CUNode)]
    target_children_ids = [node.id for node in subtree_of_type(self, target, CUNode)]

    # get required metadata
    loop_start_lines: List[LineID] = []
    root_children = subtree_of_type(self, root_loop, (CUNode, LoopNode))
    root_children_cus = [cu for cu in root_children if isinstance(cu, CUNode)]
    root_children_loops = [cu for cu in root_children if isinstance(cu, LoopNode)]
    for v in root_children_loops:
        loop_start_lines.append(v.start_position())

    # check for RAW dependencies between any of source_children and any of target_children
    for source_child_id in source_children_ids:
        # get a list of filtered dependencies, outgoing from source_child
        out_deps = out_edges(self, source_child_id, EdgeType.DATA)
        out_raw_deps = [dep for dep in out_deps if dep[2].dtype == DepType.RAW]
        filtered_deps = [
            elem
            for elem in out_raw_deps
            if not is_readonly_inside_loop_body(
                self,
                elem[2],
                root_loop,
                root_children_cus,
                root_children_loops,
                loops_start_lines=loop_start_lines,
            )
        ]
        filtered_deps = [
            elem
            for elem in filtered_deps
            if not is_loop_index(self, elem[2].var_name, loop_start_lines, root_children_cus)
        ]
        # get a list of dependency targets
        dep_targets = [t for _, t, _ in filtered_deps]
        # check if overlap between dependency targets and target_children exists.
        overlap = [node_id for node_id in dep_targets if node_id in target_children_ids]
        if len(overlap) > 0:
            # if so, a RAW dependency exists
            return True
    return False

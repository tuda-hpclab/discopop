# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""PEGraphX.enforce_single_function_exit_node: one exit node per function, with the next free id of its file."""

from __future__ import annotations

from typing import Any, Callable, List, Tuple

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type

MakeNode = Callable[..., Any]
BuildPetGraph = Callable[..., PEGraphX]


def _reference_enforce_single_function_exit_node(pet: PEGraphX) -> None:
    """The implementation before the highest node id of a file was determined once (it searched all nodes for every
    function)."""
    for func in all_nodes(pet, FunctionNode):
        file_id = func.file_id
        max_node_id_in_file = 0
        for node in all_nodes(pet):
            if node.file_id != file_id:
                continue
            if ":" in node.id:
                id_int = int(node.id.split(":")[1])
                if id_int > max_node_id_in_file:
                    max_node_id_in_file = id_int
        exit_id = NodeID(str(file_id) + ":" + str(max_node_id_in_file + 1))
        exit_node = Node(exit_id)
        exit_node.type = NodeType.CU
        exit_node.name = "FuncExit_" + func.name
        pet.g.add_node(exit_id, data=exit_node)
        subtree = subtree_of_type(pet, func, CUNode, True)
        max_end_line = 0
        for node in subtree:
            if len(out_edges(pet, node.id, EdgeType.SUCCESSOR)) == 0:
                pet.g.add_edge(node.id, exit_id, data=Dependency(EdgeType.SUCCESSOR))
                max_end_line = max(max_end_line, node.end_line)
        exit_node.start_line = max_end_line
        exit_node.end_line = max_end_line


def _graph(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> PEGraphX:
    """File 1: function 1:0 (CUs 1:1 -> 1:2 and a CU 1:7 without successor), function 1:3 (CU 1:4), a node 1:9 that
    belongs to no function; file 2: function 2:0 (CU 2:1) and function 2:5 (CU 2:6)."""
    nodes = [
        make_node("1:0", NodeType.FUNC, name="a"),
        make_node("1:1", NodeType.CU, name="a1", start_line=1, end_line=2),
        make_node("1:2", NodeType.CU, name="a2", start_line=3, end_line=5),
        make_node("1:7", NodeType.CU, name="a3", start_line=6, end_line=8),
        make_node("1:3", NodeType.FUNC, name="b"),
        make_node("1:4", NodeType.CU, name="b1", start_line=10, end_line=12),
        make_node("1:9", NodeType.CU, name="orphan", start_line=20, end_line=21),
        make_node("2:0", NodeType.FUNC, name="c"),
        make_node("2:1", NodeType.CU, name="c1", start_line=1, end_line=4),
        make_node("2:5", NodeType.FUNC, name="d"),
        make_node("2:6", NodeType.CU, name="d1", start_line=5, end_line=9),
    ]
    edges: List[Tuple[str, str, EdgeType]] = [
        ("1:0", "1:1", EdgeType.CHILD),
        ("1:0", "1:2", EdgeType.CHILD),
        ("1:0", "1:7", EdgeType.CHILD),
        ("1:1", "1:2", EdgeType.SUCCESSOR),
        ("1:3", "1:4", EdgeType.CHILD),
        ("2:0", "2:1", EdgeType.CHILD),
        ("2:5", "2:6", EdgeType.CHILD),
    ]
    return build_pet_graph(nodes, edges)


def _state(pet: PEGraphX) -> Tuple[List[Tuple[str, str, int, int]], List[Tuple[str, str, str]]]:
    nodes = sorted((str(n.id), n.name, n.start_line, n.end_line) for _, n in pet.g.nodes(data="data"))
    edges = sorted((str(s), str(t), d.etype.name) for s, t, d in pet.g.edges(data="data"))
    return nodes, edges


def test_every_function_gets_an_exit_node_with_the_next_free_id_of_its_file(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet = _graph(make_node, build_pet_graph)
    pet.enforce_single_function_exit_node()
    # file 1: the highest id is 9, the exit nodes of its two functions are 10 and 11; file 2: 6 -> 7 and 8
    exits = {str(n.id): n.name for _, n in pet.g.nodes(data="data") if n.name.startswith("FuncExit_")}
    assert exits == {"1:10": "FuncExit_a", "1:11": "FuncExit_b", "2:7": "FuncExit_c", "2:8": "FuncExit_d"}


def test_the_cus_without_successor_lead_to_the_exit_node(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet = _graph(make_node, build_pet_graph)
    pet.enforce_single_function_exit_node()
    _, edges = _state(pet)
    exit_edges = [e for e in edges if e[2] == "SUCCESSOR" and e[1] in {"1:10", "1:11", "2:7", "2:8"}]
    assert exit_edges == [
        ("1:2", "1:10", "SUCCESSOR"),
        ("1:4", "1:11", "SUCCESSOR"),
        ("1:7", "1:10", "SUCCESSOR"),
        ("2:1", "2:7", "SUCCESSOR"),
        ("2:6", "2:8", "SUCCESSOR"),
    ]
    # the position of an exit node is the end of the last CU leading to it
    positions = {str(n.id): (n.start_line, n.end_line) for _, n in pet.g.nodes(data="data") if str(n.id) == "1:10"}
    assert positions == {"1:10": (8, 8)}


def test_the_result_equals_the_one_of_the_implementation_searching_all_nodes(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    new = _graph(make_node, build_pet_graph)
    new.enforce_single_function_exit_node()
    reference = _graph(make_node, build_pet_graph)
    _reference_enforce_single_function_exit_node(reference)
    assert _state(new) == _state(reference)

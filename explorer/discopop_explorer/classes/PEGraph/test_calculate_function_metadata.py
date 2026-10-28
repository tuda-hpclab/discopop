# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Which functions PEGraphX.calculateFunctionMetadata computes metadata for.

All of them: the metadata attributes accesses to functions, so a function that is too short to
be a hotspot (and not listed in Hotspots.json at all) needs it as much as a hot one, e.g. for its side effects.
"""

from __future__ import annotations

from typing import Any, Callable, List

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType

MakeNode = Callable[..., Any]
BuildPetGraph = Callable[..., PEGraphX]


def _two_function_graph(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> PEGraphX:
    """Two functions, "hot" and "cold", each with one child CU."""
    return build_pet_graph(
        [
            make_node("1:0", NodeType.FUNC, name="hot"),
            make_node("1:1", NodeType.CU, name="hot_body"),
            make_node("1:2", NodeType.FUNC, name="cold"),
            make_node("1:3", NodeType.CU, name="cold_body"),
        ],
        [
            ("1:0", "1:1", EdgeType.CHILD),
            ("1:2", "1:3", EdgeType.CHILD),
        ],
    )


def _processed_function_names(pet: PEGraphX) -> List[str]:
    """Names of the functions metadata was computed for.

    children_cu_ids starts out as None and is only populated by the metadata
    computation, so it doubles as a marker of which functions were processed.
    """
    return sorted(
        node.name
        for node in pet.g.nodes(data="data")  # type: ignore[misc]
        for node in [node[1]]
        if isinstance(node, FunctionNode) and node.children_cu_ids is not None
    )


def test_all_functions_are_processed(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet = _two_function_graph(make_node, build_pet_graph)
    pet.calculateFunctionMetadata()
    assert _processed_function_names(pet) == ["cold", "hot"]


def test_the_children_of_every_function_get_their_parent_function(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    """What the side effects of a function rest on, hot or not."""
    pet = _two_function_graph(make_node, build_pet_graph)
    pet.calculateFunctionMetadata()
    assert pet.node_at(NodeID("1:1")).parent_function_id == NodeID("1:0")
    assert pet.node_at(NodeID("1:3")).parent_function_id == NodeID("1:2")


def test_explicit_func_nodes_are_the_ones_processed(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    """Callers passing func_nodes select the functions themselves."""
    pet = _two_function_graph(make_node, build_pet_graph)
    cold = [node for node in pet.g.nodes(data="data") if node[1].name == "cold"][0][1]  # type: ignore[misc]
    pet.calculateFunctionMetadata(func_nodes=[cold])
    assert _processed_function_names(pet) == ["cold"]

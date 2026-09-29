# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Which functions PEGraphX.calculateFunctionMetadata computes metadata for.

Hotspot information restricts the metadata computation to the hot functions,
but only when it actually says something about functions -- see the guard in
calculateFunctionMetadata.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType

MakeNode = Callable[..., Any]
BuildPetGraph = Callable[..., PEGraphX]

HotspotEntry = Tuple[int, int, HotspotNodeType, str, float]


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


def _function_hotspot(name: str) -> Dict[HotspotType, List[HotspotEntry]]:
    return {HotspotType.YES: [(1, 1, HotspotNodeType.FUNCTION, name, 1.0)]}


def test_without_hotspot_information_all_functions_are_processed(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet = _two_function_graph(make_node, build_pet_graph)
    pet.calculateFunctionMetadata(None)
    assert _processed_function_names(pet) == ["cold", "hot"]


def test_hotspot_information_restricts_the_processed_functions(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet = _two_function_graph(make_node, build_pet_graph)
    pet.calculateFunctionMetadata(_function_hotspot("hot"))
    assert _processed_function_names(pet) == ["hot"]


def test_empty_hotspot_information_does_not_filter(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    """The hotspot loader returns {} when Hotspots.json is absent.

    That means "nothing is known", not "no function is hot" -- filtering against
    it would leave every function without reachability metadata.
    """
    pet = _two_function_graph(make_node, build_pet_graph)
    pet.calculateFunctionMetadata({})
    assert _processed_function_names(pet) == ["cold", "hot"]


def test_hotspot_information_without_function_entries_does_not_filter(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    """Hotspots.json may classify only LOOP regions in the requested hotspot types."""
    pet = _two_function_graph(make_node, build_pet_graph)
    loops_only: Dict[HotspotType, List[HotspotEntry]] = {HotspotType.YES: [(1, 10, HotspotNodeType.LOOP, "", 1.0)]}
    pet.calculateFunctionMetadata(loops_only)
    assert _processed_function_names(pet) == ["cold", "hot"]


def test_explicit_func_nodes_are_never_filtered(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    """Callers passing func_nodes select the functions themselves."""
    pet = _two_function_graph(make_node, build_pet_graph)
    cold = [node for node in pet.g.nodes(data="data") if node[1].name == "cold"][0][1]  # type: ignore[misc]
    pet.calculateFunctionMetadata(_function_hotspot("hot"), func_nodes=[cold])
    assert _processed_function_names(pet) == ["cold"]

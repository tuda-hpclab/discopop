# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""parallel_map, the choice of the number of threads, and calculateFunctionMetadata on threads."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Tuple

import pytest

from discopop_explorer import parallel_utils
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.parallel_utils import effective_workers, parallel_map

MakeNode = Callable[..., Any]
BuildPetGraph = Callable[..., PEGraphX]


@pytest.mark.parametrize("workers", [1, 2, 8])  # type: ignore[misc]
def test_parallel_map_returns_the_results_in_the_order_of_the_items(workers: int) -> None:
    def slow_for_small_numbers(x: int) -> int:
        time.sleep(0.002 * (10 - x % 10))  # the first items finish last
        return x * x

    items = list(range(40))
    assert parallel_map(slow_for_small_numbers, items, workers) == [x * x for x in items]


def test_parallel_map_of_nothing_and_of_one_item() -> None:
    assert parallel_map(lambda x: x, [], 4) == []
    assert parallel_map(lambda x: x + 1, [1], 4) == [2]


def test_parallel_map_uses_several_threads() -> None:
    barrier = threading.Barrier(4, timeout=10)  # passes only if four calls are running at the same time

    def meet(x: int) -> int:
        barrier.wait()
        return x

    assert parallel_map(meet, [1, 2, 3, 4], 4) == [1, 2, 3, 4]


def test_parallel_map_raises_the_exception_of_a_call_and_does_not_start_the_rest() -> None:
    started: List[int] = []

    def fail_on_three(x: int) -> int:
        started.append(x)
        if x == 3:
            raise ValueError("three")
        time.sleep(0.01)
        return x

    with pytest.raises(ValueError, match="three"):
        parallel_map(fail_on_three, list(range(200)), 2)
    assert len(started) < 200


def test_serial_for_jobs_up_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parallel_utils, "gil_enabled", lambda: False)
    assert effective_workers(0) == 1
    assert effective_workers(1) == 1


def test_serial_with_the_gil(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parallel_utils, "gil_enabled", lambda: True)
    assert effective_workers(None) == 1
    assert effective_workers(8) == 1


def test_threads_without_the_gil(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parallel_utils, "gil_enabled", lambda: False)
    assert effective_workers(8) == 8
    assert effective_workers(None) >= 1


def _graph_with_functions(make_node: MakeNode, build_pet_graph: BuildPetGraph, functions: int = 12) -> PEGraphX:
    """`functions` functions of four CUs each (a diamond of SUCCESSOR edges plus a loop back edge in every third), and
    a CU every function calls, which is the child of the first function only."""
    nodes = []
    edges: List[Tuple[str, str, EdgeType]] = []
    for f in range(functions):
        base = 10 * f
        nodes.append(make_node(f"1:{base}", NodeType.FUNC, name=f"f{f}"))
        for c in range(1, 5):
            nodes.append(make_node(f"1:{base + c}", NodeType.CU, name=f"f{f}_cu{c}"))
            edges.append((f"1:{base}", f"1:{base + c}", EdgeType.CHILD))
        edges += [
            (f"1:{base + 1}", f"1:{base + 2}", EdgeType.SUCCESSOR),
            (f"1:{base + 1}", f"1:{base + 3}", EdgeType.SUCCESSOR),
            (f"1:{base + 2}", f"1:{base + 4}", EdgeType.SUCCESSOR),
            (f"1:{base + 3}", f"1:{base + 4}", EdgeType.SUCCESSOR),
        ]
        if f % 3 == 0:
            edges.append((f"1:{base + 4}", f"1:{base + 1}", EdgeType.SUCCESSOR))
    return build_pet_graph(nodes, edges)


def _metadata(pet: PEGraphX) -> Dict[str, Any]:
    result: Dict[str, Any] = dict()
    for _, node in pet.g.nodes(data="data"):  # type: ignore[misc]
        if isinstance(node, FunctionNode):
            reach = {str(k): sorted(str(v) for v in vs) for k, vs in (node.reachability_pairs or {}).items()}
            result[str(node.id)] = (sorted(str(c) for c in node.children_cu_ids or []), reach)
        else:
            result[str(node.id)] = str(node.parent_function_id)
    return result


def test_function_metadata_of_functions_with_and_without_a_loop(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet = _graph_with_functions(make_node, build_pet_graph, functions=4)
    pet.calculateFunctionMetadata()
    metadata = _metadata(pet)
    # function f0 has a loop back edge 4 -> 1: all of its CUs reach each other
    children, reachability = metadata["1:0"]
    assert children == ["1:1", "1:2", "1:3", "1:4"]
    assert reachability["1:4"] == ["1:1", "1:2", "1:3", "1:4"]
    # function f1 (id 10) has none: the last CU reaches only itself, the first one all
    children, reachability = metadata["1:10"]
    assert reachability["1:14"] == ["1:14"]
    assert reachability["1:11"] == ["1:11", "1:12", "1:13", "1:14"]
    # the parent function of every CU, and no reachability across functions
    assert metadata["1:12"] == "1:10"
    assert metadata["1:31"] == "1:30"
    assert all(not r.startswith("1:3") for r in reachability["1:11"])


def test_reachability_from_plain_successor_lists_equals_the_one_from_the_graph(
    make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet = _graph_with_functions(make_node, build_pet_graph)
    pet.calculateFunctionMetadata()
    functions = [n for _, n in pet.g.nodes(data="data") if isinstance(n, FunctionNode)]  # type: ignore[misc]
    assert len(functions) == 12
    for function in functions:
        assert function.reachability_pairs == function.calculate_reachability_pairs(pet)


def test_edges_for_the_function_metadata(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet = _graph_with_functions(make_node, build_pet_graph, functions=2)
    children, successors = parallel_utils.function_metadata_edges(pet)
    assert children[NodeID("1:0")] == ["1:1", "1:2", "1:3", "1:4"]
    assert successors[NodeID("1:1")] == ["1:2", "1:3"]
    assert successors[NodeID("1:4")] == ["1:1"]  # the loop back edge of the first function
    assert NodeID("1:0") not in successors

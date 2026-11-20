# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Checks for running the explorer's detectors on threads that really run in parallel.

On a free-threaded interpreter (``python3.14t``, GIL disabled) these tests show that

* importing the explorer and its dependencies does not switch the GIL back on, and
* the read-only detection functions give the serial result when many threads call them on one shared
  ``PEGraphX`` at the same time.

On a regular interpreter the concurrency tests still run (the GIL serializes them); only the GIL test is skipped.
Run them under the free-threaded build with
``PYTHON_GIL=0 python3.14t -m pytest explorer/discopop_explorer/test_free_threading.py`` (the variable makes sure that
an extension module that does not declare free-threading support cannot re-enable the GIL unnoticed).
"""

from __future__ import annotations

import importlib
import sys
import sysconfig
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Tuple, cast

import pytest

from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., PEGraphX]

THREADS = 8
ROUNDS = 20
LOOPS = 24

FREE_THREADED_BUILD = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))


def _gil_enabled() -> bool:
    check = getattr(sys, "_is_gil_enabled", None)
    return True if check is None else bool(check())


def _detector(module: str, function: str) -> Callable[[PEGraphX, LoopNode], bool]:
    # the detector functions have module level names starting with two underscores
    return cast(Callable[[PEGraphX, LoopNode], bool], getattr(importlib.import_module(module), function))


def _graph_with_loops(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> Tuple[PEGraphX, List[LoopNode]]:
    """A function with LOOPS loops of two CUs each, side by side."""
    main = make_node("1:1", NodeType.FUNC, name="main")
    nodes: List[Node] = [main]
    edges = []
    loops: List[LoopNode] = []
    next_id = 2
    for i in range(LOOPS):
        loop = make_node(f"1:{next_id}", NodeType.LOOP, name=f"loop{i}", start_line=10 * i + 1, end_line=10 * i + 9)
        cu1 = make_node(f"1:{next_id + 1}", NodeType.CU, name=f"cu{i}a", start_line=10 * i + 2, end_line=10 * i + 2)
        cu2 = make_node(f"1:{next_id + 2}", NodeType.CU, name=f"cu{i}b", start_line=10 * i + 3, end_line=10 * i + 3)
        next_id += 3
        nodes += [loop, cu1, cu2]
        edges += [
            (main.id, loop.id, EdgeType.CHILD),
            (loop.id, cu1.id, EdgeType.CHILD),
            (loop.id, cu2.id, EdgeType.CHILD),
        ]
        loops.append(cast(LoopNode, loop))
    return build_pet_graph(nodes, edges), loops


@pytest.mark.skipif(not FREE_THREADED_BUILD, reason="needs a free-threaded interpreter (python3.14t)")  # type: ignore[misc]
def test_importing_the_explorer_keeps_the_gil_disabled() -> None:
    # all of these are imported by the explorer's detection code; an extension module without free-threading
    # support would switch the GIL on at import time
    for module in (
        "networkx",
        "numpy",
        "scipy",
        "lxml.etree",
        "jsonpickle",
        "discopop_explorer.classes.PEGraph.PEGraphX",
    ):
        try:
            importlib.import_module(module)
        except ModuleNotFoundError:
            continue
        assert not _gil_enabled(), f"importing {module} re-enabled the GIL"


@pytest.mark.parametrize(  # type: ignore[misc]
    "module, function",
    [
        ("discopop_explorer.pattern_detectors.do_all_detector", "__detect_do_all"),
        ("discopop_explorer.pattern_detectors.reduction_detector", "__detect_reduction"),
    ],
)
def test_concurrent_detection_matches_serial(
    make_node: MakeNode, build_pet_graph: BuildPetGraph, module: str, function: str
) -> None:
    detect = _detector(module, function)
    pet, loops = _graph_with_loops(make_node, build_pet_graph)
    expected = [detect(pet, loop) for loop in loops]

    for _ in range(ROUNDS):
        barrier = threading.Barrier(THREADS)

        def work(offset: int) -> List[bool]:
            barrier.wait()  # start all threads at the same moment
            # every thread visits all loops, starting at another one, so that the threads meet on the same nodes
            order = loops[offset:] + loops[:offset]
            by_id = {loop.id: detect(pet, loop) for loop in order}
            return [by_id[loop.id] for loop in loops]

        with ThreadPoolExecutor(max_workers=THREADS) as executor:
            results = list(executor.map(work, range(THREADS)))
        assert all(result == expected for result in results)


def test_concurrent_graph_reads_see_a_consistent_graph(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> None:
    pet, loops = _graph_with_loops(make_node, build_pet_graph)
    expected_nodes = {node_id for node_id in pet.g.nodes}
    expected_edges = sorted((str(s), str(t)) for s, t in pet.g.edges())
    errors: List[BaseException] = []
    barrier = threading.Barrier(THREADS)

    def work() -> None:
        try:
            barrier.wait()
            for _ in range(ROUNDS * 5):
                assert {node_id for node_id in pet.g.nodes} == expected_nodes
                assert sorted((str(s), str(t)) for s, t in pet.g.edges()) == expected_edges
                for loop in loops:
                    assert pet.node_at(loop.id) is loop
        except BaseException as e:  # noqa: BLE001 - reported to the main thread below
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []

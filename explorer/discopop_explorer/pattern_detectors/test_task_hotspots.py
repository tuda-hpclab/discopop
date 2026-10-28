# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Hotspot classes of the task and parallel region patterns (design/task_suggestions.md, 3.9)."""

from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo, TPIType
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.pattern_detectors.task_hotspots import attach_hotspot_information, classify_region
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType

MakeNode = Callable[..., Node]
BuildPetGraph = Callable[..., Any]


def _group(make_node: MakeNode, build_pet_graph: BuildPetGraph) -> Tuple[Any, ParallelRegionInfo, TaskParallelismInfo]:
    """fib: a group of two tasks on lines 11 and 12 of file 1, the first one calls fib (instruction 7)"""
    caller = make_node(
        "1:10",
        NodeType.CU,
        start_line=11,
        end_line=12,
        node_calls=[{"cuid": "1:99", "atLine": "1:11", "callInstId": "7"}],
    )
    function = make_node("1:99", NodeType.FUNC, name="fib", end_line=20)
    pet = build_pet_graph([caller, function])
    task = TaskParallelismInfo(caller, TPIType.TASK, ["#pragma omp task"], "11", [], [], [])
    task.instruction_ids = [7]
    setattr(caller, "instruction_ids", [7])
    region = ParallelRegionInfo(caller, TPIType.PARALLELREGION, 11, 12, task_group=[0], contained_tasks=[task])
    return pet, region, task


def _entry(node_type: HotspotNodeType, line: int, name: str = "", runtime: float = 0.5, file_id: int = 1) -> Any:
    return (file_id, line, node_type, name, runtime)


def test_a_group_whose_task_calls_a_hotspot_function_is_a_hotspot(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, region, _ = _group(make_node, build_pet_graph)
    hotspots = {HotspotType.YES: [_entry(HotspotNodeType.FUNCTION, 5, "fib", 2.5)]}
    assert classify_region(pet, region, hotspots) == (HotspotType.YES, 2.5)


def test_a_hotspot_loop_in_the_region_is_a_match(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, region, _ = _group(make_node, build_pet_graph)
    hotspots = {HotspotType.MAYBE: [_entry(HotspotNodeType.LOOP, 12, runtime=0.1)]}
    assert classify_region(pet, region, hotspots) == (HotspotType.MAYBE, 0.1)


def test_the_best_class_wins_and_its_largest_runtime_is_taken(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, region, _ = _group(make_node, build_pet_graph)
    hotspots = {
        HotspotType.NO: [_entry(HotspotNodeType.LOOP, 11, runtime=9.0)],
        HotspotType.YES: [
            _entry(HotspotNodeType.LOOP, 12, runtime=1.0),
            _entry(HotspotNodeType.FUNCTION, 5, "fib", 3.0),
        ],
    }
    assert classify_region(pet, region, hotspots) == (HotspotType.YES, 3.0)


def test_other_files_functions_and_loops_outside_the_region_do_not_match(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, region, _ = _group(make_node, build_pet_graph)
    hotspots = {
        HotspotType.YES: [
            _entry(HotspotNodeType.LOOP, 13),  # after the region
            _entry(HotspotNodeType.LOOP, 11, file_id=2),  # another file
            _entry(HotspotNodeType.FUNCTION, 5, "other"),  # not called by the tasks
            _entry(HotspotNodeType.FUNCTION, 5, "fib", file_id=2),  # another fib
        ]
    }
    assert classify_region(pet, region, hotspots) == (None, None)


def test_the_function_the_region_lies_in_is_no_match(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, region, _ = _group(make_node, build_pet_graph)
    caller = _entry(HotspotNodeType.FUNCTION, 1, "main")
    assert classify_region(pet, region, {HotspotType.YES: [caller]}) == (None, None)


def test_without_hotspot_information_nothing_is_set(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, region, task = _group(make_node, build_pet_graph)
    for hotspots in (None, dict()):  # type: ignore[var-annotated]
        attach_hotspot_information(pet, [region, task], hotspots)
        assert region.hotspot_type is None and task.hotspot_type is None


def test_the_class_is_attached_to_the_region_and_its_tasks(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, region, task = _group(make_node, build_pet_graph)
    hotspots = {HotspotType.YES: [_entry(HotspotNodeType.FUNCTION, 5, "fib", 2.5)]}
    attach_hotspot_information(pet, [task, region], hotspots)
    for pattern in (region, task):
        assert (pattern.hotspot_type, pattern.hotspot_runtime) == (HotspotType.YES, 2.5)


def test_the_group_of_a_loop_is_classified_by_the_loop(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    """the region of the tasks of a loop covers the body: the hotspot loop is the one that creates them"""
    pet, region, _ = _group(make_node, build_pet_graph)
    region.loop_start_line, region.loop_end_line = "1:9", "1:13"
    hotspots = {HotspotType.YES: [_entry(HotspotNodeType.LOOP, 9, runtime=4.0)]}
    assert classify_region(pet, region, hotspots) == (HotspotType.YES, 4.0)


def test_a_region_with_unreadable_lines_is_not_classified(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    pet, region, _ = _group(make_node, build_pet_graph)
    region.region_end_line = "x"
    hotspots = {HotspotType.YES: [_entry(HotspotNodeType.LOOP, 11)]}
    result: Tuple[Optional[HotspotType], Optional[float]] = classify_region(pet, region, hotspots)
    assert result == (None, None)


def test_the_recursive_calls_of_the_region_are_resolved_by_the_function_name(
    isolated_pattern_id_cwd: Any, make_node: MakeNode, build_pet_graph: BuildPetGraph
) -> None:
    """a recursive call is no edge of the graph, only the text "<function> <file id>:<line>," of the CU"""
    caller = make_node("1:10", NodeType.CU, start_line=11, end_line=12, recursive_function_calls=["fib 1:11,fib 1:40,"])
    function = make_node("1:99", NodeType.FUNC, name="fib", end_line=20)
    pet = build_pet_graph([caller, function])
    task = TaskParallelismInfo(caller, TPIType.TASK, ["#pragma omp task"], "11", [], [], [])
    task.instruction_ids = [7]
    setattr(caller, "instruction_ids", [7])
    region = ParallelRegionInfo(caller, TPIType.PARALLELREGION, 11, 12, task_group=[0], contained_tasks=[task])
    hotspots = {HotspotType.YES: [_entry(HotspotNodeType.FUNCTION, 5, "fib", 2.5)]}
    assert classify_region(pet, region, hotspots) == (HotspotType.YES, 2.5)
    # a recursive call outside of the region, a call of another function and None entries are no match
    caller.recursive_function_calls = ["fib 1:40,", "other 1:11,", None]  # type: ignore[list-item]
    assert classify_region(pet, region, hotspots) == (None, None)

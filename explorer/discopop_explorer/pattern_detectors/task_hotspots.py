# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Hotspot information for the task and parallel region patterns (design/task_suggestions.md, 3.9).

The autotuner selects patterns by their hotspot class. A group of tasks is not a loop, so the lines of its first task
never contained a loop hotspot: the groups of recursive functions were never classified. A group is classified here
by what it contains: the hotspot loops inside its region and the hotspot functions its tasks call.
"""

from typing import Dict, List, Optional, Sequence, Set, Tuple

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.classes.patterns.TaskParallelismInfo import ParallelRegionInfo, TaskParallelismInfo
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType

HotspotInformation = Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]

# the best class wins: a region that contains a YES hotspot is YES, whatever else it contains
_PRIORITY = [HotspotType.YES, HotspotType.MAYBE, HotspotType.NO]


def function_files(pet: PEGraphX) -> Dict[NodeID, int]:
    """The file id of each function. The id of a function node has the file id 0 ("0:<n>"), the file is only known
    from the nodes of its code: the file id of the hotspot of a function is not the one of its node."""
    files: Dict[NodeID, int] = {}
    for cu in all_nodes(pet, CUNode):
        if cu.parent_function_id is not None:
            files.setdefault(cu.parent_function_id, cu.file_id)
    return files


def _callees_of_region(
    pet: PEGraphX, instruction_ids: Sequence[int], file_id: int, first: int, last: int
) -> Set[Tuple[int, str]]:
    """(file id, name) of the functions called by the instructions. The recursive calls are no edges of the graph
    ("<function> <file id>:<line>," per call): those on the lines of the region are resolved by the name, preferring
    the functions of the file of the call."""
    wanted = set(instruction_ids)
    result: Set[Tuple[int, str]] = set()
    files = function_files(pet)
    functions: Dict[str, List[int]] = {}
    for function in all_nodes(pet, FunctionNode):
        functions.setdefault(function.name, []).append(files.get(function.id, function.file_id))
    for cu in all_nodes(pet, CUNode):
        if wanted.isdisjoint(cu.instruction_ids):
            continue
        for call in cu.node_calls:
            call_id = call.get("callInstId")
            if call_id is None or int(call_id) not in wanted or call["cuid"] not in pet.g:
                continue
            callee = pet.node_at(NodeID(call["cuid"]))
            result.add((files.get(callee.id, callee.file_id), callee.name))
        for text in cu.recursive_function_calls:
            if not text:  # an empty element of Data.xml is read as None
                continue
            for entry in text.split(","):
                name, _, position = entry.strip().partition(" ")
                try:
                    call_file, call_line = (int(part) for part in position.split(":"))
                except ValueError:
                    continue
                if call_file == file_id and first <= call_line <= last and name in functions:
                    candidates = [f for f in functions[name] if f == call_file] or functions[name]
                    result |= {(f, name) for f in candidates}
    return result


def _region_of(region: ParallelRegionInfo) -> Optional[Tuple[int, int, int]]:
    """(file id, first line, last line) of the code the region contains. For the tasks of a loop, the loop itself."""
    try:
        if region.loop_start_line is not None and region.loop_end_line is not None:
            file_id, first = (int(part) for part in region.loop_start_line.split(":"))
            last = int(region.loop_end_line.split(":")[1])
        else:
            file_id = int(region.start_line.split(":")[0])
            first, last = int(region.region_start_line), int(region.region_end_line)
    except (ValueError, IndexError, TypeError):
        return None
    return file_id, min(first, last), max(first, last)


def classify_region(
    pet: PEGraphX, region: ParallelRegionInfo, hotspots: Optional[HotspotInformation]
) -> Tuple[Optional[HotspotType], Optional[float]]:
    """(class, average runtime) of the region, (None, None) if there is no hotspot information or nothing matches.

    Matches: a hotspot loop whose first line lies in the region, a hotspot function that one of the tasks calls. The
    best class of the matches is the class of the region, the largest runtime of the matches of that class its
    runtime (nested hotspots overlap, a sum would count them twice). The function the region lies in is no match:
    the group of a cold recursive call inside a hot ``main`` is no hotspot.
    """
    if not hotspots:
        return None, None
    location = _region_of(region)
    if location is None:
        return None, None
    file_id, first, last = location
    callees = _callees_of_region(pet, region.instruction_ids, file_id, first, last)
    matches: Dict[HotspotType, List[float]] = {}
    for hotspot_type, entries in hotspots.items():
        for entry_file, entry_line, node_type, name, runtime in entries:
            if node_type == HotspotNodeType.LOOP:
                matched = entry_file == file_id and first <= entry_line <= last
            else:
                matched = (entry_file, name) in callees
            if matched:
                matches.setdefault(hotspot_type, []).append(runtime)
    for hotspot_type in _PRIORITY:
        if hotspot_type in matches:
            return hotspot_type, max(matches[hotspot_type])
    return None, None


def attach_hotspot_information(
    pet: PEGraphX, patterns: Sequence[PatternInfo], hotspots: Optional[HotspotInformation]
) -> None:
    """Sets ``hotspot_type`` and ``hotspot_runtime`` of the parallel regions among the patterns, and of the tasks they
    contain. Without hotspot information nothing is set: the consumers treat every suggestion alike then."""
    if not hotspots:
        return
    tasks = {p.pattern_id: p for p in patterns if isinstance(p, TaskParallelismInfo)}
    for pattern in patterns:
        if not isinstance(pattern, ParallelRegionInfo):
            continue
        hotspot_type, runtime = classify_region(pet, pattern, hotspots)
        pattern.hotspot_type = hotspot_type
        pattern.hotspot_runtime = runtime
        for task_id in pattern.contains_patterns:
            if task_id in tasks:
                tasks[task_id].hotspot_type = hotspot_type
                tasks[task_id].hotspot_runtime = runtime

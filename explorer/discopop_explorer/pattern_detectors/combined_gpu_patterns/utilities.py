# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from collections import deque
from typing import List, Set, Dict, Tuple, Optional

from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import out_edges


def get_contained_lines(start_line: str, end_line: str) -> List[str]:
    """Returns a list of line numbers inbetween start_line and end_line"""
    file_id = start_line.split(":")[0]
    if file_id != end_line.split(":")[0]:
        raise ValueError("File-ids not equal! ", start_line, end_line)
    line_numbers: List[int] = list(range(int(start_line.split(":")[1]), int(end_line.split(":")[1]) + 1))
    result = [file_id + ":" + str(num) for num in line_numbers]
    return result


def get_function_body_cus_without_called_functions(pet: PEGraphX, function_node: FunctionNode) -> List[NodeID]:
    queue = deque(t for s, t, d in out_edges(pet, function_node.id, EdgeType.CHILD))
    visited: Set[NodeID] = set()
    while queue:
        current = queue.popleft()
        visited.add(current)
        current_node = pet.node_at(current)

        # add children if they do not result from a call
        children = [t for s, t, d in out_edges(pet, current, EdgeType.CHILD)]
        called = [t for s, t, d in out_edges(pet, current, EdgeType.CALLSNODE)]
        queue += [c for c in children if c not in visited and c not in called]  # todo add check for call
    return list(visited)


def prepare_liveness_metadata(
    pet: PEGraphX,
    liveness: Dict[MemoryRegion, List[NodeID]],
    writes: Dict[MemoryRegion, Set[Tuple[NodeID, Optional[int]]]],
    meta_liveness: Dict[MemoryRegion, List[str]],
) -> Dict[MemoryRegion, List[str]]:
    for mem_reg in liveness:
        for cu_id in liveness[mem_reg]:
            if mem_reg not in meta_liveness:
                meta_liveness[mem_reg] = []
            cu_node = pet.node_at(cu_id)
            write_identifiers: Set[int] = set()
            for cid, ident in writes[mem_reg]:
                if cid == cu_id:
                    if ident is not None:
                        write_identifiers.add(ident)

            for line in get_contained_lines(cu_node.start_position(), cu_node.end_position()):
                if len(write_identifiers) > 0:
                    # is written
                    line = line + ":" + "(" + ",".join([str(ident) for ident in write_identifiers]) + ")"
                else:
                    # is read
                    line = line + ":"
                meta_liveness[mem_reg].append(line)

    # remove duplicates
    for mem_reg in meta_liveness:
        meta_liveness[mem_reg] = list(dict.fromkeys(meta_liveness[mem_reg]))
    # if read and write entries for the same line number exist, remove the read access
    for mem_reg in meta_liveness:
        to_be_removed: Set[str] = set()
        for entry in meta_liveness[mem_reg]:
            if ":(" in entry:
                # is written
                continue
            # else, check if write exists in list
            for entry_2 in meta_liveness[mem_reg]:
                split_line_1 = entry.split(":")
                split_line_2 = entry_2.split(":")
                if split_line_1[0] == split_line_2[0] and split_line_1[1] == split_line_2[1]:
                    if split_line_1[2] == split_line_2[2]:
                        continue
                    if split_line_2[2].startswith("("):
                        # split_line_2 is a write access.
                        # remove read entry
                        to_be_removed.add(entry)
        for entry in to_be_removed:
            if entry in meta_liveness[mem_reg]:
                meta_liveness[mem_reg].remove(entry)

    return meta_liveness

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Readers for the profiler output that describes the "<function>_loopstate<digits>" callpath labels.

Each digit of such a label is the iteration bucket of one loop of the function. Which loop a digit
position stands for is written by the profiler to loopstate_positions.txt (see
DiscoPoP::buildStaticCalltree), one line per digit position:

    <function name> <position> <loop id> <Data.xml loop node id> <file_id>:<start line>

The loop node id and the start location are "-" if the profiler could not determine them. The file
is appended to by every compiled module, so a function compiled in several modules (e.g. an inline
function of a header) is listed once per module."""

from __future__ import annotations

import os
import re
from typing import Dict, List, NamedTuple, Optional

LOOPSTATE_POSITIONS_FILE = "loopstate_positions.txt"


class LoopstatePosition(NamedTuple):
    function_name: str
    position: int
    loop_id: int
    loop_node_id: Optional[str]
    start_location: Optional[str]


def read_loopstate_positions(path: str) -> Optional[Dict[str, List[LoopstatePosition]]]:
    """The entries of loopstate_positions.txt per function name, in file order. None if the file does
    not exist (profiles of older profiler versions). Malformed lines are skipped."""
    if not os.path.exists(path):
        return None
    result: Dict[str, List[LoopstatePosition]] = dict()
    with open(path, "r") as f:
        for line in f:
            fields = line.split()
            if len(fields) != 5 or fields[0].startswith("#"):
                continue
            try:
                position = int(fields[1])
                loop_id = int(fields[2])
            except ValueError:
                continue
            entry = LoopstatePosition(
                fields[0],
                position,
                loop_id,
                None if fields[3] == "-" else fields[3],
                None if fields[4] == "-" else fields[4],
            )
            result.setdefault(entry.function_name, []).append(entry)
    return result


_LOOPSTATE_LABEL = re.compile(r"(\S+)_loopstate(\d+)(?:\s|$)")


def read_loopstate_digit_counts(state_mappings_file: str) -> Dict[str, int]:
    """Number of loopstate digits per function name, as found in the labels of
    stateID_to_callpath_mapping.txt. Empty if the file does not exist."""
    counts: Dict[str, int] = dict()
    if not os.path.exists(state_mappings_file):
        return counts
    with open(state_mappings_file, "r") as f:
        for line in f:
            if "_loopstate" not in line:
                continue
            for function_name, digits in _LOOPSTATE_LABEL.findall(line):
                counts[function_name] = max(counts.get(function_name, 0), len(digits))
    return counts

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

from typing import Optional, List

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType


class Dependency:
    etype: EdgeType
    dtype: Optional[DepType] = None
    var_name: Optional[str] = None
    memory_region: Optional[MemoryRegion] = None
    source_line: Optional[LineID] = None
    sink_line: Optional[LineID] = None
    intra_iteration: bool = False
    intra_iteration_level: int = -1
    metadata_intra_iteration_dep: Optional[List[LineID]]
    metadata_inter_iteration_dep: Optional[List[LineID]]
    metadata_intra_call_dep: Optional[List[LineID]]
    metadata_inter_call_dep: Optional[List[LineID]]
    metadata_sink_ancestors: Optional[List[LineID]]
    metadata_source_ancestors: Optional[List[LineID]]
    origin: Optional[DepOrigin] = None
    is_gep_result_dependency: bool = False

    def __init__(self, type: EdgeType):
        self.etype = type
        self.metadata_intra_iteration_dep = []
        self.metadata_inter_iteration_dep = []
        self.metadata_intra_call_dep = []
        self.metadata_inter_call_dep = []
        self.metadata_sink_ancestors = []
        self.metadata_source_ancestors = []

    def __str__(self) -> str:
        return self.var_name if self.var_name is not None else str(self.etype)

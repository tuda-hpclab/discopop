# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

from typing import FrozenSet, List, Optional

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType

# marker for Dependency.carried_by_loop: carried by a loop outside of the contexts of its ends
CARRIED_OUTSIDE = object()


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
    # an end of the dependency could not be attributed to the calling context of its callpath state
    # and was mapped to a wider scope (see TaskGraph._ContextFallback)
    approximate_context: bool = False
    # the loop whose iterations the dependency crosses, if the callpath states of its ends tell
    # (see TaskGraph.__carried_frame_and_position): a LoopParentContext, CARRIED_OUTSIDE if that loop has no
    # context on the chain of the ends, or None if unknown
    carried_by_loop: Optional[object] = None
    # the PET identity of the loops whose iterations the dependency crosses: the node ids of the loops'
    # entry CUs (LoopParentContext.parent_loop). Derived from the callpath states of the ends (the
    # frame's function and loopstate position, see TaskGraph.__assign_loopstate_positions_within_functions)
    # or, for records without states, from the instruction order of the ends (then possibly several
    # nested loops). Unlike carried_by_loop, it does not depend on the contexts the ends were mapped
    # to, so it is also known for ends mapped to a standalone copy of a function or approximately.
    # None if unknown.
    carried_by_pet_loops: Optional[FrozenSet[str]] = None

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

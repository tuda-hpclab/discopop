# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

from typing import TYPE_CHECKING, FrozenSet, Optional, Union

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext


class CarriedOutside:
    """Type of CARRIED_OUTSIDE, the marker for Dependency.carried_by_loop: carried by a loop outside of
    the contexts of its ends."""

    def __repr__(self) -> str:
        return "CARRIED_OUTSIDE"


CARRIED_OUTSIDE = CarriedOutside()

# the loop whose iterations a dependency crosses, see Dependency.carried_by_loop
CarriedByLoop = Optional[Union["LoopParentContext", CarriedOutside]]


class Dependency:
    etype: EdgeType
    dtype: Optional[DepType] = None
    var_name: Optional[str] = None
    memory_region: Optional[MemoryRegion] = None
    source_line: Optional[LineID] = None
    sink_line: Optional[LineID] = None
    intra_iteration: bool = False
    intra_iteration_level: int = -1
    origin: Optional[DepOrigin] = None
    is_gep_result_dependency: bool = False
    # an end of the dependency could not be attributed to the calling context of its callpath state
    # and was mapped to a wider scope (see TaskGraph._ContextFallback)
    approximate_context: bool = False
    # the loop whose iterations the dependency crosses, if the callpath states of its ends tell
    # (see TaskGraph.__carried_frame_and_position): a LoopParentContext, CARRIED_OUTSIDE if that loop has no
    # context on the chain of the ends, or None if unknown
    carried_by_loop: CarriedByLoop = None
    # the PET identity of the loops whose iterations the dependency crosses: the node ids of the loops'
    # entry CUs (LoopParentContext.parent_loop). Derived from the callpath states of the ends (the
    # frame's function and loopstate position, see TaskGraph.__assign_loopstate_positions_within_functions)
    # or, for records without states, from the instruction order of the ends (then possibly several
    # nested loops). Unlike carried_by_loop, it does not depend on the contexts the ends were mapped
    # to, so it is also known for ends mapped to a standalone copy of a function or approximately.
    # None if unknown.
    carried_by_pet_loops: Optional[FrozenSet[str]] = None
    # the instruction ids (dp.md.instr.id) and callpath states of the ends, None for ends recorded without them
    source_instruction_id: Optional[int] = None
    sink_instruction_id: Optional[int] = None
    source_state_id: Optional[str] = None
    sink_state_id: Optional[str] = None

    def __init__(self, type: EdgeType):
        # Every attribute is assigned here, in one fixed order, although most have class-level
        # defaults: CPython keeps the attributes of instances whose attributes were added in the
        # same order in a compact, key-sharing layout. Setting the defaulted attributes only later,
        # in an order that differs between the creators (PEGraphConstructionUtilities, the
        # TaskGraph's dependency insertion), materializes a full dict per instance, which more than
        # doubles the size of a Dependency (568 -> 1224 bytes).
        self.etype = type
        self.dtype = None
        self.var_name = None
        self.memory_region = None
        self.source_line = None
        self.sink_line = None
        self.intra_iteration = False
        self.intra_iteration_level = -1
        self.origin = None
        self.is_gep_result_dependency = False
        self.approximate_context = False
        self.carried_by_loop = None
        self.carried_by_pet_loops = None
        self.source_instruction_id = None
        self.sink_instruction_id = None
        self.source_state_id = None
        self.sink_state_id = None

    def __hash__(self) -> int:
        # not the address: dependencies are kept in sets (with their contexts), whose iteration order follows the
        # hashes and would differ from run to run. Equality stays the identity, so collisions are harmless.
        return hash((self.source_instruction_id or -1, self.sink_instruction_id or -1))

    def __str__(self) -> str:
        return self.var_name if self.var_name is not None else str(self.etype)

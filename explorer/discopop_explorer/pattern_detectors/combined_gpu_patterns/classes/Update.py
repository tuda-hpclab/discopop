# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
import os
from typing import Set, Dict, cast, Optional, List, Tuple

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.functions.PEGraph.queries.variables import get_variable
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import (
    VarName,
)
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Dependency import Dependency
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Enums import UpdateType
from discopop_library.MemoryRegions.utils import get_sizes_of_memory_regions


class Update(object):
    synchronous_source_cu_id: NodeID
    asynchronous_source_cu_id: Optional[NodeID]
    sink_cu_id: NodeID
    memory_regions: Set[MemoryRegion]
    variable_names: Set[VarName]
    update_type: UpdateType
    last_write_locations: Dict[MemoryRegion, NodeID]
    asynchronous_possible: bool
    dependencies: Set[Dependency]

    def __init__(
        self,
        cu_id: NodeID,
        sink_cu_id: NodeID,
        memory_regions: Set[MemoryRegion],
        update_type: UpdateType,
        last_write_locations: Dict[MemoryRegion, NodeID],
    ):
        self.synchronous_source_cu_id = cu_id
        self.asynchronous_source_cu_id = None
        self.sink_cu_id = sink_cu_id
        self.memory_regions = memory_regions
        self.variable_names = set()
        self.update_type = update_type
        self.last_write_locations = last_write_locations
        self.dependencies = set()
        self.asynchronous_possible = False

    # Preserve, as it will be added in the future
    #        if False:  # disable asynchronous updates
    #            # check if an asynchronous update is possible
    #            # only allow asynchronous updates to the device in order to not get problems with
    #            # enforcing dependencies on the host --> tasks etc. would be required to implement the waiting behavior
    #            if self.update_type != UpdateType.FROM_DEVICE:
    #                import sys
    #
    #                print("ORIGINAL SOURCE: ", self.synchronous_source_cu_id, file=sys.stderr)
    #                self.asynchronous_possible = True
    #                asynchronous_source: Optional[NodeID] = None
    #                for mem_reg in self.memory_regions:
    #                    if self.last_write_locations[mem_reg] == self.synchronous_source_cu_id:
    #                        self.asynchronous_possible = False
    #                        break
    #                    if asynchronous_source is None:
    #                        asynchronous_source = self.last_write_locations[mem_reg]
    #                    if asynchronous_source != self.last_write_locations[mem_reg]:
    #                        self.asynchronous_possible = False
    #                        break
    #
    #                if self.asynchronous_possible:
    #                    # update the asynchronous source cu
    #                    self.asynchronous_source_cu_id = cast(NodeID, asynchronous_source)
    #
    #                    # create a dependency to ensure correctness
    #                    self.dependencies.add(
    #                        Dependency(
    #                            self.asynchronous_source_cu_id,
    #                            self.sink_cu_id,
    #                            self.variable_names,
    #                            self.memory_regions,
    #                        )
    #                    )

    def __str__(self) -> str:
        result_str = ""
        result_str += (
            str(self.update_type)
            + " @ "
            + self.synchronous_source_cu_id
            + " -> "
            + self.sink_cu_id
            + " : "
            + str(self.variable_names)
            + "/"
            + str(self.memory_regions)
            + " last_writes@ "
            + str(self.last_write_locations)
            + " async "
            if self.asynchronous_possible
            else ""
        )
        return result_str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Update):
            raise ValueError("other is not of correct type!")
        if (
            self.synchronous_source_cu_id,
            self.asynchronous_source_cu_id,
            self.sink_cu_id,
            #            tuple(self.memory_regions),  # leads to duplicated outputs
            tuple(self.variable_names),
            self.update_type,
            tuple(self.last_write_locations.items()),
            self.asynchronous_possible,
            tuple(self.dependencies),
        ) == (
            other.synchronous_source_cu_id,
            other.asynchronous_source_cu_id,
            other.sink_cu_id,
            #            tuple(other.memory_regions),  # leads to duplicated outputs
            tuple(other.variable_names),
            other.update_type,
            tuple(other.last_write_locations.items()),
            other.asynchronous_possible,
            tuple(other.dependencies),
        ):
            return True
        return False

    def __hash__(self) -> int:
        return hash(
            (
                self.synchronous_source_cu_id,
                self.asynchronous_source_cu_id,
                self.sink_cu_id,
                tuple(self.memory_regions),
                tuple(self.variable_names),
                self.update_type,
                tuple(self.last_write_locations.items()),
                self.asynchronous_possible,
                tuple(self.dependencies),
            )
        )

    def get_position_identifier(self) -> Tuple[NodeID, NodeID, UpdateType]:
        # used to join multiple elements
        if self.asynchronous_possible:
            if self.asynchronous_source_cu_id is None:
                raise ValueError("Asynchronous_source_cu_id is None")
            return (self.sink_cu_id, self.asynchronous_source_cu_id, self.update_type)
        else:
            return (self.sink_cu_id, self.synchronous_source_cu_id, self.update_type)

    def join(self, other: Update) -> None:
        self.variable_names.update(other.variable_names)
        self.memory_regions.update(other.memory_regions)
        self.dependencies.update(other.dependencies)

    def get_as_metadata_using_memory_regions(self, pet: PEGraphX) -> Tuple[NodeID, NodeID, UpdateType, str, LineID]:
        return (
            self.synchronous_source_cu_id,
            self.sink_cu_id,
            self.update_type,
            str(self.memory_regions),
            pet.node_at(self.synchronous_source_cu_id).end_position(),
        )

    def get_as_metadata_using_variable_names(
        self, pet: PEGraphX, project_folder_path: str
    ) -> Tuple[NodeID, NodeID, UpdateType, str, LineID]:
        # get type of mapped variables
        var_names_types_and_sizes: List[Tuple[VarName, str, int]] = []
        for var_name in self.variable_names:
            var_obj = get_variable(pet, self.sink_cu_id, var_name)
            source_cu_id = (
                self.asynchronous_source_cu_id if self.asynchronous_possible else self.synchronous_source_cu_id
            )
            if var_obj is None:
                var_obj = get_variable(pet, cast(NodeID, source_cu_id), var_name)
            if var_obj is None:
                var_names_types_and_sizes.append((var_name, "", 1))
            else:
                var_names_types_and_sizes.append((var_name, var_obj.type, var_obj.sizeInByte))
        # add [..] to variable name if required (type contains "**")

        # get size of memory region
        memory_region_sizes = get_sizes_of_memory_regions(
            self.memory_regions, os.path.join(project_folder_path, "profiler/memory_regions.txt")
        )
        if len(memory_region_sizes) > 0:
            max_mem_reg_size = max(memory_region_sizes.values())
            # divide memory region size by size of variable
            # construct new list of modified var names
            modified_var_names = [
                (
                    vn + "[:]" if "**" in t else vn
                )  # (vn + "[:" + str(int(max_mem_reg_size / s)) + "]" if "**" in t else vn)
                for vn, t, s in var_names_types_and_sizes
            ]
        else:
            modified_var_names = [(vn + "[:]" if "**" in t else vn) for vn, t, s in var_names_types_and_sizes]

        # determine update position in code
        # todo consider asynchronous updates
        if self.update_type == UpdateType.FROM_DEVICE:
            # data required by host. Perform update before the sink CU
            update_position = pet.node_at(self.sink_cu_id).start_position()
        elif self.update_type == UpdateType.TO_DEVICE:
            # data required by device. Perform update before the sink CU
            update_position = pet.node_at(self.sink_cu_id).start_position()
        elif self.update_type == UpdateType.TO_FROM_DEVICE:
            # synchronize inbetween source and sink -> before the start of sink CU
            update_position = pet.node_at(self.sink_cu_id).start_position()
        elif self.update_type == UpdateType.ALLOCATE:
            update_position = pet.node_at(self.sink_cu_id).start_position()
        else:
            # updating inbetween both CUs should be a safe fallback
            update_position = pet.node_at(self.sink_cu_id).start_position()

        return (
            self.synchronous_source_cu_id,
            self.sink_cu_id,
            self.update_type,
            ",".join(modified_var_names),
            update_position,
        )

    def get_as_metadata_using_variable_names_and_memory_regions(
        self, pet: PEGraphX, project_folder_path: str
    ) -> Tuple[NodeID, NodeID, UpdateType, str, LineID]:
        # get type of mapped variables
        var_names_types_and_sizes: List[Tuple[VarName, str, int]] = []
        for var_name in self.variable_names:
            var_obj = get_variable(pet, self.sink_cu_id, var_name)
            source_cu_id = (
                self.asynchronous_source_cu_id if self.asynchronous_possible else self.synchronous_source_cu_id
            )
            if var_obj is None:
                var_obj = get_variable(pet, cast(NodeID, source_cu_id), var_name)
            if var_obj is None:
                var_names_types_and_sizes.append((var_name, "", 1))
            else:
                var_names_types_and_sizes.append((var_name, var_obj.type, var_obj.sizeInByte))
        # add [..] to variable name if required (type contains "**")

        # get size of memory region
        memory_region_sizes = get_sizes_of_memory_regions(
            self.memory_regions, os.path.join(project_folder_path, "profiler/memory_regions.txt")
        )
        if len(memory_region_sizes) > 0:
            max_mem_reg_size = max(memory_region_sizes.values())
            # divide memory region size by size of variable
            # construct new list of modified var names
            modified_var_names = [
                (
                    vn + "[:]" if "**" in t else vn
                )  # (vn + "[:" + str(int(max_mem_reg_size / s)) + "]" if "**" in t else vn)
                for vn, t, s in var_names_types_and_sizes
            ]
        else:
            modified_var_names = [(vn + "[:]" if "**" in t else vn) for vn, t, s in var_names_types_and_sizes]

        return (
            self.synchronous_source_cu_id,
            self.sink_cu_id,
            self.update_type,
            str(modified_var_names) + "/" + str(self.memory_regions),
            pet.node_at(self.synchronous_source_cu_id).end_position(),
        )

    def convert_memory_regions_to_variable_names(
        self,
        pet: PEGraphX,
        memory_regions_to_functions_and_variables: Dict[MemoryRegion, Dict[NodeID, Set[VarName]]],
    ) -> None:
        self.variable_names = set()
        parent_function_id = get_parent_function(pet, pet.node_at(self.synchronous_source_cu_id)).id

        for mem_reg in self.memory_regions:
            if parent_function_id in memory_regions_to_functions_and_variables[mem_reg]:
                self.variable_names.update(memory_regions_to_functions_and_variables[mem_reg][parent_function_id])
            elif self.synchronous_source_cu_id in memory_regions_to_functions_and_variables[mem_reg]:
                self.variable_names.update(
                    memory_regions_to_functions_and_variables[mem_reg][self.synchronous_source_cu_id]
                )
            elif self.sink_cu_id in memory_regions_to_functions_and_variables[mem_reg]:
                self.variable_names.update(memory_regions_to_functions_and_variables[mem_reg][self.sink_cu_id])
            else:
                self.variable_names.add(VarName("UNDETERMINED(" + mem_reg + ")"))

    def remove_dummy_marks(self) -> None:
        if self.sink_cu_id.startswith("dummy:"):
            self.sink_cu_id = NodeID(self.sink_cu_id[6:])
        if self.synchronous_source_cu_id.startswith("dummy:"):
            self.synchronous_source_cu_id = NodeID(self.synchronous_source_cu_id[6:])

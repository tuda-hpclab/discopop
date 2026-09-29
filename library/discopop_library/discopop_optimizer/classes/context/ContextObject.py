# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
from typing import Dict, Set, List, Optional
import warnings


from sympy import Expr, Integer, Symbol  # type: ignore
import networkx as nx  # type: ignore

from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.Update import Update
from discopop_library.discopop_optimizer.classes.types.Aliases import DeviceID
from discopop_library.discopop_optimizer.classes.types.DataAccessType import (
    WriteDataAccess,
    ReadDataAccess,
)
from discopop_library.discopop_optimizer.utilities.simple_utilities import data_at


class ContextObject(object):
    last_visited_node_id: int
    last_visited_device_id: DeviceID
    last_seen_device_ids: List[DeviceID]
    seen_writes_by_device: Dict[DeviceID, Dict[MemoryRegion, Set[WriteDataAccess]]]
    necessary_updates: Set[Update]

    def __init__(self, initializing_node_id: int, last_seen_device_ids: Optional[List[DeviceID]] = None):
        self.seen_writes_by_device = dict()
        self.necessary_updates = set()
        self.last_visited_node_id = initializing_node_id
        self.last_visited_device_id = None
        self.last_seen_device_ids = last_seen_device_ids if last_seen_device_ids is not None else []
        self.snapshot_stack = []  # type: ignore
        self.save_stack = []  # type: ignore  # list of lists of ContextObjects, one list per branching depth

    def __str__(self) -> str:
        return str(self.necessary_updates)

    def calculate_and_perform_necessary_updates(
        self,
        node_reads: Set[ReadDataAccess],
        reading_device_id: int,
        reading_node_id: int,
        graph: nx.DiGraph,
        experiment: Experiment,
        updates_originated_from: Optional[int] = None,
    ) -> ContextObject:
        """checks if the specified list of ReadDataAccesses performed by the specified device id makes updates
        necessary. If so, the updates will get append to the list of updates of the current ContextObject.
        The list of seen writes by device of the ContextObject will be updated to reflect the identified data transfers.
        A reference to the object is returned."""
        required_updates: Set[Update] = set()
        for read in node_reads:
            # check if the reading device has the latest view of the memory
            for device_id in self.__get_known_device_ids():
                # todo test
                required_updates = set()

                if device_id == reading_device_id:
                    continue

                if read.memory_region not in self.get_seen_writes_by_device(device_id):
                    # read memory region is currently "unknown" to the device, thus is can be skipped
                    continue

                other_devices_known_writes = self.get_seen_writes_by_device(device_id)[read.memory_region]

                is_first_data_occurrence = False
                if read.memory_region not in self.get_seen_writes_by_device(reading_device_id):
                    # reading device does not currently "know" about the read memory region. create a new entry.
                    self.initialize_seen_writes_by_device(reading_device_id, read.memory_region)
                    is_first_data_occurrence = True

                known_writes = self.get_seen_writes_by_device(reading_device_id)[read.memory_region]
                unknown_writes = other_devices_known_writes.difference(known_writes)

                # todo debug: test: only consider the "latest" write
                unknown_writes_dict = dict()
                for entry in unknown_writes:
                    if entry.memory_region not in unknown_writes_dict:
                        unknown_writes_dict[entry.memory_region] = entry
                    else:
                        if unknown_writes_dict[entry.memory_region].unique_id < entry.unique_id:
                            # replace old write with "newer" write
                            unknown_writes_dict[entry.memory_region] = entry

                # unknown_writes = {max(unknown_writes, key=lambda x: x.unique_id)}
                unknown_writes = set(unknown_writes_dict.values())

                for data_write in unknown_writes:
                    # if device <-> device update is required, split it into two distinct updates
                    if (
                        device_id != experiment.get_system().get_host_device_id()
                        and reading_device_id != experiment.get_system().get_host_device_id()
                    ):
                        #                         print("Device <-> Device update required!")

                        # check if data is known to the host
                        if data_write.memory_region not in self.get_seen_writes_by_device(
                            experiment.get_system().get_host_device_id()
                        ):
                            self.initialize_seen_writes_by_device(
                                experiment.get_system().get_host_device_id(), data_write.memory_region
                            )
                        if (
                            data_write
                            not in self.get_seen_writes_by_device(experiment.get_system().get_host_device_id())[
                                data_write.memory_region
                            ]
                        ):
                            # register source device -> host update
                            required_updates.add(
                                Update(
                                    source_node_id=self.last_visited_node_id,
                                    target_node_id=reading_node_id,
                                    source_device_id=device_id,
                                    target_device_id=experiment.get_system().get_host_device_id(),  # reading_device_id,
                                    write_data_access=data_write,
                                    is_first_data_occurrence=is_first_data_occurrence,
                                    source_cu_id=data_at(graph, self.last_visited_node_id).original_cu_id,
                                    target_cu_id=data_at(graph, reading_node_id).original_cu_id,
                                    originated_from_node=updates_originated_from,
                                )
                            )
                        #                        else:
                        #                            print(
                        #                                "SKIPPED KNOWN WRITE: ",
                        #                                str(
                        #                                    Update(
                        #                                        source_node_id=self.last_visited_node_id,
                        #                                        target_node_id=reading_node_id,
                        #                                        source_device_id=device_id,
                        #                                        target_device_id=0,  # reading_device_id,
                        #                                        write_data_access=data_write,
                        #                                        is_first_data_occurrence=is_first_data_occurrence,
                        #                                    )
                        #                                ),
                        #                            )

                        # register host -> target device update
                        required_updates.add(
                            Update(
                                source_node_id=self.last_visited_node_id,
                                target_node_id=reading_node_id,
                                source_device_id=0,  # device_id,
                                target_device_id=reading_device_id,
                                write_data_access=data_write,
                                is_first_data_occurrence=is_first_data_occurrence,
                                source_cu_id=data_at(graph, self.last_visited_node_id).original_cu_id,
                                target_cu_id=data_at(graph, reading_node_id).original_cu_id,
                                originated_from_node=updates_originated_from,
                            )
                        )

                    else:
                        # Host -> Device or Device -> Host update
                        required_updates.add(
                            Update(
                                source_node_id=self.last_visited_node_id,
                                target_node_id=reading_node_id,
                                source_device_id=device_id,
                                target_device_id=reading_device_id,
                                write_data_access=data_write,
                                is_first_data_occurrence=is_first_data_occurrence,
                                source_cu_id=data_at(graph, self.last_visited_node_id).original_cu_id,
                                target_cu_id=data_at(graph, reading_node_id).original_cu_id,
                                originated_from_node=updates_originated_from,
                            )
                        )

                # todo: check if this is sufficient
                for update in required_updates:
                    if update.write_data_access.memory_region not in self.get_seen_writes_by_device(
                        update.target_device_id
                    ):
                        self.initialize_seen_writes_by_device(
                            update.target_device_id, update.write_data_access.memory_region
                        )
                    if update.target_device_id is None:
                        raise ValueError("Value is None")
                    self.__add_seen_write(
                        update.target_device_id, update.write_data_access.memory_region, update.write_data_access
                    )

                self.necessary_updates.update(required_updates)

        return self

    def add_writes(self, node_writes: Set[WriteDataAccess], writing_device_id: int) -> ContextObject:
        """Add the specified writes to the list of seen writes of the given device
        and returns a reference to this ContextObject."""
        # check if the device is known to the context
        if writing_device_id not in self.seen_writes_by_device:
            self.seen_writes_by_device[writing_device_id] = dict()

        for write in node_writes:
            # check if memory region is already present in self.seen_writes_by_device before adding the write access
            if write.memory_region not in self.get_seen_writes_by_device(writing_device_id):
                self.initialize_seen_writes_by_device(writing_device_id, write.memory_region)
            # add write to the list of seen writes
            self.__add_seen_write(writing_device_id, write.memory_region, write)
        return self

    def set_last_visited_node_id(self, node_id: int) -> None:
        self.last_visited_node_id = node_id

    def get_seen_writes_by_device(self, device_id: DeviceID) -> Dict[MemoryRegion, Set[WriteDataAccess]]:
        seen_dict: Dict[MemoryRegion, Set[WriteDataAccess]] = dict()

        # collect seen writes from stack
        for stack_entry in self.snapshot_stack:
            if device_id in stack_entry[0]:
                for memory_region in stack_entry[0][device_id]:
                    if memory_region not in seen_dict:
                        seen_dict[memory_region] = set()
                    seen_dict[memory_region].update(stack_entry[0][device_id][memory_region])

        # collect seen writes from self
        if device_id in self.seen_writes_by_device:
            for memory_region in self.seen_writes_by_device[device_id]:
                if memory_region not in seen_dict:
                    seen_dict[memory_region] = set()
                seen_dict[memory_region].update(self.seen_writes_by_device[device_id][memory_region])

        return seen_dict

    def initialize_seen_writes_by_device(self, device_id: DeviceID, memory_region: MemoryRegion) -> None:
        if device_id not in self.seen_writes_by_device:
            self.seen_writes_by_device[device_id] = dict()
        self.seen_writes_by_device[device_id][memory_region] = set()

    def __add_seen_write(self, device_id: int, memory_region: MemoryRegion, write: WriteDataAccess) -> None:
        if device_id not in self.seen_writes_by_device:
            self.seen_writes_by_device[device_id] = dict()
        if memory_region not in self.seen_writes_by_device[device_id]:
            self.seen_writes_by_device[device_id][memory_region] = set()
        self.seen_writes_by_device[device_id][memory_region].add(write)

    def __get_known_device_ids(self) -> Set[DeviceID]:
        seen_devices: Set[DeviceID] = set()
        for stack_entry in self.snapshot_stack:
            for device_id in stack_entry[0]:
                seen_devices.add(device_id)

        for device_id in self.seen_writes_by_device:
            seen_devices.add(device_id)

        return seen_devices

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Optional
from discopop_explorer.classes.patterns.PatternBase import PatternBase

from discopop_library.discopop_optimizer.classes.system.devices.DeviceTypeEnum import DeviceTypeEnum

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.utils import calculate_workload, calculate_per_iteration_workload_of_loop


class PatternInfo(PatternBase):
    """Base class for pattern detection info"""

    iterations_count: int
    average_iteration_count: int
    entries: int
    instructions_count: Optional[int]
    workload: Optional[int]
    per_iteration_workload: Optional[int]
    dp_optimizer_device_id: Optional[int] = None  # used by discopop_optimizer. unused by discopop_explorer.
    device_id: Optional[int]
    device_type: Optional[DeviceTypeEnum]

    def __init__(self, node: Node):
        """
        :param node: node, where pipeline was detected
        """
        PatternBase.__init__(self, node)

        self.average_iteration_count = (
            node.loop_data.average_iteration_count
            if (isinstance(node, LoopNode) and node.loop_data is not None)
            else -1
        )
        self.iterations_count = (
            node.loop_data.total_iteration_count if (isinstance(node, LoopNode) and node.loop_data is not None) else -1
        )
        self.entries = node.loop_data.entry_count if (isinstance(node, LoopNode) and node.loop_data is not None) else -1

        # TODO self.instructions_count = total_instructions_count(pet, node)
        self.workload = None
        self.per_iteration_workload: Optional[int] = None
        # TODO self.workload = calculate_workload(pet, node)

        self.device_id = None
        self.device_type = None

    def get_workload(self, pet: PEGraphX) -> int:
        """returns the workload of self._node"""
        if self.workload is not None:
            return self.workload
        try:
            self.workload = calculate_workload(pet, self._node)
        except RecursionError as rerr:
            import warnings

            warnings.warn("Cost calculation not possible for node: " + str(self._node.id) + "!")
            self.workload = 0

        return self.workload

    def get_per_iteration_workload(self, pet: PEGraphX) -> int:
        """returns the per iteration workload of self"""
        if self.per_iteration_workload is not None:
            return self.per_iteration_workload
        self.per_iteration_workload = calculate_per_iteration_workload_of_loop(pet, self._node)
        return self.per_iteration_workload

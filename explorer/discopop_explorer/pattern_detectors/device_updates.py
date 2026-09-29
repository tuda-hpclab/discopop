# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Optional

from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.LineID import LineID


class DeviceUpdateInfo(PatternInfo):
    """Class, that contains omp device updates"""

    def __init__(
        self,
        pet: PEGraphX,
        source_node: Node,
        target_node: Node,
        mem_reg: MemoryRegion,
        var_name: Optional[str],
        source_device_id: int,
        target_device_id: int,
        start_line: LineID,
        end_line: LineID,
        is_first_data_occurrence: bool,
        openmp_source_device_id: int,
        openmp_target_device_id: int,
    ):
        """
        :param pet: PET graph
        :param source_node: node, where data originates
        :param target_node: node, where data is required
        """
        PatternInfo.__init__(self, source_node)
        self.source_node_id = source_node.id
        self.target_node_id = target_node.id
        self.mem_reg = mem_reg
        self.var_name = var_name
        self.source_device_id = source_device_id
        self.target_device_id = target_device_id
        # overwrite start and end lines set by PatternInfo
        self.start_line = start_line
        self.end_line = end_line
        self.is_first_data_occurrence = is_first_data_occurrence
        self.openmp_source_device_id = openmp_source_device_id
        self.openmp_target_device_id = openmp_target_device_id

    def __str__(self) -> str:
        return (
            # f"Device update at: {self.node_id}\n" # removed to allow reduction of duplicates in the generated OpenMP code in CodeGenerator
            f"Start line: {self.start_line}\n"
            f"End line: {self.end_line}\n"
            # f"source_node: {self.source_node_id}\n"  # removed to allow reduction of duplicates in the generated OpenMP code in CodeGenerator
            # f"target_node: {self.target_node_id}\n"  # removed to allow reduction of duplicates in the generated OpenMP code in CodeGenerator
            f"source_device: {self.source_device_id}\n"
            f"target_device: {self.target_device_id}\n"
            # f"mem_reg: {self.mem_reg}\n"  # removed to allow reduction of duplicates in the generated OpenMP code in CodeGenerator
            f"var_name: {self.var_name}\n"
            f"is_first_data_occurrence: {self.is_first_data_occurrence}\n"
            f"openmp_source_device_id: {self.openmp_source_device_id}\n"
            f"openmp_target_device_id: {self.openmp_target_device_id}"
        )

    def get_str_without_first_data_occurrence(self) -> str:
        return (
            f"Start line: {self.start_line}\n"
            f"End line: {self.end_line}\n"
            f"source_device: {self.source_device_id}\n"
            f"target_device: {self.target_device_id}\n"
            f"var_name: {self.var_name}\n"
            f"openmp_source_device_id: {self.openmp_source_device_id}\n"
            f"openmp_target_device_id: {self.openmp_target_device_id}"
        )

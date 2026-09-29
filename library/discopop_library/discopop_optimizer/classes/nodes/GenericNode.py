# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
from typing import Optional, List, Set

from sympy import Symbol, Function, Integer  # type: ignore

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    print("TYPE CHECKING")
    from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
    from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.system.devices.Device import Device
from discopop_library.discopop_optimizer.classes.types.Aliases import DeviceID
from discopop_library.discopop_optimizer.classes.types.DataAccessType import (
    ReadDataAccess,
    WriteDataAccess,
)


class GenericNode(object):
    node_id: int  # id of the node in the nx.DiGraph which stores this object  # environment object to retrieve and store free symbols and other configurable values
    ## Performance modelling
    introduced_symbols: List[Symbol]
    performance_model: CostModel
    ## Data transfer calculation
    written_memory_regions: Set[WriteDataAccess]
    read_memory_regions: Set[ReadDataAccess]
    device_id: DeviceID
    execute_in_parallel: bool
    branch_affiliation: List[int]

    def __init__(
        self,
        node_id: int,
        experiment: Experiment,
        cu_id: Optional[NodeID] = None,
        written_memory_regions: Optional[Set[WriteDataAccess]] = None,
        read_memory_regions: Optional[Set[ReadDataAccess]] = None,
        device_id: DeviceID = None,
    ):
        self.node_id = node_id
        self.cu_id = cu_id  # used to differentiate between "legacy" and suggestion nodes
        self.original_cu_id = cu_id  # used for the creation of update suggestions
        self.introduced_symbols = []
        self.performance_model = CostModel(Integer(0), Integer(0))
        self.suggestion: Optional[PatternInfo] = None
        self.suggestion_type: Optional[str] = None
        self.branch_affiliation = []
        self.execute_in_parallel = False

        if written_memory_regions is None:
            self.written_memory_regions = set()
        else:
            self.written_memory_regions = written_memory_regions
            # register free variables for memory region sizes
            for memory_region in [wmr.memory_region for wmr in written_memory_regions]:
                experiment.get_memory_region_size(memory_region, use_symbolic_value=True)

        if read_memory_regions is None:
            self.read_memory_regions = set()
        else:
            self.read_memory_regions = read_memory_regions
            # register free variables for memory region sizes
            for memory_region in [rmr.memory_region for rmr in read_memory_regions]:
                experiment.get_memory_region_size(memory_region, use_symbolic_value=True)

        self.device_id = device_id

    def get_plot_label(self) -> str:
        return ""

    def get_hover_text(self) -> str:
        return ""

    def get_cost_model(
        self, experiment: Experiment, all_function_nodes: List[FunctionRoot], current_device: Device
    ) -> CostModel:
        raise NotImplementedError("Implementation needs to be provided by derived class: !", type(self))

    def register_child(
        self, other: CostModel, experiment: Experiment, all_function_nodes: List[FunctionRoot], current_device: Device
    ) -> CostModel:
        """Registers a child node for the given model.
        Does not modify the stored model in self or other."""
        raise NotImplementedError("Implementation needs to be provided by derived class: !", type(self))

    def register_successor(self, other: CostModel) -> CostModel:
        """Registers a successor node for the given model.
        Does not modify the stored model in self or other."""
        raise NotImplementedError("Implementation needs to be provided by derived class: !", type(self))

    def represents_sequential_version(self) -> bool:
        """Returns True if the given node represents a sequential execution.
        Returns False, if the node characterizes a parallel option instead."""
        return self.suggestion is None

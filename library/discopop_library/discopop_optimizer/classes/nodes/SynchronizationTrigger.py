# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Optional, Set

from sympy import Function, Symbol, Integer, Expr  # type: ignore
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.types.DataAccessType import WriteDataAccess  # type: ignore

from discopop_explorer.aliases.NodeID import NodeID
from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.classes.nodes.Workload import Workload
from discopop_library.discopop_optimizer.classes.types.DataAccessType import ReadDataAccess


class SynchronizationTrigger(Workload):
    def __init__(
        self,
        node_id: int,
        experiment: Experiment,
        cu_id: Optional[NodeID],
        sequential_workload: Optional[Expr],
        parallelizable_workload: Optional[Expr],
        written_memory_regions: Optional[Set[WriteDataAccess]] = None,
        read_memory_regions: Optional[Set[ReadDataAccess]] = None,
    ):
        super().__init__(
            node_id=node_id,
            experiment=experiment,
            cu_id=cu_id,
            sequential_workload=sequential_workload,
            parallelizable_workload=parallelizable_workload,
            written_memory_regions=written_memory_regions,
            read_memory_regions=read_memory_regions,
        )

    def get_plot_label(self) -> str:
        return "SYNC\n" + str(self.original_cu_id)

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import List, Optional

from sympy import Symbol, Integer, Expr, Float  # type: ignore

from discopop_explorer.aliases.NodeID import NodeID
from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.discopop_optimizer.classes.nodes.Workload import Workload
from discopop_library.discopop_optimizer.classes.system.devices.Device import Device


class Loop(Workload):
    iterations: int
    position: str
    iterations_symbol: Symbol
    registered_child: Optional[CostModel]
    collapse_level: int

    def __init__(
        self,
        node_id: int,
        experiment: Experiment,
        cu_id: Optional[NodeID],
        discopop_workload: int,
        iterations: int,
        position: str,
        iterations_symbol: Optional[Symbol] = None,
        collapse_level: int = 1,
    ):
        self.position = position
        self.iterations = max(iterations, 1)  # to prevent dividing by 0 in case the loop has not been executed
        self.collapse_level = collapse_level

        if iterations_symbol is None:
            self.iterations_symbol = Symbol("loop_" + str(node_id) + "_pos_" + str(self.position) + "_iterations")
        else:
            self.iterations_symbol = iterations_symbol

        # create parallelizable_workload_symbol
        self.per_iteration_parallelizable_workload = Symbol(
            "loop_" + str(node_id) + "_pos_" + str(self.position) + "_per_iteration_parallelizable_workload"
        )
        self.per_iteration_sequential_workload = Symbol(
            "loop_" + str(node_id) + "_pos_" + str(self.position) + "_per_iteration_sequential_workload"
        )

        # calculate workload per iteration
        per_iteration_parallelizable_workload = discopop_workload / iterations

        super().__init__(
            node_id,
            experiment,
            cu_id,
            sequential_workload=self.per_iteration_sequential_workload,
            parallelizable_workload=self.per_iteration_parallelizable_workload,
            #            int(
            #                # per_iteration_parallelizable_workload
            #            ),  # todo this might be wrong! should be 1 instead, since children are registered individually
        )

        # register iteration symbol in environment
        experiment.register_free_symbol(self.iterations_symbol, value_suggestion=Integer(self.iterations))
        # register per iteration parallelizable workload symbol in environment
        experiment.register_free_symbol(
            self.per_iteration_parallelizable_workload,
            value_suggestion=Float(per_iteration_parallelizable_workload),
        )
        experiment.substitutions[self.per_iteration_sequential_workload] = Integer(0)
        self.registered_child = None

    # todo: note: it might be more beneficial to use the iterations "per entry" instead of the total amount of iterations
    # example:
    # for(100)      --> use 100
    #   for(100)    --> use 100 instead of 10000

    def get_hover_text(self) -> str:
        return (
            "WL: " + str(self.sequential_workload) + "\n" + "IT: " + str(self.iterations) + "\n"
            "Read: " + str([str(e) for e in self.read_memory_regions]) + "\n"
            "Write: " + str([str(e) for e in self.written_memory_regions]) + "\n"
            "Suggestion: " + str(self.suggestion) + "\n"
            "Collapse: " + str(self.collapse_level) + "\n"
            "Device ID: " + str(self.device_id)
        )

    def get_cost_model(
        self, experiment: Experiment, all_function_nodes: List[FunctionRoot], current_device: Device
    ) -> CostModel:
        """Performance model of a workload consists of the workload itself.
        Individual Workloads are assumed to be not parallelizable.
        Workloads of Loop etc. are parallelizable."""

        # loop costs = self.sequential + overhead + iterations * per_iteration_workload * cost_modifier

        cm = CostModel(
            self.iterations_symbol
            * self.per_iteration_parallelizable_workload
            * self.cost_multiplier.parallelizable_costs,
            self.sequential_workload
            + self.overhead.sequential_costs
            + self.per_iteration_sequential_workload * self.iterations_symbol,
        )

        # substitute Expr(0) with Integer(0)
        cm.parallelizable_costs = cm.parallelizable_costs.subs({Expr(Integer(0)): Integer(0)})
        cm.sequential_costs = cm.sequential_costs.subs({Expr(Integer(0)): Integer(0)})

        return cm

    def register_child(
        self, other: CostModel, experiment: Experiment, all_function_nodes: List[FunctionRoot], current_device: Device
    ) -> CostModel:
        """Registers a child node for the given model.
        Does not modify the stored model in self or other."""

        # at every time, only a single child is possible for each loop node
        self.registered_child = other
        experiment.substitutions[self.per_iteration_parallelizable_workload] = other.parallelizable_costs
        experiment.substitutions[self.per_iteration_sequential_workload] = other.sequential_costs

        cm = self.get_cost_model(experiment, all_function_nodes, current_device)
        cm.path_decisions += other.path_decisions
        return cm

    def register_successor(self, other: CostModel) -> CostModel:
        """Registers a successor node for the given model.
        Does not modify the stored model in self or other."""
        # sequential composition is depicted by simply adding the performance models
        return self.performance_model.parallelizable_plus_combine(other)

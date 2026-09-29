# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
import random
import sys
from typing import Any, List, Dict, TextIO, Tuple, Optional

import numpy as np
import sympy  # type: ignore
from matplotlib import pyplot as plt  # type: ignore
from sympy import Function, Symbol, init_printing, Expr, N, nsimplify, Integer  # type: ignore
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
    from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
    from discopop_library.discopop_optimizer.classes.nodes.GenericNode import GenericNode

from discopop_library.discopop_optimizer.classes.enums.Distributions import FreeSymbolDistribution
from discopop_library.discopop_optimizer.classes.system.devices.Device import Device


class CostModel(object):
    path_decisions: List[int]
    identifier: str
    parallelizable_costs: Expr
    sequential_costs: Expr
    raw_parallelizable_costs: Optional[Expr]
    raw_sequential_costs: Optional[Expr]
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]]
    free_symbol_distributions: Dict[Symbol, FreeSymbolDistribution]
    symbol_value_suggestions: Dict[Symbol, Expr]

    def toJSON(self) -> str:
        return "AsDF"

    def __init__(
        self,
        parallelizable_costs: Expr,
        sequential_costs: Expr,
        identifier: str = "None",
        path_decisions: Optional[List[int]] = None,
        symbol_value_suggestions: Optional[Dict[Symbol, Expr]] = None,
    ) -> None:
        if sequential_costs == sympy.nan:
            raise ValueError("NAN: ", sequential_costs)
        if path_decisions is None:
            self.path_decisions = []
        else:
            # used for the construction of combined models
            self.path_decisions = path_decisions
        if symbol_value_suggestions is None:
            self.symbol_value_suggestions = dict()
        else:
            self.symbol_value_suggestions = symbol_value_suggestions
        self.identifier = identifier
        self.parallelizable_costs = parallelizable_costs
        self.sequential_costs = sequential_costs

    def __str__(self) -> str:
        return str(self.parallelizable_costs) + str(self.sequential_costs)

    def print(self, file: TextIO = sys.stdout) -> None:
        init_printing()
        print("\tPARALLEL:")
        print("\t", self.parallelizable_costs, file=file)
        print("\tSERIAL")
        print("\t", self.sequential_costs, file=file)

    def parallelizable_plus_combine(self, other: CostModel) -> CostModel:
        """Combines both models in the following fashion:
        f(x,y) =
        ==> x.parallelizable_costs + y.parallelizable_costs
        ==> x.sequential_costs + y.sequential_costs"""
        if other is None:
            return self
        parallelizable_costs = self.parallelizable_costs + other.parallelizable_costs
        sequential_costs = self.sequential_costs + other.sequential_costs
        path_decisions = self.path_decisions + other.path_decisions
        # merge dictionaries
        value_suggestions = {**self.symbol_value_suggestions, **other.symbol_value_suggestions}
        return CostModel(
            parallelizable_costs,
            sequential_costs,
            path_decisions=path_decisions,
            symbol_value_suggestions=value_suggestions,
        )

    def parallelizable_divide_combine(self, other: CostModel) -> CostModel:
        """Combines both models in the following fashion:
        f(x,y) =
        ==> x.parallelizable_costs / y.parallelizable_costs
        ==> x.sequential_costs / y.sequential_costs"""
        if other is None:
            return self
        parallelizable_costs = self.parallelizable_costs / other.parallelizable_costs
        sequential_costs = self.sequential_costs / other.sequential_costs
        path_decisions = self.path_decisions + other.path_decisions
        value_suggestions = self.symbol_value_suggestions | other.symbol_value_suggestions
        return CostModel(
            parallelizable_costs,
            sequential_costs,
            path_decisions=path_decisions,
            symbol_value_suggestions=value_suggestions,
        )

    def parallelizable_multiply_combine(self, other: CostModel) -> CostModel:
        """Combines both models in the following fashion:
        f(x,y) =
        ==> x.parallelizable_costs * y.parallelizable_costs
        ==> x.sequential_costs * y.sequential_costs"""
        if other is None:
            return self
        parallelizable_costs = self.parallelizable_costs * other.parallelizable_costs
        sequential_costs = self.sequential_costs * other.sequential_costs
        path_decisions = self.path_decisions + other.path_decisions
        # merge dictionaries
        value_suggestions = {**self.symbol_value_suggestions, **other.symbol_value_suggestions}
        return CostModel(
            parallelizable_costs,
            sequential_costs,
            path_decisions=path_decisions,
            symbol_value_suggestions=value_suggestions,
        )

    def register_child(
        self,
        other: CostModel,
        root_node: GenericNode,
        experiment: Experiment,
        all_function_nodes: List[FunctionRoot],
        current_device: Device,
    ) -> CostModel:
        """Registers a child node for the given model.
        Does not modify the stored model in self or other."""
        return root_node.register_child(other, experiment, all_function_nodes, current_device)

    def register_successor(self, other: CostModel, root_node: GenericNode) -> CostModel:
        """Registers a successor node for the given model.
        Does not modify the stored model in self or other."""
        return root_node.register_successor(other)

    def __lt__(self, other: CostModel) -> bool:
        """Compare both models.
        The comparison is based on random sampling and may not be correct in all cases!
        """
        decision_tendency = 0  # positive -> self was evaluated to be smaller more often than the other way around
        decided = False
        counter = 0
        # Sampling parameters
        min_count = 50
        max_count = 300
        decision_threshold = 0.85
        # Weibull distribution parameters
        alpha, beta = 0.8, 1.3

        # draw and evaluate random samples until either the max_count has been reached, or a decision has been made
        # sampling points may be drawn from a uniform or weibull distribution in a left-skewed or right-skewed
        # configuration. The Parameters of the weibull distribution can be defined above.
        while not (decided or counter > max_count) or counter < min_count:
            counter += 1
            # determine random sampling point
            sampling_point = dict()
            for symbol in self.free_symbol_ranges:
                range_min, range_max = self.free_symbol_ranges[symbol]
                if self.free_symbol_distributions[symbol] == FreeSymbolDistribution.UNIFORM:
                    # draw from uniform distribution
                    sampling_point[symbol] = random.uniform(range_min, range_max)
                else:
                    # use_weibull_distribution
                    # get normalized random value from distribution
                    normalized_pick = 42.0
                    while normalized_pick < 0 or normalized_pick > 1:
                        normalized_pick = random.weibullvariate(alpha, beta)
                    if self.free_symbol_distributions[symbol] == FreeSymbolDistribution.LEFT_HEAVY:
                        # calculate sampling point using the range starting from minimum
                        sampling_point[symbol] = range_min + (range_max - range_min) * normalized_pick
                    else:
                        # simulate a right heavy distribution
                        # calculate sampling point using the range starting from maximum
                        sampling_point[symbol] = range_max - (range_max - range_min) * normalized_pick

            # evaluate both functions at the sampling point
            substituted_model_1_1 = self.parallelizable_costs.xreplace(sampling_point)
            numerical_result_1_1 = substituted_model_1_1.evalf()

            substituted_model_1_2 = self.sequential_costs.xreplace(sampling_point)
            numerical_result_1_2 = substituted_model_1_2.evalf()

            substituted_model_2_1 = other.parallelizable_costs.xreplace(sampling_point)
            numerical_result_2_1 = substituted_model_2_1.evalf()

            substituted_model_2_2 = other.sequential_costs.xreplace(sampling_point)
            numerical_result_2_2 = substituted_model_2_2.evalf()

            # use re() to get real values in case extrap has introduced sqrt's
            total_1 = sympy.re(numerical_result_1_1 + numerical_result_1_2) + sympy.im(
                numerical_result_1_1 + numerical_result_1_2
            )
            total_2 = sympy.re(numerical_result_2_1 + numerical_result_2_2) + sympy.im(
                numerical_result_2_1 + numerical_result_2_2
            )

            # replace Expr(0) with 0
            total_1 = total_1.subs({Expr(Integer(0)): Integer(0)})
            total_2 = total_2.subs({Expr(Integer(0)): Integer(0)})

            # determine relation between the numerical results
            try:
                if total_1 < total_2:
                    decision_tendency += 1
                else:
                    decision_tendency -= 1
            except TypeError as te:
                print("Total 1: ", total_1)
                print("Total 2: ", total_2)
                raise te

            if counter > min_count:
                # check if a decision in either direction can be made
                if decision_threshold < (abs(decision_tendency) / counter):
                    decided = True

        # check if a decision has been made
        if decided:
            if decision_tendency > 0:
                return True
            else:
                return False
        else:
            return False

    def __plot_weibull_distributions(self, alpha: float, beta: float) -> None:
        """For Debug reasons. Plots the left and right side heavy weibull distributions using the given parameters."""
        x = np.arange(1, 100.0) / 100.0  # normalized to [0,1]

        def weibull(x: Any, n: float, a: float) -> Any:
            return (a / n) * (x / n) ** (a - 1) * np.exp(-((x / n) ** a))

        plt.plot(x, weibull(x, alpha, beta), label="Alpha: " + str(alpha) + " Beta: " + str(beta))

        # show random picks
        ax = plt.subplot(1, 1, 1)  # type: ignore
        k = 100
        for i in range(0, k):
            # get normalized values
            y_rnd = 42.0
            while y_rnd < 0 or y_rnd > 1:
                y_rnd = random.weibullvariate(alpha, beta)
            ax.plot(y_rnd, 1, "or")
        plt.legend()
        plt.show()

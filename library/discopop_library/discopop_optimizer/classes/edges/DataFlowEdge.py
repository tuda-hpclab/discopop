# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from sympy import Symbol  # type: ignore

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.classes.edges.GenericEdge import GenericEdge


class DataFlowEdge(GenericEdge):
    """Used to represent data flow in the Graph. Used to determine cutoff points for local optimization"""

    def get_cost_model(self) -> CostModel:
        raise ValueError("The cost of a DataFlowEdge is not defined and may never be used!")

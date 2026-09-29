# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from sympy import Integer  # type: ignore

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel


class GenericEdge(object):
    pass

    def get_cost_model(self) -> CostModel:
        return CostModel(Integer(0), Integer(0))

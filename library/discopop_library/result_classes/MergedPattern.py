# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


from typing import List
from discopop_explorer.classes.PEGraph.Node import Node

from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.result_classes.OptimizerOutputPattern import OptimizerOutputPattern


class MergedPattern(OptimizerOutputPattern):
    def __init__(self, node: Node, decisions: List[int], host_device_id: int, experiment: Experiment):
        OptimizerOutputPattern.__init__(self, node, decisions, host_device_id, experiment)

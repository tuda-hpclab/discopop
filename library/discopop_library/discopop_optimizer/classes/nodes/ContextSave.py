# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import copy
import warnings

import networkx as nx  # type: ignore

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject
from discopop_library.discopop_optimizer.classes.nodes.ContextNode import ContextNode
from discopop_library.discopop_optimizer.utilities.MOGUtilities import show


class ContextSave(ContextNode):
    def __init__(self, node_id: int, experiment: Experiment):
        super().__init__(node_id, experiment)

    def get_plot_label(self) -> str:
        return str(self.node_id) + "\nCTX\nsave"

    def get_modified_context(
        self, node_id: int, graph: nx.DiGraph, model: CostModel, context: ContextObject
    ) -> ContextObject:
        if len(context.save_stack) < 1:
            warnings.warn("Context can not be saved to an empty stack!")
            return context
        context.save_stack[-1].append(
            (context.seen_writes_by_device, context.necessary_updates, context.last_seen_device_ids[-1])
        )
        context.seen_writes_by_device = dict()
        context.necessary_updates = set()
        return context

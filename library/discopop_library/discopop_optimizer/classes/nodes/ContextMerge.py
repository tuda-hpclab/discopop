# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import cast
import warnings

import networkx as nx  # type: ignore

from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.Variables.Experiment import Experiment
from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject
from discopop_library.discopop_optimizer.classes.nodes.ContextNode import ContextNode


class ContextMerge(ContextNode):
    def __init__(self, node_id: int, experiment: Experiment):
        super().__init__(node_id, experiment)

    def get_plot_label(self) -> str:
        return str(self.node_id) + "\nCTX\nmerge"

    def get_modified_context(
        self, node_id: int, graph: nx.DiGraph, model: CostModel, context: ContextObject
    ) -> ContextObject:
        if len(context.snapshot_stack) < 1 or len(context.save_stack) < 1:
            warnings.warn("Context can not be merged before creating a snapshot!")
            return context

        context.last_seen_device_ids = context.snapshot_stack[-1][2]

        for saved_contex in context.save_stack[-1]:
            context.necessary_updates.update(saved_contex[1])
            for device_id in saved_contex[0]:
                if device_id not in context.seen_writes_by_device:
                    context.seen_writes_by_device[device_id] = dict()
                for mem_reg_id in saved_contex[0][device_id]:
                    if mem_reg_id not in context.get_seen_writes_by_device(device_id):
                        context.initialize_seen_writes_by_device(device_id, mem_reg_id)
                    if device_id not in context.seen_writes_by_device:
                        context.seen_writes_by_device[device_id] = dict()
                    if mem_reg_id not in context.seen_writes_by_device[device_id]:
                        context.seen_writes_by_device[device_id][mem_reg_id] = set()
                    context.seen_writes_by_device[device_id][mem_reg_id].update(saved_contex[0][device_id][mem_reg_id])

            context.last_seen_device_ids.append(saved_contex[2])
        return context

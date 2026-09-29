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


class ContextRestore(ContextNode):
    def __init__(self, node_id: int, experiment: Experiment):
        super().__init__(node_id, experiment)

    def get_plot_label(self) -> str:
        return str(self.node_id) + "\nCTX\nrestore"

    def get_modified_context(
        self, node_id: int, graph: nx.DiGraph, model: CostModel, context: ContextObject
    ) -> ContextObject:
        #        # save save_stack in buffer
        #        buffer_save_stack = copy.deepcopy(context.save_stack)
        #        # save snapshot_stack in buffer
        #        buffer_snapshot_stack = copy.deepcopy(context.snapshot_stack)
        #        # restore the latest entry in snapshot_stack
        #        if len(context.snapshot_stack) < 1:
        #            warnings.warn("Context can not be restored before creating a snapshot!")
        #            return context
        #        restored_context: ContextObject = copy.deepcopy(context.snapshot_stack[-1])
        ##
        #        # add buffer to save_stack
        #        restored_context.save_stack += buffer_save_stack
        #        # set snapshot_stack to the buffered contents
        #        restored_context.snapshot_stack = buffer_snapshot_stack
        #        return restored_context

        return context

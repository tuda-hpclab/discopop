# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from discopop_library.ParallelRegionMerger.classes.TaskGraph.ModifierNode import ModifierNode


class FriendlyModifierNode(ModifierNode):
    def __init__(self) -> None:
        super().__init__()

    def get_label(self) -> str:
        return "friendly"

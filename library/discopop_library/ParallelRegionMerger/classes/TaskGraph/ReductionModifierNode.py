# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from discopop_library.ParallelRegionMerger.classes.TaskGraph.ModifierNode import ModifierNode
from discopop_explorer.pattern_detectors.reduction_detector import ReductionInfo


class ReductionModifierNode(ModifierNode):
    reduction_pattern: ReductionInfo

    def __init__(self, reduction_pattern: ReductionInfo) -> None:
        super().__init__()
        self.reduction_pattern = reduction_pattern

    def get_label(self) -> str:
        return self.reduction_pattern.get_tag()

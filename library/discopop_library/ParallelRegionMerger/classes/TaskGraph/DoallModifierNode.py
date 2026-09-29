# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from discopop_library.ParallelRegionMerger.classes.TaskGraph.ModifierNode import ModifierNode
from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo


class DoAllModifierNode(ModifierNode):
    do_all_pattern: DoAllInfo

    def __init__(self, doall_pattern: DoAllInfo) -> None:
        super().__init__()
        self.do_all_pattern = doall_pattern

    def get_label(self) -> str:
        return self.do_all_pattern.get_tag()

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, cast

from discopop_explorer.classes.patterns.PatternBase import PatternBase
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo
from discopop_explorer.pattern_detectors.geometric_decomposition_detector import GDInfo
from discopop_explorer.pattern_detectors.pipeline_detector import PipelineInfo
from discopop_explorer.pattern_detectors.reduction_detector import ReductionInfo
from discopop_library.ParallelRegionMerger.inflated_parallel_region_pattern import ParallelRegionInfo
from discopop_library.Aliases.aliases import PatternID


class PatternStorage(object):
    reduction: List[ReductionInfo]
    do_all: List[DoAllInfo]
    pipeline: List[PipelineInfo]
    geometric_decomposition: List[GDInfo]
    task: List[PatternInfo]
    simple_gpu: List[PatternInfo]
    combined_gpu: List[PatternInfo]
    optimizer_output: List[PatternBase]
    merged_pattern: List[PatternBase]
    parallel_region: List[ParallelRegionInfo]

    def __init__(self) -> None:
        self.optimizer_output = []
        self.merged_pattern = []

    def get_pattern_from_id(self, pattern_id: int) -> PatternBase:
        for type in self.__dict__:
            for suggestion in self.__dict__[type]:
                if suggestion.pattern_id == pattern_id:
                    return cast(PatternBase, suggestion)
        raise ValueError("Pattern not found: " + str(pattern_id))

    def get_pattern_ids(self) -> List[PatternID]:
        result_list: List[PatternID] = []
        for type in self.__dict__:
            for suggestion in self.__dict__[type]:
                result_list.append(suggestion.pattern_id)
        return result_list

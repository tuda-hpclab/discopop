# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
from typing import TYPE_CHECKING
import logging

from discopop_explorer.utilities.statistics.CU_count import get_CU_count
from discopop_explorer.utilities.statistics.DEP_count import get_DEP_count
from discopop_explorer.utilities.statistics.FUNC_count import get_FUNC_count
from discopop_explorer.utilities.statistics.LOOP_count import get_LOOP_count
from discopop_explorer.utilities.statistics.cyclomatic_complexity.boxplot import get_cyclomatic_complexities_for_boxplot
from discopop_explorer.utilities.statistics.cyclomatic_complexity.total import get_summed_cyclomatic_complexity
from discopop_explorer.utilities.statistics.maximum_call_path_depth import get_maximum_call_path_depth
from discopop_explorer.utilities.statistics.num_function_calls import get_suggestion_num_function_calls
from discopop_explorer.utilities.statistics.output_statistics import (
    output_aggregated_suggestion_statistics,
    output_code_statistics,
    output_suggestion_statistics,
)
from discopop_explorer.utilities.statistics.suggestion_call_path_depths import get_suggestion_call_path_depths
from discopop_explorer.utilities.statistics.suggestion_cyclomatic_complexity import (
    get_suggestion_summed_cyclomatic_complexity_from_calls,
)
from discopop_explorer.utilities.statistics.suggestion_lines_of_code import (
    get_suggestion_immediate_lines_of_code,
    get_suggestion_lines_of_code_including_calls,
)

if TYPE_CHECKING:
    from discopop_explorer.discopop_explorer import ExplorerArguments
    from discopop_library.result_classes.DetectionResult import DetectionResult

logger = logging.getLogger("statistics")


def collect_statistics(arguments: ExplorerArguments, res: DetectionResult) -> None:
    logger.info("Collecting code statistics...")

    cu_count = get_CU_count(res.pet)
    logger.debug("--> CU count: " + str(cu_count))

    func_count = get_FUNC_count(res.pet)
    logger.debug("--> FUNC count: " + str(func_count))

    loop_count = get_LOOP_count(res.pet)
    logger.debug("--> LOOP count: " + str(loop_count))

    dependency_count = get_DEP_count(res.pet)
    logger.debug("--> DEP count: " + str(dependency_count))

    maximum_call_path_depth = get_maximum_call_path_depth(res.pet)
    logger.debug("--> maximum_call_path_depth: " + str(maximum_call_path_depth))

    suggestion_call_path_depths = get_suggestion_call_path_depths(res)
    logger.debug(
        "--> suggestion_call_path_depths: "
        + str([str(key) + " => " + str(suggestion_call_path_depths[key]) for key in suggestion_call_path_depths])
    )

    suggestion_num_function_calls = get_suggestion_num_function_calls(res)
    logger.debug(
        "--> suggestion_num_function_calls: "
        + str([str(key) + " => " + str(suggestion_num_function_calls[key]) for key in suggestion_num_function_calls])
    )

    suggestion_immediate_lines_of_code = get_suggestion_immediate_lines_of_code(res)
    logger.debug(
        "--> suggestion_immediate_lines_of_code: "
        + str(
            [
                str(key) + " => " + str(suggestion_immediate_lines_of_code[key])
                for key in suggestion_immediate_lines_of_code
            ]
        )
    )

    suggestion_lines_of_code_including_calls = get_suggestion_lines_of_code_including_calls(res)
    logger.debug(
        "--> suggestion_lines_of_code_including_calls: "
        + str(
            [
                str(key) + " => " + str(suggestion_lines_of_code_including_calls[key])
                for key in suggestion_lines_of_code_including_calls
            ]
        )
    )

    summed_cyclomatic_complexity = get_summed_cyclomatic_complexity(arguments, res)
    logger.debug("--> summed_cyclomatic_complexity = " + str(summed_cyclomatic_complexity))

    cc_min, cc_max, cc_avg, cc_lower_quart, cc_upper_quart = get_cyclomatic_complexities_for_boxplot(arguments, res)
    logger.debug("--> cc_min: " + str(cc_min))
    logger.debug("--> cc_max: " + str(cc_max))
    logger.debug("--> cc_avg: " + str(cc_avg))
    logger.debug("--> cc_lower_quart: " + str(cc_lower_quart))
    logger.debug("--> cc_upper_quart: " + str(cc_upper_quart))

    suggestion_summed_cyclomatic_complexity_from_calls = get_suggestion_summed_cyclomatic_complexity_from_calls(
        arguments, res
    )
    logger.debug(
        "--> suggestion_summed_cyclomatic_complexity_from_calls: "
        + str(
            [
                str(key) + " => " + str(suggestion_summed_cyclomatic_complexity_from_calls[key])
                for key in suggestion_summed_cyclomatic_complexity_from_calls
            ]
        )
    )

    # output statistics to file
    output_code_statistics(
        arguments,
        maximum_call_path_depth,
        summed_cyclomatic_complexity,
        cc_min,
        cc_max,
        cc_avg,
        cc_lower_quart,
        cc_upper_quart,
        cu_count,
        func_count,
        loop_count,
        dependency_count,
    )

    output_suggestion_statistics(
        arguments,
        suggestion_call_path_depths,
        suggestion_num_function_calls,
        suggestion_immediate_lines_of_code,
        suggestion_lines_of_code_including_calls,
        suggestion_summed_cyclomatic_complexity_from_calls,
    )

    output_aggregated_suggestion_statistics(
        arguments,
        suggestion_call_path_depths,
        suggestion_num_function_calls,
        suggestion_immediate_lines_of_code,
        suggestion_lines_of_code_including_calls,
        suggestion_summed_cyclomatic_complexity_from_calls,
    )

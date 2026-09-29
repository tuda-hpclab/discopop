# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
from typing import TYPE_CHECKING, Dict, List, Tuple

if TYPE_CHECKING:
    from discopop_explorer.discopop_explorer import ExplorerArguments
    from discopop_library.result_classes.DetectionResult import DetectionResult

# define aliases for readability
from subprocess import check_output
from discopop_library.PathManagement.PathManagement import load_file_mapping
import logging

MIN = int
MAX = int
AVG = int
LOWER_QUART = int
UPPER_QUART = int

logger = logging.getLogger("statistics").getChild("CC").getChild("boxplot")


def get_cyclomatic_complexities_for_boxplot(
    arguments: ExplorerArguments, res: DetectionResult
) -> Tuple[MIN, MAX, AVG, LOWER_QUART, UPPER_QUART]:
    file_mapping = load_file_mapping(arguments.file_mapping_file)
    # get summed cyclomatic complexity for all functions in all files
    try:
        cmd = ["pmccabe", "-C"]
        for file_id in file_mapping:
            file_path = file_mapping[file_id]
            cmd.append(str(file_path))
        out = check_output(cmd).decode("utf-8")
    except FileNotFoundError as fnfe:
        logger.error(str(fnfe))
        return (0, 0, 0, 0, 0)

    # unpack and store results temporarily
    cyclomatic_complexities: List[int] = []
    for line in out.split("\n"):
        split_line = line.split("\t")
        if len(split_line) < 9:
            continue
        cyclomatic_complexity = split_line[1]
        # file_path = split_line[7]
        # function_name = split_line[8]

        cyclomatic_complexities.append(int(cyclomatic_complexity))

    # calculate statistics
    cc_min: MIN = min(cyclomatic_complexities)
    cc_max: MAX = max(cyclomatic_complexities)
    cc_avg: AVG = int(sum(cyclomatic_complexities) / len(cyclomatic_complexities))
    sorted_cyclomatic_complexities = sorted(cyclomatic_complexities)
    lower_quartile_idx = int((len(sorted_cyclomatic_complexities) + 1) * 1 / 4)
    upper_quartile_idx = int((len(sorted_cyclomatic_complexities) + 1) * 3 / 4)
    lower_quartile = sorted_cyclomatic_complexities[lower_quartile_idx]
    if len(sorted_cyclomatic_complexities) == 1:
        upper_quartile_idx = 0
    if len(sorted_cyclomatic_complexities) == upper_quartile_idx:
        upper_quartile_idx -= 1
    upper_quartile = sorted_cyclomatic_complexities[upper_quartile_idx]

    return cc_min, cc_max, cc_avg, lower_quartile, upper_quartile

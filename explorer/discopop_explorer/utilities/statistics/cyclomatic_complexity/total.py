# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discopop_explorer.discopop_explorer import ExplorerArguments
    from discopop_library.result_classes.DetectionResult import DetectionResult
from discopop_library.PathManagement.PathManagement import load_file_mapping


from subprocess import check_output

import logging

logger = logging.getLogger("statistics").getChild("CC").getChild("total")


def get_summed_cyclomatic_complexity(arguments: ExplorerArguments, res: DetectionResult) -> int:
    """calculate the total cyclomatic complexity"""
    file_mapping = load_file_mapping(arguments.file_mapping_file)
    # get summed cyclomatic complexity for all functions in all files
    try:
        cmd = ["pmccabe", "-T"]
        for file_id in file_mapping:
            file_path = file_mapping[file_id]
            cmd.append(str(file_path))
        out = check_output(cmd).decode("utf-8")
        summed_cyclomatic_complexity = int(out.split("\t")[1])
    except FileNotFoundError as fnfe:
        logger.error(str(fnfe))
        return 0

    return summed_cyclomatic_complexity

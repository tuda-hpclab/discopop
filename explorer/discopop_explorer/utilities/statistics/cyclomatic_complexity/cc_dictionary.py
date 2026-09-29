# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
from subprocess import check_output
from typing import TYPE_CHECKING, Dict, Optional

from discopop_library.PathManagement.PathManagement import load_file_mapping

if TYPE_CHECKING:
    from discopop_explorer.discopop_explorer import ExplorerArguments
    from discopop_library.result_classes.DetectionResult import DetectionResult


FILE_ID = int
FILEPATH = str
FUNC_NAME = str
CYC_COMP = int

CC_DICT = Dict[FILE_ID, Dict[FUNC_NAME, CYC_COMP]]


def get_cyclomatic_complexity_dictionary(arguments: ExplorerArguments, res: DetectionResult) -> CC_DICT:
    cc_dict: Dict[FILE_ID, Dict[FUNC_NAME, CYC_COMP]] = dict()
    file_mapping = load_file_mapping(arguments.file_mapping_file)

    # get summed cyclomatic complexity for all functions in all files
    try:
        cmd = ["pmccabe", "-C"]
        for file_id in file_mapping:
            file_path = file_mapping[file_id]
            cmd.append(str(file_path))
        out = check_output(cmd).decode("utf-8")
    except FileNotFoundError:
        return cc_dict

    # unpack and repack results
    for line in out.split("\n"):
        split_line = line.split("\t")
        if len(split_line) < 9:
            continue
        cyclomatic_complexity: CYC_COMP = int(split_line[1])
        file_path_2: FILEPATH = split_line[7]
        # get file_id
        file_id_2: Optional[int] = None
        for file_id in file_mapping:
            if str(file_mapping[file_id]) == file_path_2:
                file_id_2 = file_id

        if file_id_2 is None:
            continue

        func_name: FUNC_NAME = split_line[8]

        if file_id_2 not in cc_dict:
            cc_dict[file_id_2] = dict()
        cc_dict[file_id_2][func_name] = cyclomatic_complexity

    return cc_dict

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os.path
from pathlib import Path
from typing import Dict, Optional
import warnings


def load_file_mapping(fmap_path: str) -> Dict[int, Path]:
    if not os.path.exists(fmap_path):
        raise ValueError("Path does not exist! ", fmap_path)

    file_mapping: Dict[int, Path] = dict()

    with open(fmap_path, "r") as f:
        for line in f.readlines():
            line = line.replace("\n", "")
            split_line = line.split("\t")
            file_id = int(split_line[0])
            file_path = split_line[1]
            if os.path.exists(file_path):
                file_mapping[file_id] = Path(file_path)
            else:
                warnings.warn("Loading filemapping: File does not exist! " + str(file_path))
    return file_mapping


def get_path(base_path: str, file_name: str) -> str:
    """Combines path and filename if it is not absolute

    :param base_path: path
    :param file_name: file name
    :return: path to file
    """
    return file_name if os.path.isabs(file_name) else os.path.join(base_path, file_name)


def get_path_or_none(base_path: str, file_name: Optional[str]) -> Optional[str]:
    """same as get_path but returns None if file_name is None"""
    if file_name is None:
        return None
    return get_path(base_path, file_name)

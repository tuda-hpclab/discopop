# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
import os.path
from typing import Dict


def load_line_mapping(discopop_path: str = "") -> Dict[str, Dict[str, int]]:
    """Loads and returns the line_mapping dictionary"""
    line_mapping_dict: Dict[str, Dict[str, int]] = dict()
    with open(os.path.join(discopop_path, "line_mapping.json")) as f:
        line_mapping_dict = json.load(f)
    return line_mapping_dict

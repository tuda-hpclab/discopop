# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
import os
from typing import Dict


def save_line_mapping(line_mapping_dict: Dict[str, Dict[str, int]], discopop_path: str = "") -> None:
    """dumps line_mapping_dict to line_mapping.json"""
    # dump line mapping to json file
    with open(os.path.join(discopop_path, "line_mapping.json"), "w+") as f:
        json.dump(line_mapping_dict, f)

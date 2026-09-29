# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os.path
from typing import Dict, List


def read_patterns_from_json_to_json(json_path: str, relevant_patterns: List[str]) -> Dict[str, List[str]]:
    """relevant_patterns specifies the names of patterns which shall be returned.
    An empty list acts as a wildcard."""
    pattern_json_strings_by_type: Dict[str, List[str]] = dict()

    if not os.path.exists(json_path):
        raise ValueError("Path does not exist!", json_path)

    with open(json_path, "r") as f:
        data = json.load(f)
        for key in data["patterns"]:
            if len(relevant_patterns) > 0 and key not in relevant_patterns:
                continue
            if key not in pattern_json_strings_by_type:
                pattern_json_strings_by_type[key] = []
            for entry in data["patterns"][key]:
                pattern_json_strings_by_type[key].append(json.dumps(entry))

    return pattern_json_strings_by_type

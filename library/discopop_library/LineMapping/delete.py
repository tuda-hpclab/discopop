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


def delete_line_mapping(discopop_path: str = "") -> None:
    """deletes the saved line_mapping.json if it exists"""
    if os.path.exists(os.path.join(discopop_path, "line_mapping.json")):
        os.remove(os.path.join(discopop_path, "line_mapping.json"))

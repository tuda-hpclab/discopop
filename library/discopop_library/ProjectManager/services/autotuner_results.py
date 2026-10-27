# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the autotuner stored in ``<dot_dp>/auto_tuner/results.json``."""

import json
import os
from typing import List


def autotuner_results_path(dot_dp_path: str) -> str:
    return os.path.join(dot_dp_path, "auto_tuner", "results.json")


def autotuner_results_exist(dot_dp_path: str) -> bool:
    return os.path.exists(autotuner_results_path(dot_dp_path))


def read_autotuner_applied_suggestions(dot_dp_path: str, configuration: str) -> List[str]:
    """The suggestion ids the autotuner selected for ``configuration``, in the stored order.

    Empty when there are no results, they cannot be read, or they hold nothing for the configuration.
    """
    try:
        with open(autotuner_results_path(dot_dp_path), "r") as f:
            results = json.load(f)
        return [str(s) for s in results.get(configuration, {}).get("applied_suggestions", [])]
    except (json.JSONDecodeError, OSError):
        return []

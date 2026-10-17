# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the pattern detection (discopop_explorer) needs and what it left in ``<dot_dp>``."""

import json
import os
from typing import List

# the pattern lists of patterns.json that count as a suggestion
SUGGESTION_KEYS = ("optimizer_output", "merged_pattern", "task", "do_all", "reduction")


def required_explorer_files(dot_dp: str) -> List[str]:
    """The files of a profiling run the explorer reads."""
    return [
        os.path.join(dot_dp, "profiler", "Data.xml"),
        os.path.join(dot_dp, "profiler", "dynamic_dependencies.txt"),
        os.path.join(dot_dp, "profiler", "loop_counter_output.txt"),
        os.path.join(dot_dp, "profiler", "reduction.txt"),
        os.path.join(dot_dp, "FileMapping.txt"),
    ]


def missing_explorer_files(dot_dp: str) -> List[str]:
    """The required files that do not exist."""
    return [path for path in required_explorer_files(dot_dp) if not os.path.exists(path)]


def explorer_prerequisites_met(dot_dp: str) -> bool:
    """Whether a profiling run happened at all (the profiler directory exists); the files are checked on start."""
    return os.path.isdir(os.path.join(dot_dp, "profiler"))


def pattern_detection_executed(dot_dp: str) -> bool:
    return os.path.isdir(os.path.join(dot_dp, "explorer"))


def patterns_found(dot_dp: str) -> bool:
    """Whether the last pattern detection reported any suggestion."""
    patterns_file = os.path.join(dot_dp, "explorer", "patterns.json")
    if not os.path.exists(patterns_file):
        return False
    try:
        with open(patterns_file, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError):
        return False
    patterns = data.get("patterns", {})
    return any(patterns.get(key, []) for key in SUGGESTION_KEYS)

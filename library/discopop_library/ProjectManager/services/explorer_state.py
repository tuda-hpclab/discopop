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

# Selectable interpretations of the profiled dependency data, as (value, label) pairs.
# "no_states" runs the explorer with --ignore-dependency-states, i.e. it discards the
# callpath state markers the profiler recorded in dynamic_dependencies.txt.
DETECTION_MODES = [
    ("default", "default (full states)"),
    ("no_states", "no_states (states ignored)"),
]
DEFAULT_DETECTION_MODE = "default"
NO_STATES_DETECTION_MODE = "no_states"

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


def pattern_detection_tooltip_text(dot_dp: str) -> str:
    """Why the Pattern Detection tab is disabled, naming the profiling files that are missing."""
    lines = ["Prerequisites not met:", "Profiling data not found."]
    missing = missing_explorer_files(dot_dp)
    if missing:
        lines.append("Missing in " + dot_dp + ":")
        lines.extend("  " + os.path.relpath(path, dot_dp) for path in missing)
    lines.append("Execute a configuration in 'dp' mode with 'inplace' enabled first.")
    return "\n".join(lines)


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

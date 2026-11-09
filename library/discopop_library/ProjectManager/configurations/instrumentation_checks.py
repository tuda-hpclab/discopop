# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Checks that an instrumented build and an instrumented run produced what DiscoPoP needs.

Both fail silently otherwise: a build that loses ``DOT_DISCOPOP`` on the way to the compiler writes a
``.discopop`` of its own into every directory it compiles in, with numbering that does not fit together,
and the program then reports "done" while it writes its results nowhere. A scope that matches none of
the compiled files instruments nothing. See :mod:`.project_environment` for the variables.

The checks look at the files only, so they work for every build system. :func:`take_snapshot` is called
before a script runs, :func:`check_build` after an instrumented compile script, :func:`check_profiling_run`
after an instrumented ``execute.sh``.
"""

import glob
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional

# Mode of a run, as the name of its settings file tells it.
DP_SETTINGS = "dp_settings.json"
HD_SETTINGS = "hd_settings.json"

# Files written by the compiler wrappers and passes into a .discopop directory; a stray .discopop holding
# one of them that is newer than the start of the build was written by that build.
_BUILD_OUTPUT_ENTRIES = ("FileMapping.txt", "profiler", "hotspot_detection")

# Directories that are never searched for stray .discopop directories.
_SKIPPED_DIRECTORIES = (".git", ".svn", ".hg")

# Slack for file systems with a coarse modification time.
_MTIME_SLACK_SECONDS = 1.0


@dataclass(frozen=True)
class Snapshot:
    """What is known before a script runs."""

    started: float
    instruction_counter: Optional[str]


@dataclass
class CheckResult:
    """``errors`` make a successful script fail, ``warnings`` are reported only."""

    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def messages(self) -> List[str]:
        return ["ERROR: " + e for e in self.errors] + ["WARNING: " + w for w in self.warnings]


def _instruction_counter_path(dot_discopop: str) -> str:
    return os.path.join(dot_discopop, "profiler", "DP_InstructionIDCounter.txt")


def _read(path: str) -> Optional[str]:
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except OSError:
        return None


def take_snapshot(dot_discopop: str) -> Snapshot:
    return Snapshot(started=time.time(), instruction_counter=_read(_instruction_counter_path(dot_discopop)))


def _written_since(path: str, since: float) -> bool:
    try:
        return os.path.getmtime(path) >= since - _MTIME_SLACK_SECONDS
    except OSError:
        return False


def find_stray_dot_discopop_dirs(run_root: str, dot_discopop: str, since: float) -> List[str]:
    """The ``.discopop`` directories below ``run_root`` other than ``dot_discopop`` that a build wrote to
    since ``since``, sorted."""
    expected = os.path.realpath(dot_discopop)
    stray: List[str] = []
    for directory, subdirectories, _files in os.walk(run_root):
        kept = []
        for name in subdirectories:
            path = os.path.join(directory, name)
            if name in _SKIPPED_DIRECTORIES or os.path.islink(path):
                continue
            if name == ".discopop":
                # never descended into: the expected one holds the project's data, a stray one is reported
                if os.path.realpath(path) != expected and any(
                    _written_since(os.path.join(path, entry), since) for entry in _BUILD_OUTPUT_ENTRIES
                ):
                    stray.append(path)
                continue
            kept.append(name)
        subdirectories[:] = kept
    return sorted(stray)


def check_build(snapshot: Snapshot, settings_name: str, run_root: str, dot_discopop: str, scope: str) -> CheckResult:
    """Check the result of an instrumented compile script (dp or hd mode); nothing to check otherwise."""
    result = CheckResult()
    if settings_name not in (DP_SETTINGS, HD_SETTINGS):
        return result
    stray = find_stray_dot_discopop_dirs(run_root, dot_discopop, snapshot.started)
    if stray:
        result.errors.append(
            "The build wrote DiscoPoP data into "
            + str(len(stray))
            + " directories other than DOT_DISCOPOP="
            + dot_discopop
            + ": "
            + ", ".join(stray[:5])
            + (", ..." if len(stray) > 5 else "")
            + ". DOT_DISCOPOP did not reach every compiler call (e.g. the build resets the environment, or "
            "it runs a compiler other than $CC / $CXX), so the data of the build does not fit together."
        )
    if settings_name == DP_SETTINGS and _read(_instruction_counter_path(dot_discopop)) == snapshot.instruction_counter:
        result.warnings.append(
            "The build instrumented no code below the instrumentation scope DP_PROJECT_ROOT_DIR="
            + scope
            + ". Either everything was up to date, or the scope matches none of the compiled files (e.g. the "
            "build compiles sources outside the run root, as a CMake cache of another directory does)."
        )
    return result


def check_profiling_run(snapshot: Snapshot, settings_name: str, dot_discopop: str) -> CheckResult:
    """Check the result of an instrumented ``execute.sh`` (dp or hd mode); nothing to check otherwise."""
    result = CheckResult()
    if settings_name == DP_SETTINGS:
        dependencies = os.path.join(dot_discopop, "profiler", "dynamic_dependencies.txt")
        if not _written_since(dependencies, snapshot.started):
            result.errors.append(
                "The profiling run did not write "
                + dependencies
                + ". The instrumented program did not run, or it wrote its results into another directory "
                "(it reads DOT_DISCOPOP when it starts; a script that starts it with another environment or "
                "from another project loses it)."
            )
    elif settings_name == HD_SETTINGS:
        pattern = os.path.join(dot_discopop, "hotspot_detection", "private", "hotspot_result_*.txt")
        if not any(_written_since(path, snapshot.started) for path in glob.glob(pattern)):
            result.errors.append(
                "The hotspot detection run did not write a result into "
                + os.path.dirname(pattern)
                + ". The instrumented program did not run, or it wrote its results into another directory "
                "(it reads DOT_DISCOPOP when it starts)."
            )
    return result

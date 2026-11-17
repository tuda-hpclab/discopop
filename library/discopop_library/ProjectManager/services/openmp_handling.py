# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What happens to the OpenMP flags of an instrumented (``dp`` / ``hd``) compilation.

A program that is compiled with ``-fopenmp`` is profiled with its OpenMP pragmas active: the threads are instrumented
as concurrent code, the dependences depend on the thread schedule and the pattern detection does not know that a loop
is parallel already. The compiler wrappers (``profiler/scripts/dp_openmp.sh``) therefore keep the flags and warn by
default, and remove them if the environment variable ``DP_STRIP_OPENMP=1`` is set. This module holds the project's
setting (``.discopop/project/openmp_handling.json``, off by default, edited in the *Project Setup* stage of the GUI,
overridden for one invocation by ``--strip-openmp`` / ``--no-strip-openmp``), builds the variables for an instrumented
compilation and words the warning the wrappers' finding (``.discopop/openmp_flags_seen.json``) leads to. Toolkit-free.
"""

import json
import os
from dataclasses import asdict, dataclass
from typing import Dict, Optional, Tuple

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.project_environment import INSTRUMENTED_DIRECTORIES_FILE

OPENMP_HANDLING_FILE = "openmp_handling.json"
# written by the wrappers into the .discopop of a build when they saw an OpenMP flag
OPENMP_FLAGS_SEEN_FILE = "openmp_flags_seen.json"

STRIP_VARIABLE = "DP_STRIP_OPENMP"
QUIET_VARIABLE = "DP_OPENMP_QUIET"
VARIABLES = (STRIP_VARIABLE, QUIET_VARIABLE)

# where the setting is, in the words of the warnings
GUI_LOCATION = 'Project Setup stage, section "OpenMP flags", check box "Remove OpenMP flags"'
COMMAND_LINE_OPTION = "--strip-openmp"


@dataclass(frozen=True)
class OpenMPHandling:
    """The setting: whether the instrumented compilations remove the OpenMP flags."""

    strip: bool = False


def openmp_handling_path(project_dir: str) -> str:
    """The file of the setting; ``project_dir`` is ``.discopop/project``."""
    return os.path.join(project_dir, OPENMP_HANDLING_FILE)


def load_openmp_handling(project_dir: str) -> OpenMPHandling:
    """The stored setting; the default (keep the flags) if there is none (an unreadable file must not stop a
    build)."""
    try:
        with open(openmp_handling_path(project_dir), "r") as file:
            content = json.load(file)
    except (OSError, ValueError):
        return OpenMPHandling()
    if not isinstance(content, dict):
        return OpenMPHandling()
    return OpenMPHandling(strip=content.get("strip") is True)


def save_openmp_handling(project_dir: str, handling: OpenMPHandling) -> None:
    """Store ``handling``; the file is only written if the setting changes (its modification time marks results as
    stale for the MCP server)."""
    if load_openmp_handling(project_dir) == handling:
        return
    os.makedirs(project_dir, exist_ok=True)
    path = openmp_handling_path(project_dir)
    temporary = path + ".tmp"
    with open(temporary, "w") as file:
        json.dump(asdict(handling), file, indent=2)
        file.write("\n")
    os.replace(temporary, path)


def strips_openmp(arguments: ProjectManagerArguments) -> bool:
    """Whether instrumented compilations remove the OpenMP flags: the command line option wins over the stored
    setting."""
    if arguments.strip_openmp is not None:
        return arguments.strip_openmp
    return load_openmp_handling(arguments.project_dir).strip


def environment(arguments: ProjectManagerArguments) -> Dict[str, str]:
    """The variables an instrumented compilation gets. The wrappers only record what they saw
    (``DP_OPENMP_QUIET``): the project manager words the warning itself, see :func:`outcome_message`."""
    variables = {QUIET_VARIABLE: "1"}
    if strips_openmp(arguments):
        variables[STRIP_VARIABLE] = "1"
    return variables


def fingerprint_part(arguments: ProjectManagerArguments) -> Optional[str]:
    """The part of the fingerprint of an instrumented build, None (no part, so builds of before this setting stay
    current) while the flags are kept."""
    return "strip" if strips_openmp(arguments) else None


def ignored_variables_warning(present: Tuple[str, ...]) -> Optional[str]:
    """A warning for ``present`` (names of :data:`VARIABLES` found in the environment or the settings file of an
    instrumented compilation, where they are ignored)."""
    if not present:
        return None
    return (
        ", ".join(present) + " set in the environment or the settings file is ignored: the removal of the OpenMP "
        "flags is configured in the project (GUI: "
        + GUI_LOCATION
        + "; command line: "
        + COMMAND_LINE_OPTION
        + " / --no-strip-openmp)."
    )


def flags_seen_path(dot_discopop: str) -> str:
    return os.path.join(dot_discopop, OPENMP_FLAGS_SEEN_FILE)


def clear_flags_seen(dot_discopop: str) -> None:
    """Forget what an earlier compilation saw: the wrappers only report the first sighting of a build."""
    try:
        os.remove(flags_seen_path(dot_discopop))
    except OSError:
        pass


def flags_seen(dot_discopop: str) -> Optional[Tuple[str, bool]]:
    """``(flags, stripped)`` the wrappers recorded for the compilation in ``dot_discopop``; None if they saw no OpenMP
    flag."""
    try:
        with open(flags_seen_path(dot_discopop), "r") as file:
            content = json.load(file)
        flags = content["flags"]
        stripped = content["stripped"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(flags, str) or not isinstance(stripped, bool):
        return None
    return flags, stripped


def outcome_message(dot_discopop: str) -> Tuple[Optional[str], Optional[str]]:
    """``(warning, note)`` for the compilation that wrote into ``dot_discopop``: a warning if OpenMP flags were kept,
    a note if they were removed; both None if there were none. The warning says where to switch the removal on."""
    seen = flags_seen(dot_discopop)
    if seen is None:
        return None, None
    flags, stripped = seen
    if stripped:
        return None, (
            "The OpenMP flags (" + flags + ") were removed from the instrumented compilation: the program is profiled "
            "as the sequential code its pragmas annotate. Code that calls omp_* functions needs #ifdef _OPENMP guards "
            "to link without the OpenMP runtime."
        )
    return (
        "The instrumented compilation kept the OpenMP flags (" + flags + "): the program is profiled with its OpenMP "
        "pragmas active. Its threads are instrumented as concurrent code, the dependences found depend on the thread "
        "schedule, and the pattern detection does not know that a loop is parallel already. To profile the "
        "sequential code, remove the flags from the instrumented builds: in the GUI ("
        + GUI_LOCATION
        + "), with "
        + COMMAND_LINE_OPTION
        + " on the command line, or with DP_STRIP_OPENMP=1 for discopop_cc / discopop_cxx "
        "called by hand."
    ), None


def record_state(dot_discopop: str, mode: str, strip: bool) -> None:
    """Note in ``instrumented_project_directories.json`` that the data of ``mode`` was compiled with the OpenMP flags
    kept or removed. Best effort."""
    path = os.path.join(dot_discopop, INSTRUMENTED_DIRECTORIES_FILE)
    try:
        with open(path, "r") as file:
            recorded = json.load(file)
        recorded[mode]["strip_openmp"] = strip
        with open(path, "w") as file:
            json.dump(recorded, file, indent=2)
    except (OSError, ValueError, KeyError, TypeError):
        pass


def recorded_state(dot_discopop: str, mode: str) -> Optional[bool]:
    """Whether the data of ``mode`` was compiled with the OpenMP flags removed; None if unknown (older data)."""
    try:
        with open(os.path.join(dot_discopop, INSTRUMENTED_DIRECTORIES_FILE), "r") as file:
            state = json.load(file)[mode]["strip_openmp"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return state if isinstance(state, bool) else None


def stale_message(arguments: ProjectManagerArguments, mode: str = "dp") -> Optional[str]:
    """A message if the data of ``mode`` was compiled with another OpenMP handling than a build now would; None if it
    matches or is unknown (older data)."""
    recorded = recorded_state(arguments.dot_dp, mode)
    if recorded is None or recorded == strips_openmp(arguments):
        return None
    return (
        "The profiling data was compiled with the OpenMP flags "
        + ("removed" if recorded else "kept")
        + ", but the setting is now to "
        + ("keep" if recorded else "remove")
        + " them. Profile again to update it."
    )

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Whether the instrumented build of the hotspot analysis is still usable."""

import os
from typing import Callable, Optional, Tuple

# Build states, as reported by hotspot_build_state.
BUILD_NONE = "none"
BUILD_CURRENT = "current"
BUILD_STALE = "stale"
BUILD_MISMATCH = "mismatch"

# Source extensions considered when deciding whether a build went stale.
SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx")
# Directories never worth walking for source mtimes.
PRUNED_DIRS = {".git", ".discopop", "build", "venv", "__pycache__", "node_modules", ".mypy_cache"}


def newest_source_mtime(project_root: str) -> Optional[float]:
    """Newest mtime among the project's C/C++ sources, or ``None`` if none found."""
    newest: Optional[float] = None
    for root, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [d for d in dirnames if d not in PRUNED_DIRS and not d.startswith(".")]
        for filename in filenames:
            if not filename.endswith(SOURCE_SUFFIXES):
                continue
            try:
                mtime = os.path.getmtime(os.path.join(root, filename))
            except OSError:
                continue
            if newest is None or mtime > newest:
                newest = mtime
    return newest


def hotspot_build_state(
    cs_id_path: str, project_root: str, compile_script_differs: Callable[[], bool]
) -> Tuple[str, str]:
    """Whether the current build can serve another run directly, and why not.

    ``cs_id_path`` is the profiler's call site id file, which the instrumented build writes; its mtime is
    the time of the build. A non-current state only means a recompile is needed first; it no longer
    implies losing anything, since runs from separate builds are combined by source location.
    ``BUILD_MISMATCH`` is the one case that warrants a warning: the region set changed under the
    accumulated runs, which for a source edit means their line numbers may no longer refer to the same code.
    ``compile_script_differs`` tells whether the selected configuration compiles with another script than
    the recorded build; it is only called once the build is otherwise usable.
    """
    if not os.path.exists(cs_id_path):
        return (BUILD_NONE, "No instrumented build yet.")

    try:
        build_mtime = os.path.getmtime(cs_id_path)
    except OSError:
        return (BUILD_NONE, "No instrumented build yet.")
    newest_source = newest_source_mtime(project_root)
    if newest_source is not None and newest_source > build_mtime:
        return (BUILD_MISMATCH, "Sources changed since the instrumented build was made.")

    if compile_script_differs():
        return (
            BUILD_STALE,
            "This configuration uses a different compile.sh, so it will be instrumented separately.",
        )
    return (BUILD_CURRENT, "")

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

from discopop_library.AnalysisRecord import RECORD_FILENAME, source_files, step_status

# Build states, as reported by hotspot_build_state.
BUILD_NONE = "none"
BUILD_CURRENT = "current"
BUILD_STALE = "stale"
BUILD_MISMATCH = "mismatch"


def newest_source_mtime(project_root: str) -> Optional[float]:
    """Newest mtime among the project's C/C++ sources, or ``None`` if none found.

    The files are those of the analysis record's source walk. Only the fallback for projects whose
    hotspot runs carry no analysis record.
    """
    newest: Optional[float] = None
    for relative in source_files(project_root):
        try:
            mtime = os.path.getmtime(os.path.join(project_root, relative))
        except OSError:
            continue
        if newest is None or mtime > newest:
            newest = mtime
    return newest


def _sources_changed(project_root: str, build_mtime: float) -> bool:
    """Whether the sources differ from those the build (and the hotspot runs) were made for.

    The analysis record's content fingerprint decides when the hotspot runs are recorded; a build of
    unrecorded (older) data falls back to comparing the sources' mtimes with the build's.
    """
    dot_discopop = os.path.join(project_root, ".discopop")
    if os.path.isfile(os.path.join(dot_discopop, RECORD_FILENAME)):
        status = step_status(dot_discopop, "hotspot_detection", project_root)
        if status.basis == "fingerprint":
            return status.state == "stale"
    newest_source = newest_source_mtime(project_root)
    return newest_source is not None and newest_source > build_mtime


def hotspot_build_state(
    cs_id_path: str, project_root: str, compile_script_differs: Callable[[], bool]
) -> Tuple[str, str]:
    """Whether the current build can serve another run directly, and why not.

    ``cs_id_path`` is the profiler's call site id file, which the instrumented build writes; its mtime is
    the time of the build (used only for data without an analysis record; with one, the sources' content
    decides). A non-current state only means a recompile is needed first; it no longer
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
    if _sources_changed(project_root, build_mtime):
        return (BUILD_MISMATCH, "Sources changed since the instrumented build was made.")

    if compile_script_differs():
        return (
            BUILD_STALE,
            "This configuration uses a different compile.sh, so it will be instrumented separately.",
        )
    return (BUILD_CURRENT, "")

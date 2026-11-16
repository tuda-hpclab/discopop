# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The run phase: execute ``execute.sh`` in a build, a profiling run (dp, hd) in a run directory of its own."""

from typing import Any, Callable, Dict, Optional, Tuple

import subprocess

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.builds import BuildRecord
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.configurations.runs import PROFILING_MODES, RunRecord, finish_run, prepare_run

PATH = str


def execute_in_build(
    arguments: ProjectManagerArguments,
    build: BuildRecord,
    config_path: PATH,
    settings_path: PATH,
    thread_count: int,
    timeout: Optional[float],
    execution_time_regex: Optional[str],
    repetitions: int,
    process_started_callback: Optional[Callable[["subprocess.Popen[bytes]"], None]] = None,
    should_abort: Optional[Callable[[], bool]] = None,
    on_run: Optional[Callable[[RunRecord], None]] = None,
) -> Tuple[Optional[Tuple[int, float, str, str]], Optional[RunRecord]]:
    """Run ``execute.sh`` of the configuration in the tree of ``build``.

    The run of a profiling mode gets the directory of a new run as its ``DOT_DISCOPOP`` (see
    :mod:`~discopop_library.ProjectManager.configurations.runs`), so that its results neither overwrite those of
    another run nor accumulate in the build; ``on_run`` is told about it before the script starts. The record of the
    run and of the measurement name the build (and the run), so that results can be traced back. Returns what
    :func:`execute_configuration` returns and the run, if there is one.
    """
    run: Optional[RunRecord] = None
    annotations: Dict[str, Any] = {"build_id": build.build_id}
    dot_discopop: Optional[str] = None
    if build.mode in PROFILING_MODES:
        run = prepare_run(arguments.project_root, build, thread_count, arguments.label_prefix)
        dot_discopop = run.dot_discopop
        annotations["run_id"] = run.run_id
        if on_run is not None:
            on_run(run)
    result = None
    try:
        result = execute_configuration(
            arguments,
            build.tree,
            config_path,
            settings_path,
            _execute_script(config_path),
            thread_count,
            timeout,
            process_started_callback=process_started_callback,
            execution_time_regex=execution_time_regex,
            repetitions=repetitions,
            should_abort=should_abort,
            dot_discopop=dot_discopop,
            result_annotations=annotations,
        )
    finally:
        if run is not None:
            finish_run(run, result[0] if result is not None else None)
    return result, run


def _execute_script(config_path: PATH) -> PATH:
    import os

    return os.path.join(config_path, "execute.sh")

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Run the DiscoPoP pipeline (build with the pass, profile, explore) on a copy of a test program."""

import os
import shutil
import subprocess
from pathlib import Path

import jsonpickle

from discopop_library.result_classes.DetectionResult import DetectionResult


class PipelineError(Exception):
    """A stage of the pipeline failed, i.e. the test could not check anything."""


def _run(stage: str, cmd: str, cwd: Path, env: dict[str, str]) -> None:
    result = subprocess.run(cmd, cwd=cwd, env=env, shell=True, executable="/bin/bash", capture_output=True, text=True)
    if result.returncode != 0:
        raise PipelineError(
            f"{stage} failed (exit code {result.returncode}): {cmd}\n"
            f"cwd: {cwd}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


def run_pipeline(src_dir: Path, work_dir: Path, enable_patterns: str, run_args: str = "") -> DetectionResult:
    """Copy src_dir to work_dir, build it with the DiscoPoP compiler wrappers, run it (./prog run_args) and the
    explorer.

    The source tree is never written to; work_dir is kept for inspection after a failure.
    """
    shutil.copytree(src_dir, work_dir)
    env = dict(os.environ)
    env["CC"] = "discopop_cc"
    env["CXX"] = "discopop_cxx"
    env["DP_PROJECT_ROOT_DIR"] = str(work_dir)

    _run("build", "make", work_dir, env)
    _run("profiling", f"./prog {run_args}".strip(), work_dir, env)
    dot_discopop = work_dir / ".discopop"
    _run("explorer", f"discopop_explorer --enable-patterns {enable_patterns}", dot_discopop, env)

    dump = dot_discopop / "explorer" / "detection_result_dump.json"
    result: DetectionResult = jsonpickle.decode(dump.read_text(), keys=True)
    return result

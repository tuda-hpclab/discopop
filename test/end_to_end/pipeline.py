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
import tempfile
import unittest
from pathlib import Path

import jsonpickle

from discopop_library.result_classes.DetectionResult import DetectionResult


class PipelineError(Exception):
    """A stage of the pipeline failed, i.e. the test could not check anything."""


def _environment(project_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["CC"] = "discopop_cc"
    env["CXX"] = "discopop_cxx"
    env["DP_PROJECT_ROOT_DIR"] = str(project_dir)
    return env


def _run(stage: str, cmd: str, cwd: Path, env: dict[str, str]) -> None:
    result = subprocess.run(cmd, cwd=cwd, env=env, shell=True, executable="/bin/bash", capture_output=True, text=True)
    if result.returncode != 0:
        raise PipelineError(
            f"{stage} failed (exit code {result.returncode}): {cmd}\n"
            f"cwd: {cwd}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


def build_and_profile(src_dir: Path, work_dir: Path, run_args: str = "") -> Path:
    """Copy src_dir to work_dir, build it with the DiscoPoP compiler wrappers and run it (./prog run_args).

    Returns the .discopop directory. The source tree is never written to.
    """
    shutil.copytree(src_dir, work_dir)
    env = _environment(work_dir)
    _run("build", "make", work_dir, env)
    _run("profiling", f"./prog {run_args}".strip(), work_dir, env)
    return work_dir / ".discopop"


def explore(dot_discopop: Path, enable_patterns: str) -> DetectionResult:
    """Run discopop_explorer in dot_discopop and load its detection result."""
    env = _environment(dot_discopop.parent)
    _run("explorer", f"discopop_explorer --enable-patterns {enable_patterns}", dot_discopop, env)
    dump = dot_discopop / "explorer" / "detection_result_dump.json"
    result: DetectionResult = jsonpickle.decode(dump.read_text(), keys=True)
    return result


def run_pipeline(src_dir: Path, work_dir: Path, enable_patterns: str, run_args: str = "") -> DetectionResult:
    """build_and_profile, then explore; work_dir is kept for inspection after a failure."""
    return explore(build_and_profile(src_dir, work_dir, run_args), enable_patterns)


class PipelineTestCase(unittest.TestCase):
    """A test class whose tests share one profiled (and, with ENABLE_PATTERNS, explored) run of SRC_DIR.

    The run happens in a temporary directory, which is removed after the tests of the class. Provides
    ``dot_discopop``, ``profiler_dir`` and, with ENABLE_PATTERNS, ``test_output`` (the DetectionResult).
    """

    SRC_DIR: Path
    ENABLE_PATTERNS: str | None = None
    RUN_ARGS = ""

    dot_discopop: Path
    profiler_dir: Path
    test_output: DetectionResult

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="discopop_e2e_")
        cls.addClassCleanup(tmp.cleanup)
        cls.dot_discopop = build_and_profile(cls.SRC_DIR, Path(tmp.name) / "src", cls.RUN_ARGS)
        cls.profiler_dir = cls.dot_discopop / "profiler"
        if cls.ENABLE_PATTERNS is not None:
            cls.test_output = explore(cls.dot_discopop, cls.ENABLE_PATTERNS)

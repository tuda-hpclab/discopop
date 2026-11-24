# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Run the DiscoPoP pipeline (build with the pass, profile, explore) on a copy of a test program."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import jsonpickle

from discopop_library.Amdahl.regions import extents_path_of, read_suggestion_extents, suggestion_extents
from discopop_library.result_classes.DetectionResult import DetectionResult


class PipelineError(Exception):
    """A stage of the pipeline failed, i.e. the test could not check anything."""


def _isolated_home(project_dir: Path) -> Path:
    """A HOME next to project_dir with the update check of the DiscoPoP tools switched off.

    The tools keep their configuration in $HOME/.discopop_config; a HOME per test keeps the tests from sharing it
    with each other and with the developer, and from contacting the release server.
    """
    home = project_dir.parent / "home"
    settings_file = home / ".discopop_config" / "auto_updater" / "settings.json"
    if not settings_file.exists():
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        settings_file.write_text(
            json.dumps({"automatic_check_active": False, "enable_interactive_notifications": False})
        )
    return home


def _environment(project_dir: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["CC"] = "discopop_cc"
    env["CXX"] = "discopop_cxx"
    env["DP_PROJECT_ROOT_DIR"] = str(project_dir)
    env["HOME"] = str(_isolated_home(project_dir))
    return env


def _run(stage: str, cmd: str, cwd: Path, env: dict[str, str]) -> None:
    result = subprocess.run(cmd, cwd=cwd, env=env, shell=True, executable="/bin/bash", capture_output=True, text=True)
    if result.returncode != 0:
        raise PipelineError(
            f"{stage} failed (exit code {result.returncode}): {cmd}\n"
            f"cwd: {cwd}\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )


def build_and_profile(
    src_dir: Path, work_dir: Path, run_args: str = "", extra_env: dict[str, str] | None = None
) -> Path:
    """Copy src_dir to work_dir, build it with the DiscoPoP compiler wrappers and run it (./prog run_args).

    extra_env is added to the environment of both steps (e.g. CXXFLAGS, which the test Makefiles pass to the
    compiler). Returns the .discopop directory. The source tree is never written to.
    """
    shutil.copytree(src_dir, work_dir)
    env = _environment(work_dir)
    env.update(extra_env or {})
    _run("build", "make", work_dir, env)
    _run("profiling", f"./prog {run_args}".strip(), work_dir, env)
    return work_dir / ".discopop"


def explore(dot_discopop: Path, enable_patterns: str) -> DetectionResult:
    """Run discopop_explorer in dot_discopop and load its detection result."""
    env = _environment(dot_discopop.parent)
    _run("explorer", f"discopop_explorer --enable-patterns {enable_patterns}", dot_discopop, env)
    dump = dot_discopop / "explorer" / "detection_result_dump.json"
    result: DetectionResult = jsonpickle.decode(dump.read_text(), keys=True)
    _check_suggestion_extents(dump, result)
    return result


def _check_suggestion_extents(dump: Path, result: DetectionResult) -> None:
    """The explorer writes the extents of the suggestions next to the dump (what the GUI reads instead of decoding
    the dump): they must belong to this dump and match the detection result."""
    written = read_suggestion_extents(str(dump))
    if written is None:
        raise PipelineError(f"explorer wrote no current {extents_path_of(str(dump))} next to {dump}")
    expected = suggestion_extents(result)
    if written != expected:
        raise PipelineError(
            f"the suggestion extents next to {dump} differ from the detection result:\n"
            f"written: {written}\nexpected: {expected}"
        )


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
    EXTRA_ENV: dict[str, str] | None = None

    dot_discopop: Path
    profiler_dir: Path
    test_output: DetectionResult

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="discopop_e2e_")
        cls.addClassCleanup(tmp.cleanup)
        cls.dot_discopop = build_and_profile(cls.SRC_DIR, Path(tmp.name) / "src", cls.RUN_ARGS, cls.EXTRA_ENV)
        cls.profiler_dir = cls.dot_discopop / "profiler"
        if cls.ENABLE_PATTERNS is not None:
            cls.test_output = explore(cls.dot_discopop, cls.ENABLE_PATTERNS)

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Whether the compile scripts get the thread count of the run as ``OMP_NUM_THREADS``.

GNU ``nproc`` honors ``OMP_NUM_THREADS``, so ``make -j $(nproc)`` in the compilation of a ``par:8`` run would start 8
jobs only. The compile scripts (``compile.sh``, ``compile_incremental.sh``, ``compile_validate.sh``) therefore do not
get the variable from the project manager by default; ``execute.sh`` / ``validate.sh`` always do. This module holds the
project's setting (``.discopop/project/build_thread_count.json``, off by default, edited in the *Build* stage of the Qt
GUI, overridden for one invocation by ``--build-thread-count`` / ``--no-build-thread-count``). The setting is no part of
the build fingerprint. Toolkit-free.
"""

import json
import os
from dataclasses import asdict, dataclass

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments

BUILD_THREAD_COUNT_FILE = "build_thread_count.json"


@dataclass(frozen=True)
class BuildThreadCount:
    """The setting: whether the compile scripts get the thread count of the run as ``OMP_NUM_THREADS``."""

    pass_to_builds: bool = False


def build_thread_count_path(project_dir: str) -> str:
    """The file of the setting; ``project_dir`` is ``.discopop/project``."""
    return os.path.join(project_dir, BUILD_THREAD_COUNT_FILE)


def load_build_thread_count(project_dir: str) -> BuildThreadCount:
    """The stored setting; the default (do not pass) if there is none (an unreadable file must not stop a build)."""
    try:
        with open(build_thread_count_path(project_dir), "r") as file:
            content = json.load(file)
    except (OSError, ValueError):
        return BuildThreadCount()
    if not isinstance(content, dict):
        return BuildThreadCount()
    return BuildThreadCount(pass_to_builds=content.get("pass_to_builds") is True)


def save_build_thread_count(project_dir: str, setting: BuildThreadCount) -> None:
    """Store ``setting``; the file is only written if the setting changes."""
    if load_build_thread_count(project_dir) == setting:
        return
    os.makedirs(project_dir, exist_ok=True)
    path = build_thread_count_path(project_dir)
    temporary = path + ".tmp"
    with open(temporary, "w") as file:
        json.dump(asdict(setting), file, indent=2)
        file.write("\n")
    os.replace(temporary, path)


def passes_thread_count_to_builds(arguments: ProjectManagerArguments) -> bool:
    """Whether compile scripts get ``OMP_NUM_THREADS``: the command line option wins over the stored setting."""
    if arguments.build_thread_count is not None:
        return arguments.build_thread_count
    return load_build_thread_count(arguments.project_dir).pass_to_builds

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The build phase of a configuration: compile once, run many times.

:func:`ensure_build` makes sure that a build tree of a :class:`~discopop_library.ProjectManager.configurations.builds.BuildKey`
exists and is current -- reusing it when the fingerprint still matches, compiling otherwise, as the
:class:`~discopop_library.ProjectManager.configurations.builds.BuildPolicy` says. The runs (``execute.sh``) are the
callers' business: they execute in the returned tree.
"""

import logging
import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterator, Optional, Tuple

import subprocess

from filelock import FileLock, Timeout

from discopop_library.PatchApplicator.PatchApplicationResult import PatchApplicationResult
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.builds import (
    BuildKey,
    BuildPolicy,
    BuildRecord,
    BuildState,
    build_status,
    build_tree_path_of,
    compute_fingerprint_parts,
    delete_build,
    make_record,
    manifest_path_of,
    write_build,
)
from discopop_library.ProjectManager.configurations.copying import (
    copy_configuration,
    get_application_result,
    restore_outside_patches,
)
from discopop_library.ProjectManager.configurations.execution import execute_configuration

PATH = str
logger = logging.getLogger("ConfigurationManager")


class BuildResult(str, Enum):
    # compiled now
    BUILT = "built"
    # an existing build serves the run
    REUSED = "reused"
    # the compilation failed
    COMPILE_FAILED = "compile_failed"
    # the requested suggestions could not be applied, so the tree holds the original code
    APPLICATION_FAILED = "application_failed"
    # the policy forbids compiling and there is no usable build
    UNAVAILABLE = "unavailable"
    # the copy of the project failed
    COPY_FAILED = "copy_failed"


@dataclass
class BuildOutcome:
    result: BuildResult
    key: BuildKey
    # the build tree the runs execute in; None unless the build is usable
    tree: Optional[PATH] = None
    record: Optional[BuildRecord] = None
    # return code, seconds, stdout, stderr of the compilation, if it ran
    compile_result: Optional[Tuple[int, float, str, str]] = None
    application_result: Optional[PatchApplicationResult] = None
    message: str = ""

    @property
    def usable(self) -> bool:
        return self.result in (BuildResult.BUILT, BuildResult.REUSED)


class BuildLockAborted(Exception):
    """The caller stopped waiting for the lock of a build."""


# what a build does not start with: the data of earlier profiling runs in the project's .discopop
DATA_LEFT_OUT_OF_BUILDS = ("profiler", "hotspot_detection", "explorer")


@contextmanager
def build_lock(
    arguments: ProjectManagerArguments,
    key: BuildKey,
    should_abort: Optional[Callable[[], bool]] = None,
    on_wait: Optional[Callable[[], None]] = None,
) -> Iterator[None]:
    """Serializes everything that uses or changes the build tree of ``key`` (building and running in it).

    Waits as long as another run holds the lock, calling ``on_wait`` once, and raises :class:`BuildLockAborted`
    if ``should_abort`` says so meanwhile.
    """
    os.makedirs(os.path.dirname(manifest_path_of(arguments.project_dir, key)), exist_ok=True)
    lock = FileLock(manifest_path_of(arguments.project_dir, key) + ".build.lock")
    waiting = False
    while True:
        try:
            lock.acquire(timeout=1)
            break
        except Timeout:
            if not waiting and on_wait is not None:
                on_wait()
            waiting = True
            if should_abort is not None and should_abort():
                raise BuildLockAborted(key.build_id)
    try:
        yield
    finally:
        lock.release()


def refresh_run_scripts(arguments: ProjectManagerArguments, tree: PATH) -> None:
    """Bring the configuration files of the build tree up to date with the project.

    The runs execute ``execute.sh`` / ``validate.sh`` and read the settings from the copy of ``.discopop/project``
    in the tree, which was made with the build; editing them (another input, other arguments) must not need a new
    build, so they are copied again before a run. Whatever changes the compilation is part of the fingerprint.
    """
    source = os.path.abspath(arguments.project_config_dir)
    root = os.path.abspath(arguments.project_root)
    if os.path.commonpath([source, root]) != root:
        return
    destination = os.path.join(tree, os.path.relpath(source, root))
    shutil.copytree(source, destination, dirs_exist_ok=True)


def ensure_build(
    arguments: ProjectManagerArguments,
    key: BuildKey,
    config_path: PATH,
    settings_path: PATH,
    compile_script: PATH,
    thread_count: int,
    policy: BuildPolicy,
    timeout: Optional[float] = None,
    process_started_callback: Optional[Callable[["subprocess.Popen[bytes]"], None]] = None,
    message: Callable[[str], None] = lambda _text: None,
    on_application_failure: Optional[Callable[[PATH, PatchApplicationResult], None]] = None,
) -> BuildOutcome:
    """The usable build of ``key``, compiled if the policy and the state of the build require it.

    ``arguments.apply_suggestions`` has to hold the suggestions of ``key`` (the caller derives both from the same
    list). The caller holds :func:`build_lock` of ``key``. ``on_application_failure`` is called with the tree and the
    result when the suggestions could not be applied, before the tree (which then holds the original code) is removed.
    """
    status = build_status(arguments, key, compile_script, settings_path)

    # A suggestion that patches files outside of the project was applied to those files in place and restored
    # after the compilation (see below), which the fingerprint cannot see: such a build is never reused.
    outside_patches = bool(key.suggestions) and arguments.allow_patching_outside_project
    reusable = status.usable and not outside_patches

    if policy == BuildPolicy.REUSE:
        if reusable and status.record is not None:
            refresh_run_scripts(arguments, status.record.tree)
            message("Reusing the build " + key.build_id + ".\n")
            return BuildOutcome(BuildResult.REUSED, key, status.record.tree, status.record)
        reason = status.reason if not status.usable else "Its suggestions patch files outside of the project."
        return BuildOutcome(
            BuildResult.UNAVAILABLE,
            key,
            message="No usable build " + key.build_id + " and compiling is not allowed (reuse): " + reason,
        )
    if policy == BuildPolicy.AUTO and reusable and status.record is not None:
        refresh_run_scripts(arguments, status.record.tree)
        message("Reusing the build " + key.build_id + " (compiled " + _age(status.record) + ").\n")
        return BuildOutcome(BuildResult.REUSED, key, status.record.tree, status.record)
    if status.state == BuildState.STALE:
        message("The build " + key.build_id + " is stale. " + status.reason + "\n")

    # a new build replaces the old one: its manifest must not outlive the tree
    try:
        os.remove(manifest_path_of(arguments.project_dir, key))
    except OSError:
        pass
    # taken before the copy, so that a change while copying makes the build stale rather than wrongly current
    parts = compute_fingerprint_parts(arguments, key, compile_script, settings_path)
    tree = build_tree_path_of(arguments.project_root, key)

    message("Copying project to " + tree + "...\n")
    try:
        copy_configuration(
            arguments, config_path, settings_path, destination=tree, leave_out_of_dot_discopop=DATA_LEFT_OUT_OF_BUILDS
        )
    except Exception as error:
        return BuildOutcome(BuildResult.COPY_FAILED, key, message="Error copying project: " + str(error))

    application_result = get_application_result(tree)
    try:
        if application_result is not None and application_result.failure:
            if on_application_failure is not None:
                on_application_failure(tree, application_result)
            _discard_tree(arguments, tree)
            return BuildOutcome(BuildResult.APPLICATION_FAILED, key, application_result=application_result, tree=None)

        message("Compiling...\n")
        compile_result = execute_configuration(
            arguments,
            tree,
            config_path,
            settings_path,
            compile_script,
            thread_count,
            timeout,
            process_started_callback=process_started_callback,
        )
        if compile_result is None or compile_result[0] != 0:
            _discard_tree(arguments, tree)
            return BuildOutcome(
                BuildResult.COMPILE_FAILED,
                key,
                compile_result=compile_result,
                application_result=application_result,
                message="Compilation failed.",
            )
        record = make_record(arguments, key, compile_script, settings_path, tree, compile_result[1], parts)
        write_build(arguments.project_dir, record)
        return BuildOutcome(
            BuildResult.BUILT,
            key,
            tree=tree,
            record=record,
            compile_result=compile_result,
            application_result=application_result,
        )
    finally:
        # files outside of the project, which the copy does not isolate, are needed patched by the compilation only
        try:
            restore_outside_patches(tree)
        except Exception as error:
            logger.error("Restoring the files outside the project failed: " + str(error))


def _discard_tree(arguments: ProjectManagerArguments, tree: PATH) -> None:
    """Remove the tree of a build that did not succeed, unless the user asked to keep project copies."""
    if arguments.skip_cleanup:
        return
    try:
        # the outside files are restored by the caller's ``finally``, which needs the patches in the tree
        restore_outside_patches(tree)
        shutil.rmtree(tree)
    except OSError:
        pass


def _age(record: BuildRecord) -> str:
    import time

    seconds = max(0, int(time.time() - record.built_at))
    if seconds < 120:
        return str(seconds) + " s ago"
    if seconds < 7200:
        return str(seconds // 60) + " min ago"
    if seconds < 172800:
        return str(seconds // 3600) + " h ago"
    return str(seconds // 86400) + " days ago"


__all__ = [
    "BuildOutcome",
    "BuildResult",
    "BuildLockAborted",
    "build_lock",
    "delete_build",
    "ensure_build",
]

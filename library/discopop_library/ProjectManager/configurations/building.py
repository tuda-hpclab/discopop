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
from typing import Callable, Dict, Iterator, List, Optional, Set, Tuple

import subprocess

from filelock import FileLock, Timeout

from discopop_library.PatchApplicator.PatchApplicationResult import PatchApplicationResult
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.builds import (
    BuildFiles,
    BuildKey,
    BuildPolicy,
    BuildRecord,
    BuildState,
    accepted_changes_text,
    build_status,
    build_lock_path_of,
    build_tree_path_of,
    compute_fingerprint,
    delete_build,
    forget_build,
    kept_tree_path_of,
    key_of,
    left_out_of,
    list_builds,
    make_record,
    manifest_path_of,
    remove_build_files,
    tree_key,
    write_build,
)
from discopop_library.ProjectManager.configurations.copy_exclusions import CopyExclusions
from discopop_library.ProjectManager.configurations.copying import (
    copy_configuration,
    copy_dot_discopop,
    get_application_result,
    patch_applicator_dir_of,
    restore_outside_patches,
)
from discopop_library.ProjectManager.configurations.tree_sync import (
    BUILDING,
    CLEAN,
    SYNCING,
    TreeState,
    clean_outputs,
    copy_set,
    read_tree_state,
    remove_tree_state,
    set_tree_state,
    sync_tree,
    write_tree_state,
)
from discopop_library.PatchApplicator.PatchApplicationResult import clear_application_result
from discopop_library.PatchApplicator.PatchApplicatorArguments import PatchApplicatorArguments
from discopop_library.PatchApplicator.outside_project import patch_target_paths, read_file_mapping_paths
from discopop_library.PatchApplicator.patch_applicator import run_with_result as apply_suggestions
from discopop_library.ProjectManager.services.copy_exclude import load_copy_exclude
from discopop_library.ProjectManager.configurations.execution import execute_configuration
from discopop_library.ProjectManager.services import callpath_pruning

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
    """Serializes everything that uses or changes the build tree of ``key`` (building and running in it); the
    builds of all sets of suggestions of a configuration and mode share one tree, and so this lock.

    Waits as long as another run holds the lock, calling ``on_wait`` once, and raises :class:`BuildLockAborted`
    if ``should_abort`` says so meanwhile.
    """
    lock_path = build_lock_path_of(arguments.project_dir, key)
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    lock = FileLock(lock_path)
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


def _accepted_note(arguments: ProjectManagerArguments, key: BuildKey) -> str:
    text = accepted_changes_text(arguments.project_dir, key)
    return text + "\n" if text else ""


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
    output_callback: Optional[Callable[[str], None]] = None,
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
            message("Reusing the build " + key.build_id + ".\n" + _accepted_note(arguments, key))
            return BuildOutcome(BuildResult.REUSED, key, status.record.tree, status.record)
        reason = status.reason if not status.usable else "Its suggestions patch files outside of the project."
        return BuildOutcome(
            BuildResult.UNAVAILABLE,
            key,
            message="No usable build " + key.build_id + " and compiling is not allowed (reuse): " + reason,
        )
    if policy == BuildPolicy.AUTO and reusable and status.record is not None:
        refresh_run_scripts(arguments, status.record.tree)
        message(
            "Reusing the build "
            + key.build_id
            + " (compiled "
            + _age(status.record)
            + ").\n"
            + _accepted_note(arguments, key)
        )
        return BuildOutcome(BuildResult.REUSED, key, status.record.tree, status.record)
    if status.state == BuildState.STALE:
        message("The build " + key.build_id + " is stale. " + status.reason + "\n")

    # a new build replaces the old one: its manifest must not outlive the tree
    try:
        os.remove(manifest_path_of(arguments.project_dir, key))
    except OSError:
        pass
    remove_build_files(arguments.project_dir, key)
    # taken before the copy, so that a change while copying makes the build stale rather than wrongly current
    # computed once: the fingerprint describes the pruning the compilation below uses, even if hotspot results change
    pruning_environment = callpath_pruning.environment(arguments, key.configuration) if key.mode == "dp" else None
    parts, entries = compute_fingerprint(arguments, key, compile_script, settings_path, pruning_environment)
    kept_tree = _uses_kept_tree(arguments, key)
    tree = (
        kept_tree_path_of(arguments.project_root, key) if kept_tree else build_tree_path_of(arguments.project_root, key)
    )

    try:
        if kept_tree:
            failed_application = _prepare_kept_tree(arguments, key, tree, message, on_application_failure)
            if failed_application is not None:
                return BuildOutcome(
                    BuildResult.APPLICATION_FAILED, key, application_result=failed_application, tree=None
                )
        else:
            message("Copying project to " + tree + "...\n")
            copy_configuration(
                arguments,
                config_path,
                settings_path,
                destination=tree,
                leave_out_of_dot_discopop=DATA_LEFT_OUT_OF_BUILDS,
                on_left_out=lambda text: message(text + "\n"),
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
            result_annotations={"build_id": key.build_id},
            output_callback=output_callback,
            callpath_pruning_environment=pruning_environment,
        )
        if compile_result is None or compile_result[0] != 0:
            # the files of a kept tree are those of the project, but its outputs are unknown: copied anew next time
            remove_tree_state(arguments.project_dir, tree_key(key).build_id)
            _discard_tree(arguments, tree)
            return BuildOutcome(
                BuildResult.COMPILE_FAILED,
                key,
                compile_result=compile_result,
                application_result=application_result,
                message="Compilation failed.",
            )
        if kept_tree:
            set_tree_state(arguments.project_dir, tree_key(key).build_id, CLEAN)
            # the builds of other suggestions in the tree are gone (their runs stay)
            for other in list_builds(arguments.project_dir):
                if other.build_id != key.build_id and os.path.abspath(other.tree) == os.path.abspath(tree):
                    forget_build(arguments.project_dir, key_of(other))
        record = make_record(arguments, key, compile_script, settings_path, tree, compile_result[1], parts)
        write_build(
            arguments.project_dir, record, BuildFiles(sources=entries, left_out=left_out_of(arguments, entries))
        )
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


def _uses_kept_tree(arguments: ProjectManagerArguments, key: BuildKey) -> bool:
    """Whether the build ``key`` is compiled in the kept tree of its configuration and mode, updated instead of
    copied (``configurations/tree_sync.py``). Not a build whose suggestions may patch files outside of the project:
    those are patched in place, which the tree does not isolate."""
    return not (key.suggestions and arguments.allow_patching_outside_project)


def _prepare_kept_tree(
    arguments: ProjectManagerArguments,
    key: BuildKey,
    tree: PATH,
    message: Callable[[str], None],
    on_application_failure: Optional[Callable[[PATH, PatchApplicationResult], None]] = None,
) -> Optional[PatchApplicationResult]:
    """Make ``tree`` hold what a fresh copy of the project with the suggestions of ``key`` would: the files of the
    project (written only where they differ), the patched files instead of the originals, no outputs of an earlier
    compilation, and a new copy of the project's ``.discopop``. A tree in an unknown state (none recorded, an
    interrupted update or compilation, changed by a validation build) is filled from scratch.

    The suggestions are applied to copies of the files they patch in a scratch directory first; if that fails,
    the tree is not touched and the result of the application is returned (``on_application_failure`` is called
    with the scratch directory)."""
    project_dir = arguments.project_dir
    tree_id = tree_key(key).build_id
    state = read_tree_state(project_dir, tree_id)
    exclusions = CopyExclusions(arguments.project_root, listed=load_copy_exclude(project_dir))
    files = copy_set(exclusions)
    scratch = tree + ".scratch"
    overrides: Dict[str, PATH] = {}
    try:
        if key.suggestions:
            overrides, application_result = _apply_in_scratch(arguments, key, scratch)
            if application_result is not None and application_result.failure:
                logger.error("Suggestion application incomplete: " + application_result.summary())
                if on_application_failure is not None:
                    on_application_failure(scratch, application_result)
                return application_result
        fresh = state is None or state.state != CLEAN or not os.path.isdir(tree)
        if fresh:
            message("Copying project to " + tree + "...\n")
            if os.path.lexists(tree):
                shutil.rmtree(tree)
            os.makedirs(tree)
            previous: Dict[str, str] = {}
        else:
            assert state is not None
            message("Updating the build tree " + tree + "...\n")
            previous = state.synced
        report = exclusions.report()
        if report is not None:
            message(report + "\n")
        write_tree_state(project_dir, tree_id, TreeState(dict(previous), [], SYNCING))
        result = sync_tree(tree, files, previous, overrides)
        removed = clean_outputs(tree, result.synced, arguments.project_root)
        copy_dot_discopop(arguments, tree, DATA_LEFT_OUT_OF_BUILDS)
        if key.suggestions:
            # what the application recorded: the applied suggestions, the result, the shifted lines
            shutil.rmtree(patch_applicator_dir_of(tree), ignore_errors=True)
            shutil.copytree(os.path.join(scratch, ".discopop", "patch_applicator"), patch_applicator_dir_of(tree))
            line_mapping = os.path.join(scratch, ".discopop", "line_mapping.json")
            if os.path.exists(line_mapping):
                shutil.copyfile(line_mapping, os.path.join(tree, ".discopop", "line_mapping.json"))
        else:
            clear_application_result(patch_applicator_dir_of(tree))
        write_tree_state(project_dir, tree_id, TreeState(result.synced, sorted(key.suggestions), BUILDING))
        if not fresh:
            message(
                "Changed files written: "
                + str(len(result.written))
                + ", deleted: "
                + str(len(result.deleted))
                + "; outputs of the last compilation removed: "
                + str(len(removed))
                + ".\n"
            )
        return None
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _apply_in_scratch(
    arguments: ProjectManagerArguments, key: BuildKey, scratch: PATH
) -> Tuple[Dict[str, PATH], Optional[PatchApplicationResult]]:
    """Apply the suggestions of ``key`` to copies of the files they patch, in ``scratch`` (a ``.discopop`` of its own
    whose ``FileMapping.txt`` names the copies). Returns the patched files (relative path in the project -> copy)
    and the result of the application."""
    root = os.path.abspath(arguments.project_root)
    project_dot = os.path.abspath(arguments.dot_dp)
    if os.path.lexists(scratch):
        shutil.rmtree(scratch)
    scratch = os.path.abspath(scratch)
    scratch_dot = os.path.join(scratch, ".discopop")
    os.makedirs(scratch_dot)
    os.symlink(os.path.join(project_dot, "patch_generator"), os.path.join(scratch_dot, "patch_generator"))
    for name in ("line_mapping.json",):
        if os.path.exists(os.path.join(project_dot, name)):
            shutil.copyfile(os.path.join(project_dot, name), os.path.join(scratch_dot, name))
    if os.path.isdir(os.path.join(project_dot, "patch_applicator")):
        shutil.copytree(os.path.join(project_dot, "patch_applicator"), os.path.join(scratch_dot, "patch_applicator"))
    clear_application_result(os.path.join(scratch_dot, "patch_applicator"))

    mapping = read_file_mapping_paths(project_dot)
    target_ids: Set[int] = set()
    for suggestion in key.suggestions:
        for target in patch_target_paths(project_dot, suggestion, mapping):
            target_ids.update(file_id for file_id, path in mapping.items() if path == target)
    overrides: Dict[str, PATH] = {}
    lines: List[str] = []
    for file_id in sorted(target_ids):
        path = mapping[file_id]
        relative = os.path.relpath(os.path.abspath(path), root)
        if relative != ".." and not relative.startswith(".." + os.sep) and os.path.isfile(path):
            copy = os.path.join(scratch, relative)
            os.makedirs(os.path.dirname(copy), exist_ok=True)
            shutil.copy2(path, copy)
            overrides[relative.replace(os.sep, "/")] = copy
            path = copy
        # a file outside of the project keeps its path: the patch applicator refuses it (outside_project.py)
        lines.append(str(file_id) + "\t" + path + "\n")
    with open(os.path.join(scratch_dot, "FileMapping.txt"), "w") as file:
        file.writelines(lines)

    pa_args = PatchApplicatorArguments(
        verbose=False,
        apply=list(key.suggestions),
        rollback=[],
        clear=False,
        load=False,
        list=False,
        log_level=arguments.log_level,
        write_log=arguments.write_log,
        allow_outside_project=False,
    )
    home_dir = os.getcwd()
    os.chdir(scratch_dot)
    try:
        _retval, application_result = apply_suggestions(pa_args)
    finally:
        os.chdir(home_dir)
    return overrides, application_result


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

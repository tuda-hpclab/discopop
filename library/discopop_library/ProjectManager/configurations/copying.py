# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import logging
import os
from pathlib import Path
import shutil
from typing import List, Optional
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.PatchApplicator.PatchApplicationResult import (
    PatchApplicationResult,
    clear_application_result,
    read_application_result,
)
from discopop_library.PatchApplicator.PatchApplicatorArguments import PatchApplicatorArguments
from discopop_library.PatchApplicator.outside_project import (
    find_outside_project_targets,
    log_skipped_outside_suggestions,
    split_by_outside_project,
)
from discopop_library.PatchApplicator.patch_applicator import run_with_result as apply_suggestions

PATH = str
logger = logging.getLogger("ConfigurationManager")


def patch_applicator_dir_of(project_copy_path: PATH) -> PATH:
    """The ``patch_applicator`` directory inside a project copy's ``.discopop``."""
    return os.path.join(project_copy_path, ".discopop", "patch_applicator")


def get_application_result(project_copy_path: PATH) -> Optional[PatchApplicationResult]:
    """The suggestion application outcome recorded for a project copy, if any.

    Returned as written by :func:`copy_configuration`; ``None`` means no suggestions
    were requested for this copy.
    """
    return read_application_result(patch_applicator_dir_of(project_copy_path))


def copy_configuration(
    arguments: ProjectManagerArguments,
    config_path: PATH,
    settings_path: PATH,
    configuration_id: Optional[int] = None,
) -> PATH:

    config_name = os.path.basename(config_path)
    settings_name = os.path.basename(settings_path)

    # create project copy
    project_copy_folder_name = config_name + "_" + settings_name + "_" + os.path.basename(arguments.project_root)
    if configuration_id is not None:
        project_copy_folder_name += "_" + str(configuration_id)
    project_copy_path = os.path.join(Path(arguments.project_root).parent.absolute(), project_copy_folder_name)
    if os.path.exists(project_copy_path):
        shutil.rmtree(project_copy_path)
    shutil.copytree(arguments.project_root, project_copy_path)
    # correct paths in Filemapping.txt
    fmap_path = os.path.join(project_copy_path, ".discopop", "FileMapping.txt")
    if os.path.exists(fmap_path):
        fmap_lines = []
        with open(fmap_path, "r") as f:
            fmap_lines = f.readlines()
        for idx, line in enumerate(fmap_lines):
            # only paths below the project root move into the copy; a plain substring replacement would also
            # rewrite a directory outside the project that merely starts with the root ("/p/proj2" for "/p/proj")
            file_id, separator, file_path = line.partition("\t")
            stripped_path = file_path.rstrip("\n")
            line_ending = file_path[len(stripped_path) :]
            if separator and (
                stripped_path == arguments.project_root or stripped_path.startswith(arguments.project_root + os.sep)
            ):
                moved_path = project_copy_path + stripped_path[len(arguments.project_root) :]
                fmap_lines[idx] = file_id + separator + moved_path + line_ending
        with open(fmap_path, "w") as f:
            for line in fmap_lines:
                f.write(line)

    # apply the specified parallelization suggestions if requested
    if arguments.apply_suggestions is not None:
        suggestions: List[str] = []
        dp_folder_path = os.path.join(project_copy_path, ".discopop")
        if arguments.apply_suggestions == "auto":
            auto_tuner_results_path = os.path.join(dp_folder_path, "auto_tuner", "results.json")
            if os.path.exists(auto_tuner_results_path):
                with open(auto_tuner_results_path, "r") as f:
                    auto_tuner_results = json.load(f)
                for configuration in auto_tuner_results:
                    for sugg in auto_tuner_results[configuration]["applied_suggestions"]:
                        if sugg not in suggestions:
                            suggestions.append(sugg)
        elif arguments.apply_suggestions == "prm":
            prm_results_path = os.path.join(dp_folder_path, "parallel_region_merger", "results.json")
            if os.path.exists(prm_results_path):
                with open(prm_results_path, "r") as f:
                    prm_results = json.load(f)
                for configuration in prm_results:
                    for sugg in prm_results[configuration]["applied_suggestions"]:
                        if sugg not in suggestions:
                            suggestions.append(sugg)
        else:
            suggestions = arguments.apply_suggestions.split(",")

        # Suggestions that patch files outside the project are never part of an automatic selection ("auto", "prm"):
        # the copy does not isolate those files. An explicit list reaches the patch applicator, which refuses them
        # unless the caller allowed it (a visible failure of the run, see PatchApplicationResult.refused).
        if arguments.apply_suggestions in ("auto", "prm"):
            suggestions, outside = split_by_outside_project(dp_folder_path, suggestions)
            log_skipped_outside_suggestions(logger, "Project manager (" + arguments.apply_suggestions + ")", outside)

        pa_args = PatchApplicatorArguments(
            verbose=False,
            apply=suggestions,
            rollback=[],
            clear=False,
            load=False,
            list=False,
            log_level=arguments.log_level,
            write_log=arguments.write_log,
            allow_outside_project=arguments.allow_patching_outside_project
            and arguments.apply_suggestions not in ("auto", "prm"),
        )
        home_dir = os.getcwd()
        os.chdir(dp_folder_path)
        try:
            _retval, application_result = apply_suggestions(pa_args)
        finally:
            os.chdir(home_dir)
        # A failed application leaves the copy holding the *original*, sequential
        # code. Callers must be able to see that instead of measuring it as if it
        # were parallelized, so the outcome is logged here and persisted by the
        # patch applicator for later consumers (see get_application_result).
        if application_result is not None and application_result.failure:
            logger.error("Suggestion application incomplete: " + application_result.summary())
    else:
        # the copy inherits the source project's .discopop; a result file left over
        # from an earlier run must not be mistaken for this copy's outcome
        clear_application_result(patch_applicator_dir_of(project_copy_path))

    return project_copy_path


def restore_outside_patches(project_copy_path: PATH) -> List[str]:
    """Roll back the suggestions applied to ``project_copy_path`` that patched files outside the project.

    The copy isolates only the files below the project root; an outside target of a manually allowed suggestion was
    patched in place. Call this after the run of a copy -- also when it failed or was stopped, and before the copy is
    deleted (its ``.discopop`` holds the patches the rollback needs). Returns the rolled back suggestions.

    The rollback is per suggestion: the files of such a suggestion inside the copy are restored as well. It is
    idempotent (a rolled back suggestion is not applied any more and is skipped).
    """
    application_result = get_application_result(project_copy_path)
    if application_result is None:
        return []
    dp_folder_path = os.path.join(project_copy_path, ".discopop")
    if not os.path.isdir(dp_folder_path):
        return []
    # only what is applied still: a suggestion that was rolled back already (or never applied) is left alone
    applied_file = os.path.join(patch_applicator_dir_of(project_copy_path), "applied_suggestions.json")
    try:
        with open(applied_file, "r") as f:
            still_applied = {str(sugg) for sugg in json.load(f)["applied"]}
    except (OSError, ValueError, KeyError):
        return []
    outside = find_outside_project_targets(
        dp_folder_path, [sugg for sugg in application_result.applied if sugg in still_applied]
    )
    if not outside:
        return []
    suggestions = sorted(outside)
    pa_args = PatchApplicatorArguments(
        verbose=False,
        apply=[],
        rollback=suggestions,
        clear=False,
        load=False,
        list=False,
        log_level="WARNING",
        write_log=False,
    )
    home_dir = os.getcwd()
    os.chdir(dp_folder_path)
    try:
        retval, _ = apply_suggestions(pa_args)
    finally:
        os.chdir(home_dir)
    if retval not in (0, 3):
        logger.error(
            "Rolling back the suggestions "
            + ", ".join(suggestions)
            + " failed (return code "
            + str(retval)
            + "); these files outside the project may still be modified: "
            + ", ".join(sorted({t for targets in outside.values() for t in targets}))
        )
    else:
        logger.info("Restored the files outside the project of the suggestions " + ", ".join(suggestions))
    return suggestions

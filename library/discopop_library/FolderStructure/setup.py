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

from discopop_library.FolderStructure.teardown import teardown_explorer
from discopop_library.LineMapping.initialize import initialize_line_mapping
from discopop_library.PathManagement.PathManagement import load_file_mapping

logger = logging.getLogger("FolderStructure").getChild("Setup")


def setup_explorer(path: str = "") -> None:
    tmp_logger = logger.getChild("explorer")
    tmp_logger.debug("Start")

    teardown_explorer(path)

    # create explorer directory if not already present
    if not os.path.exists(os.path.join(path, "explorer")):
        os.mkdir(os.path.join(path, "explorer"))
    # create file to store next free pattern ids if not already present
    if not os.path.exists("next_free_pattern_id.txt"):
        with open("next_free_pattern_id.txt", "w") as f:
            f.write(str(0))

    # initialize the line_mapping.json
    initialize_line_mapping(load_file_mapping(os.path.join(path, "FileMapping.txt")), path)

    tmp_logger.debug("Done")


def setup_patch_generator(path: str = "") -> None:
    tmp_logger = logger.getChild("patch_generator")
    tmp_logger.debug("Start")
    patch_generator_dir = os.path.join(path, "patch_generator")
    if not os.path.exists(patch_generator_dir):
        os.mkdir(patch_generator_dir)

    setup_patch_applicator()

    tmp_logger.debug("Done")


def setup_auto_tuner(path: str = "") -> None:
    tmp_logger = logger.getChild("auto_tuner")
    tmp_logger.debug("Start")
    auto_tuner_dir = os.path.join(path, "auto_tuner")
    if not os.path.exists(auto_tuner_dir):
        os.mkdir(auto_tuner_dir)
    tmp_logger.debug("Done")


def setup_patch_repair(path: str = "") -> None:
    tmp_logger = logger.getChild("patch_repair")
    tmp_logger.debug("Start")
    patch_repair_dir = os.path.join(path, "patch_repair")
    if not os.path.exists(patch_repair_dir):
        os.mkdir(patch_repair_dir)
    # Transcripts and backups are written per suggestion; creating the roots here keeps
    # every writer free of "does the parent exist" checks.
    for sub_dir in ["backups", "attempts"]:
        if not os.path.exists(os.path.join(patch_repair_dir, sub_dir)):
            os.mkdir(os.path.join(patch_repair_dir, sub_dir))
    tmp_logger.debug("Done")


def setup_parallel_region_merger(path: str = "") -> None:
    tmp_logger = logger.getChild("parallel_region_merger")
    tmp_logger.debug("Start")
    prm_dir = os.path.join(path, "parallel_region_merger")
    if not os.path.exists(prm_dir):
        os.mkdir(prm_dir)
    tmp_logger.debug("Done")


def setup_patch_applicator(path: str = "") -> None:
    tmp_logger = logger.getChild("patch_applicator")
    tmp_logger.debug("Start")
    # create a directory for the patch applicator
    patch_applicator_dir = os.path.join(path, "patch_applicator")
    if not os.path.exists(patch_applicator_dir):
        os.mkdir(patch_applicator_dir)

    # create a file to store applied suggestions
    applied_suggestions_file = os.path.join(patch_applicator_dir, "applied_suggestions.json")
    if not os.path.exists(applied_suggestions_file):
        with open(applied_suggestions_file, "w+") as f:
            f.write(json.dumps({"applied": []}))

    tmp_logger.debug("Done")


def setup_optimizer(path: str = "") -> None:
    tmp_logger = logger.getChild("optimizer")
    tmp_logger.debug("Start")
    optimizer_dir = os.path.join(path, "optimizer")
    if not os.path.exists(optimizer_dir):
        os.mkdir(optimizer_dir)

    tmp_logger.debug("Done")


def setup_sanity_checker(path: str = "") -> None:
    tmp_logger = logger.getChild("sanity_checker")
    tmp_logger.debug("Start")
    sanity_checker_dir = os.path.join(path, "sanity_checker")
    if not os.path.exists(sanity_checker_dir):
        os.mkdir(sanity_checker_dir)

    tmp_logger.debug("Done")

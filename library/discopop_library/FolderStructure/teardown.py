# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import shutil
from discopop_library.LineMapping.delete import delete_line_mapping

import logging

logger = logging.getLogger("FolderStructure").getChild("Teardown")


def teardown_explorer(path: str = "") -> None:
    tmp_logger = logger.getChild("explorer")
    tmp_logger.debug("Start")
    # reset environment, if previous results existed
    if os.path.exists(os.path.join(path, "explorer")):
        shutil.rmtree(os.path.join(path, "explorer"))
    # reset file lock in case of prior crashes
    if os.path.exists("next_free_pattern_id.txt.lock"):
        os.remove("next_free_pattern_id.txt.lock")
    if os.path.exists("next_free_pattern_id.txt"):
        os.remove("next_free_pattern_id.txt")
    delete_line_mapping(path)

    teardown_patch_generator(path)
    teardown_patch_applicator(path)
    teardown_optimizer(path)

    tmp_logger.debug("Done")


def teardown_patch_generator(path: str = "") -> None:
    tmp_logger = logger.getChild("patch_generator")
    tmp_logger.debug("Start")
    patch_generator_dir = os.path.join(path, "patch_generator")
    if os.path.exists(patch_generator_dir):
        shutil.rmtree(patch_generator_dir)
    teardown_patch_applicator(path)
    tmp_logger.debug("Done")


def teardown_parallel_region_merger(path: str = "") -> None:
    tmp_logger = logger.getChild("parallel_region_merger")
    tmp_logger.debug("Start")
    prm_dir = os.path.join(path, "parallel_region_merger")
    if os.path.exists(prm_dir):
        shutil.rmtree(prm_dir)
    tmp_logger.debug("Done")


def teardown_patch_applicator(path: str = "") -> None:
    tmp_logger = logger.getChild("patch_applicator")
    tmp_logger.debug("Start")
    patch_applicator_dir = os.path.join(path, "patch_applicator")
    if os.path.exists(patch_applicator_dir):
        shutil.rmtree(patch_applicator_dir)
    tmp_logger.debug("Done")


def teardown_optimizer(path: str = "") -> None:
    tmp_logger = logger.getChild("optimizer")
    tmp_logger.debug("Start")
    optimizer_dir = os.path.join(path, "optimizer")
    if os.path.exists(optimizer_dir):
        shutil.rmtree(optimizer_dir)

    tmp_logger.debug("Done")


def teardown_sanity_checker(path: str = "") -> None:
    tmp_logger = logger.getChild("sanity_checker")
    tmp_logger.debug("Start")
    sanity_checker_dir = os.path.join(path, "sanity_checker")
    if os.path.exists(sanity_checker_dir):
        shutil.rmtree(sanity_checker_dir)

    tmp_logger.debug("Done")

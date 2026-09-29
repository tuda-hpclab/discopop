# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
import os.path
import shutil
from pathlib import Path
from typing import Dict

from discopop_library.PatchApplicator.PatchApplicatorArguments import PatchApplicatorArguments
from discopop_library.PatchApplicator.rollback import rollback_patches


def clear_patches(
    file_mapping: Dict[int, Path],
    arguments: PatchApplicatorArguments,
    applied_suggestions_file: str,
    patch_generator_dir: str,
) -> int:
    # save the currently applied suggestions. Overwrites old saves
    shutil.copyfile(applied_suggestions_file, applied_suggestions_file + ".save")

    # get the list of applied suggestions
    with open(applied_suggestions_file, "r") as f:
        applied_suggestions = json.loads(f.read())["applied"]

    # rollback all suggestions in inverse order
    applied_suggestions.reverse()
    retval = rollback_patches(
        applied_suggestions, file_mapping, arguments, applied_suggestions_file, patch_generator_dir
    )

    return retval

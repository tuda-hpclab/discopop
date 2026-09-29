# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
import os.path
from pathlib import Path
from typing import Dict

from discopop_library.PatchApplicator.PatchApplicatorArguments import PatchApplicatorArguments
from discopop_library.PatchApplicator.apply import apply_patches


def load_patches(
    file_mapping: Dict[int, Path],
    arguments: PatchApplicatorArguments,
    applied_suggestions_file: str,
    patch_generator_dir: str,
) -> int:
    # check if a saved configuration exists
    if not os.path.exists(applied_suggestions_file + ".save"):
        raise FileNotFoundError(
            "Nothing to be loaded. Exiting." "\nExpected file: ", applied_suggestions_file + ".save"
        )

    # get the list of suggestions to be applied
    with open(applied_suggestions_file + ".save", "r") as f:
        suggestions_to_be_applied = json.loads(f.read())["applied"]

    # apply all suggestions
    result = apply_patches(
        suggestions_to_be_applied, file_mapping, arguments, applied_suggestions_file, patch_generator_dir
    )
    if result.failure:
        print("WARNING: " + result.summary())

    return result.retval

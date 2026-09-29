# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import logging
import os.path
from pathlib import Path
import shutil
from typing import Dict, List, Tuple
from discopop_library.CodeGenerator.CodeGenerator import from_json_strings
from discopop_library.PatchGenerator.PatchGeneratorArguments import PatchGeneratorArguments
from discopop_library.PatchGenerator.diffs import get_diffs_from_modified_code
from discopop_library.PatchGenerator.from_optimizer_output import from_optimizer_output

logger = logging.getLogger("PatchGenerator")


def from_json_patterns(
    arguments: PatchGeneratorArguments,
    patterns_by_type: Dict[str, List[str]],
    file_mapping: Dict[int, Path],
    patch_generator_dir: str,
) -> None:
    # collect metadata
    # collect patterns_by_id
    max_pattern_id = 0
    patterns_by_id: Dict[int, Tuple[str, str]] = dict()
    for suggestion_type in patterns_by_type:
        for suggestion in patterns_by_type[suggestion_type]:
            suggestion_dict = json.loads(suggestion)
            suggestion_id = suggestion_dict["pattern_id"]
            if max_pattern_id < suggestion_id:
                max_pattern_id = suggestion_id
            patterns_by_id[suggestion_id] = (suggestion_type, suggestion)

    # generate code modifications from each suggestion, create a patch and store the patch
    # using the suggestions unique id
    if arguments.verbose:
        print("Generating modified code...")
    for suggestion_type in patterns_by_type:
        if suggestion_type == "version":
            continue
        for suggestion in patterns_by_type[suggestion_type]:
            # parse benchmarking flags
            if arguments.only_optimizer_output_patterns and suggestion_type != "optimizer_output":
                # ignore all other pattern types
                logger.debug("Ignoring pattern of type: " + suggestion_type)
                continue

            suggestion_dict = json.loads(suggestion)
            if not suggestion_dict["applicable_pattern"]:
                continue

            # parse benchmarking flags
            if arguments.only_maximum_id_pattern:
                if suggestion_dict["pattern_id"] != max_pattern_id:
                    logger.debug("Skipping pattern: " + str(suggestion_dict["pattern_id"]))
                    continue

            if suggestion_type in ["optimizer_output", "merged_pattern"]:
                from_optimizer_output(file_mapping, patterns_by_type, suggestion, arguments, patch_generator_dir)
                continue

            if arguments.verbose:
                print("Suggestion: ", suggestion)
            # collect patterns to be applied in case of "contains_patterns" relations
            patterns_for_application: Dict[str, List[str]] = dict()
            queue: List[str] = []
            if "contains_patterns" in suggestion_dict:
                for cpi in suggestion_dict["contains_patterns"]:
                    queue.append(patterns_by_id[cpi][1])
            while len(queue) > 0:
                current = queue.pop()
                current_dict = json.loads(current)
                current_suggestion_type = patterns_by_id[current_dict["pattern_id"]][0]
                if current_suggestion_type not in patterns_for_application:
                    patterns_for_application[current_suggestion_type] = []
                patterns_for_application[current_suggestion_type].insert(0, current)

                if "contains_patterns" in current_dict:
                    for contained_pattern_id in current_dict["contains_patterns"]:
                        queue.append(patterns_by_id[contained_pattern_id][1])

            file_id_to_modified_code: Dict[int, str] = from_json_strings(
                file_mapping,
                {suggestion_type: [suggestion]},
                CC=arguments.CC,
                CXX=arguments.CXX,
                skip_compilation_check=True,
                contained_patterns=patterns_for_application,
            )
            # create patches from the modified codes
            file_id_to_patches: Dict[int, str] = get_diffs_from_modified_code(
                file_mapping, file_id_to_modified_code, arguments
            )
            if arguments.verbose:
                print("Patches: ", file_id_to_patches)
            # clear old results and save patches
            suggestion_dict = json.loads(suggestion)
            suggestion_id = suggestion_dict["pattern_id"]
            suggestion_folder_path = os.path.join(patch_generator_dir, str(suggestion_id))
            if arguments.verbose:
                print("Saving patches for suggestion: ", suggestion_id)
            if os.path.exists(suggestion_folder_path):
                shutil.rmtree(suggestion_folder_path)
            os.mkdir(suggestion_folder_path)
            for file_id in file_id_to_patches:
                patch_path = os.path.join(suggestion_folder_path, str(file_id) + ".patch")
                with open(patch_path, "w", newline="") as f:
                    f.write(file_id_to_patches[file_id])

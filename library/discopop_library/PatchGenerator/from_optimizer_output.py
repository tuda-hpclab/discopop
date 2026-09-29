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
import shutil
from typing import Dict, List, Optional, Tuple
from discopop_library.CodeGenerator.CodeGenerator import from_json_strings, from_json_strings_with_mapping
from discopop_library.PatchGenerator.PatchGeneratorArguments import PatchGeneratorArguments
from discopop_library.PatchGenerator.diffs import get_diffs_from_modified_code
from discopop_library.discopop_optimizer.classes.context.Update import Update, construct_update_from_dict
from discopop_library.discopop_optimizer.classes.system.devices.DeviceTypeEnum import DeviceTypeEnum
from discopop_library.discopop_optimizer.classes.types.Aliases import DeviceID
from discopop_library.result_classes.DetectionResult import DetectionResult
import jsonpickle  # type: ignore

from discopop_library.result_classes.OptimizerOutputPattern import OptimizerOutputPattern  # type: ignore


def from_optimizer_output(
    file_mapping: Dict[int, Path],
    patterns_by_type: Dict[str, List[str]],
    optimizer_output_json_str: str,
    arguments: PatchGeneratorArguments,
    patch_generator_dir: str,
) -> None:
    suggestion_strings_with_mapping: Dict[str, List[Tuple[str, DeviceID, Optional[DeviceTypeEnum]]]] = dict()
    if arguments.verbose:
        print("Loading optimizer output: ")

    optimizer_output = json.loads(optimizer_output_json_str)

    # load detectionresult and pet
    if arguments.verbose:
        print("Loading detection result and PET...", end="")
    detection_result_dump_str = ""
    with open(os.path.join("explorer", "detection_result_dump.json")) as f:
        detection_result_dump_str = f.read()
    detection_result: DetectionResult = jsonpickle.decode(detection_result_dump_str, keys=True)
    if arguments.verbose:
        print("Done")

    # build suggestion_strings_with_mapping
    for pattern_values in optimizer_output["applied_patterns"]:
        pattern_id = pattern_values["pattern_id"]
        device_id = pattern_values["device_id"]
        device_type = pattern_values["device_type"]
        for pattern_type in patterns_by_type:
            if pattern_type == "version":
                continue
            for pattern_string in patterns_by_type[pattern_type]:
                loaded_pattern = json.loads(pattern_string)
                if loaded_pattern["pattern_id"] == pattern_id:
                    if pattern_type not in suggestion_strings_with_mapping:
                        suggestion_strings_with_mapping[pattern_type] = []
                    suggestion_strings_with_mapping[pattern_type].append((pattern_string, device_id, device_type))

    # collect data movement information
    if "device_update" not in suggestion_strings_with_mapping:
        suggestion_strings_with_mapping["device_update"] = []
    for data_movement in optimizer_output["data_movement"]:
        update_obj = construct_update_from_dict(data_movement)
        suggestion_strings_with_mapping["device_update"].append(
            (update_obj.get_pattern_string(detection_result.pet), None, None)
        )

    # generate the modified code
    file_id_to_modified_code: Dict[int, str] = from_json_strings_with_mapping(
        file_mapping,
        suggestion_strings_with_mapping,
        CC=arguments.CC,
        CXX=arguments.CXX,
        skip_compilation_check=True,
        host_device_id=optimizer_output["host_device_id"],
    )
    print("MODIFIED CODE: ")
    print(file_id_to_modified_code)

    # create patches from the modified codes
    file_id_to_patches: Dict[int, str] = get_diffs_from_modified_code(file_mapping, file_id_to_modified_code, arguments)
    if arguments.verbose:
        print("Patches: ", file_id_to_patches)
    # save patches
    suggestion_id = optimizer_output["pattern_id"]

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

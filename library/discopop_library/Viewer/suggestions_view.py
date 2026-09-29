# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
import os
from typing import Dict, List, Set
from discopop_library.PathManagement.PathManagement import load_file_mapping
from discopop_library.StatusReporting.console import banner
from discopop_library.Viewer.ViewerArguments import ViewerArguments

logger = logging.getLogger("Viewer").getChild("Suggestions").getChild("Print")


def print_suggestions_overview(arguments: ViewerArguments) -> None:
    if not os.path.exists(arguments.path):
        raise FileNotFoundError(arguments.path)
    if not os.path.exists(os.path.join(arguments.path, "FileMapping.txt")):
        raise FileNotFoundError(os.path.join(arguments.path, "FileMapping.txt"))
    if not os.path.exists(os.path.join(arguments.path, "patch_generator")):
        raise FileNotFoundError(os.path.join(arguments.path, "patch_generator"))

    # collect information for display
    suggestion_to_files_map: Dict[int, Set[int]] = dict()
    files_to_suggestions_map: Dict[int, Set[int]] = dict()

    suggestion_ids = sorted(
        x
        for x in os.listdir(os.path.join(arguments.path, "patch_generator"))
        if os.path.isdir(os.path.join(arguments.path, "patch_generator", x))
    )

    for suggestion_id in suggestion_ids:
        suggestion_to_files_map[int(suggestion_id)] = set()
        file_ids = sorted(
            x.replace(".patch", "")
            for x in os.listdir(os.path.join(arguments.path, "patch_generator", suggestion_id))
            if os.path.isfile(os.path.join(arguments.path, "patch_generator", suggestion_id, x))
        )
        for file_id in file_ids:
            suggestion_to_files_map[int(suggestion_id)].add(int(file_id))
            if int(file_id) not in files_to_suggestions_map:
                files_to_suggestions_map[int(file_id)] = set()
            files_to_suggestions_map[int(file_id)].add(int(suggestion_id))
    file_mapping = load_file_mapping(os.path.join(arguments.path, "FileMapping.txt"))

    banner("Suggestion IDs by files")
    for key_file_id in files_to_suggestions_map:
        print("==> " + str(file_mapping[key_file_id]))
        for val_suggestion_id in files_to_suggestions_map[key_file_id]:
            print("|---> " + str(val_suggestion_id))

    banner("Files by Suggestion IDs")
    for key_suggestion_id in suggestion_to_files_map:
        print("==> " + str(key_suggestion_id))
        for file_id_key in suggestion_to_files_map[key_suggestion_id]:
            print("|---> " + str(file_mapping[file_id_key]))

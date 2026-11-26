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
from typing import Dict, List

from discopop_library.FolderStructure.setup import setup_patch_generator
from discopop_library.JSONHandler.JSONHandler import read_patterns_from_json_to_json
from discopop_library.PatchGenerator.PatchGeneratorArguments import PatchGeneratorArguments
from discopop_library.PatchGenerator.from_json_patterns import from_json_patterns
from discopop_library.PathManagement.PathManagement import load_file_mapping
from discopop_library.StatusReporting.console import stage

# written by discopop_explorer --unsure-suggestions, see design/agent_checked_suggestions.md
UNSURE_SUGGESTIONS_FILE = "unsure_suggestions.json"
# The plain patches of the unsure suggestions. Not below patch_generator/: tools take every directory there for a
# suggestion, and these patches are incorrect as they are.
UNSURE_PATCH_DIR = "patch_generator_unsure"
# the members of an unsure suggestion which are not part of its pattern
_UNSURE_ONLY_KEYS = ("type", "blockers")


def unsure_patterns_by_type(path: str) -> Dict[str, List[str]]:
    """the patterns of the unsure suggestions in path, as read_patterns_from_json_to_json returns them: per pattern
    type, the patterns as JSON strings"""
    with open(path) as f:
        data = json.load(f)
    by_type: Dict[str, List[str]] = dict()
    for entry in data.get("suggestions", []):
        pattern = {key: value for key, value in entry.items() if key not in _UNSURE_ONLY_KEYS}
        by_type.setdefault(str(entry["type"]), []).append(json.dumps(pattern))
    return by_type


def run(arguments: PatchGeneratorArguments) -> None:

    if arguments.verbose:
        print("Started DiscoPoP Patch Generator...")

    setup_patch_generator(os.getcwd())
    patch_generator_dir = os.path.join(os.getcwd(), "patch_generator")

    # get pattern file to load
    if arguments.add_from_json != "None":
        pattern_file_path = arguments.add_from_json
    else:
        pattern_file_path = os.path.join(os.getcwd(), "explorer", "patterns.json")
    if not os.path.exists(pattern_file_path):
        raise FileNotFoundError(
            "No pattern file found. Please execute the discopop_explorer in advance."
            + "\nExpected pattern file: "
            + pattern_file_path
        )
    file_mapping_path = os.path.join(os.getcwd(), "FileMapping.txt")
    if not os.path.exists(file_mapping_path):
        raise FileNotFoundError(
            "No file mapping found. Please execute the discopop_explorer in advance."
            + "\nExpected file: "
            + file_mapping_path
        )

    unsure_file = os.path.join(os.getcwd(), "explorer", UNSURE_SUGGESTIONS_FILE)
    unsure_dir = os.path.join(os.getcwd(), UNSURE_PATCH_DIR)
    # the unsure patches belong to the explorer's patterns, not to patterns added from another file
    with_unsure = arguments.add_from_json == "None" and not arguments.only_optimizer_output_patterns
    # never left over from an earlier explorer run: they would be taken for patches of the current one
    if with_unsure and os.path.exists(unsure_dir):
        shutil.rmtree(unsure_dir)

    with stage("Loading file mapping and patterns", 1, total=2):
        if arguments.verbose:
            print("Loading file mapping...")
        file_mapping = load_file_mapping(file_mapping_path)

        if arguments.verbose:
            print("Loading patterns...")
        patterns_by_type = read_patterns_from_json_to_json(pattern_file_path, [])
        if arguments.verbose:
            print("Patterns: ", patterns_by_type)

    with stage("Generating patches", 2, total=2):
        from_json_patterns(arguments, patterns_by_type, file_mapping, patch_generator_dir)

    if with_unsure and os.path.exists(unsure_file):
        unsure_by_type = unsure_patterns_by_type(unsure_file)
        if sum(len(patterns) for patterns in unsure_by_type.values()) > 0:
            os.mkdir(unsure_dir)
            with stage("Generating the patches of the unsure suggestions"):
                from_json_patterns(arguments, unsure_by_type, file_mapping, unsure_dir)

    if arguments.verbose:
        print("Done.")

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import logging
import os.path

from discopop_library.AnalysisRecord import record_step
from discopop_library.FolderStructure.setup import setup_patch_generator
from discopop_library.JSONHandler.JSONHandler import read_patterns_from_json_to_json
from discopop_library.PatchGenerator.PatchGeneratorArguments import PatchGeneratorArguments
from discopop_library.PatchGenerator.from_json_patterns import from_json_patterns
from discopop_library.PathManagement.PathManagement import load_file_mapping


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

    if arguments.verbose:
        print("Loading file mapping...")
    file_mapping = load_file_mapping(file_mapping_path)

    if arguments.verbose:
        print("Loading patterns...")
    patterns_by_type = read_patterns_from_json_to_json(pattern_file_path, [])
    if arguments.verbose:
        print("Patterns: ", patterns_by_type)

    from_json_patterns(arguments, patterns_by_type, file_mapping, patch_generator_dir)

    # Only the complete patch set generated from the explorer's own patterns.json is derived from the recorded pattern
    # detection; patterns added from another file, or a benchmarking restriction, make it something else.
    if arguments.add_from_json == "None" and not (
        arguments.only_optimizer_output_patterns or arguments.only_maximum_id_pattern
    ):
        try:
            record_step(os.getcwd(), "patch_generation", {})
        except Exception as e:  # bookkeeping must never fail the run
            logging.getLogger("PatchGenerator").warning("Could not record the patch generation: %s", e)

    if arguments.verbose:
        print("Done.")

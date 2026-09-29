# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import jsons  # type: ignore

from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_library.CodeGenerator.classes.ContentBuffer import ContentBuffer
from discopop_library.CodeGenerator.classes.UnpackedSuggestion import UnpackedSuggestion
from discopop_library.discopop_optimizer.classes.system.devices.DeviceTypeEnum import DeviceTypeEnum
from discopop_library.discopop_optimizer.classes.types.Aliases import DeviceID


def from_pattern_info(
    file_mapping: Dict[int, Path],
    patterns_by_type: Dict[str, List[PatternInfo]],
    skip_compilation_check: bool = False,
    compile_check_command: Optional[str] = None,
    CC: str = "clang",
    CXX: str = "clang++",
) -> Dict[int, str]:
    """Insert the given parallel patterns into the original source code.
    Returns a dictionary which maps the ID of every modified file to the updated contents of the file.
    This method does not modify the original source code.
    Only fileIDs of files which would be modified occur as keys in the returned dictionary.
    For now, it is assumed that the given patterns are independent of each other, i.e. no nesting exists.
    """
    # convert patterns to json strings so that only a single interface has to be maintained
    pattern_json_strings_by_type: Dict[str, List[str]] = dict()
    for type_str in patterns_by_type:
        if type_str not in pattern_json_strings_by_type:
            pattern_json_strings_by_type[type_str] = []
        for pattern in patterns_by_type[type_str]:
            pattern_json_strings_by_type[type_str].append(pattern.to_json())
    return from_json_strings(
        file_mapping,
        pattern_json_strings_by_type,
        skip_compilation_check=skip_compilation_check,
        compile_check_command=compile_check_command,
    )


def from_json_strings(
    file_mapping: Dict[int, Path],
    pattern_json_strings_by_type: Dict[str, List[str]],
    skip_compilation_check: bool = False,
    compile_check_command: Optional[str] = None,
    CC: str = "clang",
    CXX: str = "clang++",
    contained_patterns: Optional[Dict[str, List[str]]] = None,
) -> Dict[int, str]:
    """Insert the parallel patterns described by the given json strings into the original source code.
    Returns a dictionary which maps the ID of every modified file to the updated contents of the file.
    This method does not modify the original source code.
    Only fileIDs of files which would be modified occur as keys in the returned dictionary.
    For now, it is assumed that the given patterns are independent of each other, i.e. no nesting exists.
    """
    # convert pattern_json_strings to UnpackedSuggestion object
    unpacked_suggestions: List[UnpackedSuggestion] = []
    pattern_precedence = [
        "do_all",
        "reduction",
        "device_update",
        "gpu_do_all",
        "gpu_reduction",
        "pipeline",
        "task",
        "simple_gpu",
        "combined_gpu",
        "parallel_region",
    ]
    for type_str in pattern_precedence:
        if type_str not in pattern_json_strings_by_type:
            continue
        for json_str in pattern_json_strings_by_type[type_str]:
            unpacked_suggestions.append(UnpackedSuggestion(type_str, jsons.loads(json_str)))

    # create a dictionary mapping fileIds to ContentBuffer elements
    file_id_to_content_buffer: Dict[int, ContentBuffer] = dict()
    # iterate over UnpackedSuggestion objects
    for suggestion in unpacked_suggestions:

        # create new ContentBuffer if required
        if suggestion.file_id not in file_id_to_content_buffer:
            file_id_to_content_buffer[suggestion.file_id] = ContentBuffer(
                suggestion.file_id, file_mapping[suggestion.file_id]
            )
        # get pragma objects represented by the UnpackedSuggestion
        pragmas = suggestion.get_pragmas(contained_patterns=contained_patterns)
        # add pragmas to the ContentBuffer object which corresponds to the fileId specified in UnpackedSuggestions
        for pragma in pragmas:
            successful = file_id_to_content_buffer[suggestion.file_id].add_pragma(
                file_mapping,
                pragma,
                [],
                skip_compilation_check=skip_compilation_check,
                compile_check_command=compile_check_command,
                CC=CC,
                CXX=CXX,
            )
            # if the addition resulted in a non-compilable file, add the pragma as a comment
            if not successful:
                file_id_to_content_buffer[suggestion.file_id].add_pragma(
                    file_mapping,
                    pragma,
                    [],
                    add_as_comment=True,
                    compile_check_command=compile_check_command,
                    CC=CC,
                    CXX=CXX,
                )

    # create the resulting dictionary by assembling the contents of the ContentBuffer objects
    result_dict: Dict[int, str] = dict()
    for file_id in file_id_to_content_buffer:
        result_dict[file_id] = file_id_to_content_buffer[file_id].get_modified_source_code()
    return result_dict


def from_json_strings_with_mapping(
    file_mapping: Dict[int, Path],
    pattern_json_strings_with_mapping_by_type: Dict[str, List[Tuple[str, DeviceID, Optional[DeviceTypeEnum]]]],
    skip_compilation_check: bool = False,
    compile_check_command: Optional[str] = None,
    CC: str = "clang",
    CXX: str = "clang++",
    host_device_id: int = 0,
    contained_patterns: Optional[Dict[str, List[str]]] = None,
) -> Dict[int, str]:
    """Insert the parallel patterns described by the given json strings into the original source code.
    Returns a dictionary which maps the ID of every modified file to the updated contents of the file.
    This method does not modify the original source code.
    Only fileIDs of files which would be modified occur as keys in the returned dictionary.
    For now, it is assumed that the given patterns are independent of each other, i.e. no nesting exists.
    """
    # convert pattern_json_strings to UnpackedSuggestion object
    unpacked_suggestions: List[UnpackedSuggestion] = []
    pattern_precedence = [
        "device_update",
        "do_all",
        "reduction",
        "gpu_do_all",
        "gpu_reduction",
        "pipeline",
        "simple_gpu",
        "combined_gpu",
        "parallel_region",
    ]
    for type_str in pattern_precedence:
        if type_str not in pattern_json_strings_with_mapping_by_type:
            continue
        for json_str, device_id, device_type in pattern_json_strings_with_mapping_by_type[type_str]:
            unpacked_suggestions.append(
                UnpackedSuggestion(
                    type_str,
                    jsons.loads(json_str),
                    device_id=device_id,
                    device_type=device_type,
                    host_device_id=host_device_id,
                )
            )

    # create a dictionary mapping fileIds to ContentBuffer elements
    file_id_to_content_buffer: Dict[int, ContentBuffer] = dict()
    # iterate over UnpackedSuggestion objects
    for suggestion in unpacked_suggestions:
        # create new ContentBuffer if required
        if suggestion.file_id not in file_id_to_content_buffer:
            file_id_to_content_buffer[suggestion.file_id] = ContentBuffer(
                suggestion.file_id, file_mapping[suggestion.file_id]
            )
        # get pragma objects represented by the UnpackedSuggestion
        pragmas = suggestion.get_pragmas(contained_patterns=contained_patterns)
        # add pragmas to the ContentBuffer object which corresponds to the fileId specified in UnpackedSuggestions
        for pragma in pragmas:
            successful = file_id_to_content_buffer[suggestion.file_id].add_pragma(
                file_mapping,
                pragma,
                [],
                skip_compilation_check=skip_compilation_check,
                compile_check_command=compile_check_command,
                CC=CC,
                CXX=CXX,
            )
            # if the addition resulted in a non-compilable file, add the pragma as a comment
            if not successful:
                file_id_to_content_buffer[suggestion.file_id].add_pragma(
                    file_mapping,
                    pragma,
                    [],
                    add_as_comment=True,
                    compile_check_command=compile_check_command,
                    CC=CC,
                    CXX=CXX,
                )

    # create the resulting dictionary by assembling the contents of the ContentBuffer objects
    result_dict: Dict[int, str] = dict()
    for file_id in file_id_to_content_buffer:
        result_dict[file_id] = file_id_to_content_buffer[file_id].get_modified_source_code()
    return result_dict

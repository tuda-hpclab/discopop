# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import os.path
import subprocess
from typing import List, Tuple, Dict, Optional, Set

from discopop_library.LineMapping.load import load_line_mapping
from discopop_library.LineMapping.save import save_line_mapping


def apply_line_mapping_modifications_from_files(file_id: int, original_file: str, modified_file: str) -> None:
    """Calculates diff between original_file and modified_file and applied modifications from the diff to the line_mapping"""
    if not os.path.exists(original_file):
        raise FileNotFoundError(original_file)
    if not os.path.exists(modified_file):
        raise FileNotFoundError(original_file)

    command = [
        "diff",
        original_file,
        modified_file,
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if result.returncode == 1:
        # print("RESULT: ", result.returncode)
        # print("STDERR:")
        # print(result.stderr)
        # print("STDOUT: ")
        # print(result.stdout)
        diff = result.stdout
        # print("DIFF: ", diff)
    else:
        diff = ""

    apply_line_mapping_modifications_from_diff(file_id, diff)


def apply_line_mapping_modifications_from_diff(file_id: int, diff: str) -> None:
    """parse diff, apply line num modifications according to c,a,d values"""
    # get cleaned diff
    cleaned_diff: List[str] = []
    for line in diff.split("\n"):
        if (
            line.startswith("<")
            or line.startswith(">")
            or line.startswith("-")
            or line.startswith("\\")
            or len(line) == 0
        ):
            continue
        line = line.replace("\n", "")
        cleaned_diff.append(line)

    # get line_mapping
    line_mapping: Dict[str, Dict[str, int]] = load_line_mapping()

    deletions: Set[str] = set()
    shifts: Dict[str, int] = dict()

    # initialize
    for key in line_mapping[str(file_id)]:
        shifts[key] = 0

    # parse diff
    for diff_entry in cleaned_diff:
        if "a" in diff_entry:
            lhs = diff_entry[: diff_entry.index("a")]
            if "," in lhs:
                base_line = int(lhs.split(",")[0])
            else:
                base_line = int(lhs)
            rhs = diff_entry[diff_entry.index("a") + 1 :]
            if "," in rhs:
                added_lines_count = int(rhs.split(",")[1]) - int(rhs.split(",")[0]) + 1
            else:
                added_lines_count = 1
            for key in line_mapping[str(file_id)]:
                if line_mapping[str(file_id)][key] < 0:
                    # invalid due to deletion
                    continue
                if line_mapping[str(file_id)][key] > base_line:
                    shifts[key] += added_lines_count

        if "d" in diff_entry:
            lhs = diff_entry[: diff_entry.index("d")]
            if "," in lhs:
                base_line = int(lhs.split(",")[0])
                deleted_lines_count = int(lhs.split(",")[1]) - int(lhs.split(",")[0]) + 1
            else:
                base_line = int(lhs)
                deleted_lines_count = 1
            for key in line_mapping[str(file_id)]:
                if line_mapping[str(file_id)][key] < 0:
                    # invalid due to deletion
                    continue
                if line_mapping[str(file_id)][key] in range(base_line, base_line + deleted_lines_count):
                    deletions.add(key)
                elif line_mapping[str(file_id)][key] >= base_line + deleted_lines_count:
                    shifts[key] -= deleted_lines_count

        if "c" in diff_entry:
            lhs = diff_entry[: diff_entry.index("c")]
            if "," in lhs:
                base_line = int(lhs.split(",")[0])
                deleted_lines_count = int(lhs.split(",")[1]) - int(lhs.split(",")[0]) + 1
            else:
                base_line = int(lhs)
                deleted_lines_count = 1
            rhs = diff_entry[diff_entry.index("c") + 1 :]
            if "," in rhs:
                added_lines_count = int(rhs.split(",")[1]) - int(rhs.split(",")[0]) + 1
            else:
                added_lines_count = 1

            for key in line_mapping[str(file_id)]:
                if line_mapping[str(file_id)][key] < 0:
                    # invalid due to deletion
                    continue
                if line_mapping[str(file_id)][key] > base_line:
                    shifts[key] += added_lines_count

            for key in line_mapping[str(file_id)]:
                if line_mapping[str(file_id)][key] < 0:
                    # invalid due to deletion
                    continue
                if line_mapping[str(file_id)][key] in range(base_line, base_line + deleted_lines_count):
                    deletions.add(key)
                elif line_mapping[str(file_id)][key] >= base_line + deleted_lines_count:
                    shifts[key] -= deleted_lines_count

    # apply deletions
    for key in deletions:
        line_mapping[str(file_id)][key] = -1

    # apply shifts
    for key in shifts:
        if line_mapping[str(file_id)][key] < 0:
            # invalid due to deletion
            continue
        line_mapping[str(file_id)][key] = line_mapping[str(file_id)][key] + shifts[key]

    # save updated line mapping
    save_line_mapping(line_mapping)

    pass

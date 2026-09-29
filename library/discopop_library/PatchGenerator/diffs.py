# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import os.path
import subprocess
from pathlib import Path
from typing import Dict, Optional

from discopop_library.PatchGenerator.PatchGeneratorArguments import PatchGeneratorArguments

CRLF = "\r\n"
LF = "\n"
CR = "\r"


def detect_line_terminator(file_path: Path) -> Optional[str]:
    """Dominant line terminator of ``file_path`` (``"\\r\\n"``, ``"\\r"`` or ``"\\n"``).

    Returns ``None`` when the file cannot be read or contains no line break at all,
    in which case the caller must leave the modified code untouched.
    """
    try:
        with open(file_path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    crlf_count = raw.count(b"\r\n")
    lf_count = raw.count(b"\n") - crlf_count
    cr_count = raw.count(b"\r") - crlf_count
    if crlf_count == 0 and lf_count == 0 and cr_count == 0:
        return None
    if crlf_count >= lf_count and crlf_count >= cr_count:
        return CRLF
    if cr_count > lf_count:
        return CR
    return LF


def apply_line_terminator(code: str, terminator: str) -> str:
    """Rewrite every line break in ``code`` to ``terminator``.

    The code generator emits LF-only text regardless of the original file's line
    endings. Diffing that against a CRLF original makes ``diff`` report the whole
    file as rewritten, and ``patch`` then rejects the result with "different line
    endings" -- i.e. every suggestion for such a file is unapplicable. Restoring the
    original terminator before diffing keeps the diff minimal and applicable.
    """
    normalized = code.replace(CRLF, LF).replace(CR, LF)
    if terminator == LF:
        return normalized
    return normalized.replace(LF, terminator)


def get_diffs_from_modified_code(
    file_mapping: Dict[int, Path], file_id_to_modified_code: Dict[int, str], arguments: PatchGeneratorArguments
) -> Dict[int, str]:
    patches: Dict[int, str] = dict()
    for file_id in file_id_to_modified_code:
        # get path to original code
        original_file_path = file_mapping[file_id]
        # create temporary modified code
        modified_file_path = original_file_path.parent / (original_file_path.name + ".discopop_patch_generator.temp")
        if arguments.verbose:
            print("Original: ", original_file_path)
            print("Modified:  ", modified_file_path)

        # match the original file's line endings so the diff stays minimal and the
        # resulting patch is applicable (see apply_line_terminator)
        modified_code = file_id_to_modified_code[file_id]
        terminator = detect_line_terminator(original_file_path)
        if terminator is not None and terminator != LF:
            modified_code = apply_line_terminator(modified_code, terminator)
            if arguments.verbose:
                print("Restored line terminator: ", repr(terminator))

        try:
            # newline="" keeps the terminators above byte-for-byte
            with open(modified_file_path, "w", newline="") as f:
                f.write(modified_code)
        except PermissionError:
            continue

        # calculate diff
        diff_name = original_file_path.parent / (original_file_path.name + ".discopop_patch_generator.diff")
        command = [
            "diff",
            "-Naru",
            original_file_path.as_posix(),
            modified_file_path.as_posix(),
        ]
        # NOTE: the output is captured in binary mode on purpose. Universal-newline
        # translation would rewrite the CR of a CRLF file's context lines and thus
        # undo the terminator restoration above, making the patch unapplicable again.
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.getcwd(),
        )
        diff_output = result.stdout.decode("utf-8", errors="replace")
        if result.returncode != 0:
            if arguments.verbose:
                print("RESULT: ", result.returncode)
                print("STDERR:")
                print(result.stderr.decode("utf-8", errors="replace"))
                print("STDOUT: ")
                print(diff_output)

        # save diff
        patches[file_id] = diff_output

        # cleanup environment
        if os.path.exists(modified_file_path):
            os.remove(modified_file_path)
        if os.path.exists(diff_name):
            os.remove(diff_name)

    return patches

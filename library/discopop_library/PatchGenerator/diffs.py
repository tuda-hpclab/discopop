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
    file_mapping: Dict[int, Path],
    file_id_to_modified_code: Dict[int, str],
    arguments: PatchGeneratorArguments,
    scratch_dir: Optional[Path] = None,
) -> Dict[int, str]:
    """The diffs from the original files to the modified code, keyed by file id.

    The modified code is written to a temporary file next to the original, unless ``scratch_dir`` is given: it is then
    written there, so that nothing is written into the project. The headers of the diff are the same either way.
    """
    patches: Dict[int, str] = dict()
    for file_id in file_id_to_modified_code:
        # get path to original code
        original_file_path = file_mapping[file_id]
        # create temporary modified code
        conventional_path = original_file_path.parent / (original_file_path.name + ".discopop_patch_generator.temp")
        if scratch_dir is None:
            modified_file_path = conventional_path
        else:
            # one directory per file id: files of the same name in different directories must not collide
            (scratch_dir / str(file_id)).mkdir(parents=True, exist_ok=True)
            modified_file_path = scratch_dir / str(file_id) / conventional_path.name
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
        if modified_file_path != conventional_path:
            diff_output = _rename_new_file(diff_output, modified_file_path, conventional_path)
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


def _rename_new_file(diff_output: str, actual: Path, conventional: Path) -> str:
    """the diff with the path of the modified file in its "+++" header replaced by the conventional one"""
    lines = diff_output.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("+++ " + actual.as_posix()):
            lines[index] = "+++ " + conventional.as_posix() + line[len("+++ " + actual.as_posix()) :]
            break
        if line.startswith("@@"):
            break
    return "\n".join(lines)

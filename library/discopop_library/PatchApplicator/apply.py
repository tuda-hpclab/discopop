# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

from discopop_library.LineMapping.diff_modifications import apply_line_mapping_modifications_from_files
from discopop_library.PatchApplicator.PatchApplicationResult import PatchApplicationResult
from discopop_library.PatchApplicator.PatchApplicatorArguments import PatchApplicatorArguments


def apply_patches(
    apply: List[str],
    file_mapping: Dict[int, Path],
    arguments: PatchApplicatorArguments,
    applied_suggestions_file: str,
    patch_generator_dir: str,
) -> PatchApplicationResult:
    """Apply the requested suggestions and report which of them reached the code.

    A requested suggestion can miss the code in two ways: ``patch`` rejects its
    patch (e.g. the source no longer matches), or no patch was generated for the id
    at all. Both are recorded, so callers can tell an unmodified code base apart
    from a successful application -- see :class:`PatchApplicationResult`.
    """
    result = PatchApplicationResult(requested=list(apply))
    # get list of applicable suggestions
    applicable_suggestions = sorted(os.listdir(patch_generator_dir))

    # get already applied suggestions
    with open(applied_suggestions_file, "r") as f:
        applied_suggestions = json.loads(f.read())
        if arguments.verbose:
            print("Previously applied suggestions: ", applied_suggestions["applied"])

    for suggestion_id in apply:
        if suggestion_id in applied_suggestions["applied"]:
            if arguments.verbose:
                print("Skipping already applied suggestion: ", suggestion_id)
            result.already_applied.append(suggestion_id)
            continue
        if suggestion_id in applicable_suggestions:
            if arguments.verbose:
                print("Applying suggestion ", suggestion_id)
            successful = __apply_file_patches(file_mapping, suggestion_id, patch_generator_dir, arguments)
            if successful:
                applied_suggestions["applied"].append(suggestion_id)
                # write updated applied suggestions to file
                with open(applied_suggestions_file, "w") as f:
                    f.write(json.dumps(applied_suggestions))
                result.applied.append(suggestion_id)
            else:
                print("Applying suggestion", suggestion_id, "not successful.")
                result.failed.append(suggestion_id)
        else:
            # requested, but the patch generator produced nothing for this id. This
            # used to be reported as success, which silently measured unmodified code.
            print("Nothing to apply for suggestion", suggestion_id, "- no patch was generated.")
            result.unknown.append(suggestion_id)
    return result


def __apply_file_patches(
    file_mapping: Dict[int, Path], suggestion_id: str, patch_generator_dir: str, arguments: PatchApplicatorArguments
) -> bool:
    # get a list of patches for the given suggestion
    patch_files = sorted(os.listdir(os.path.join(patch_generator_dir, suggestion_id)))
    if arguments.verbose:
        print("\tFound patch files:", patch_files)
    encountered_error = False
    already_patched: List[str] = []
    for patch_file_name in patch_files:
        patch_file_id = int(patch_file_name.rstrip(".patch"))
        patch_target = file_mapping[patch_file_id]
        patch_file_path = os.path.join(patch_generator_dir, suggestion_id, patch_file_name)
        # save original version to calculate diff to calculate line mapping
        shutil.copyfile(patch_target.as_posix(), patch_target.as_posix() + ".line_mapping_tmp")
        # --batch: never ask. Without it patch turns interactive on a reversed or
        # already-applied patch ("Assume -R? [n]", "Apply anyway? [n]"), and with no
        # terminal attached -- under the autotuner, the GUI, the MCP server -- the prompt
        # is answered by EOF.
        # --forward: and never guess. --batch ALONE answers that prompt with "Assuming
        # -R" and silently *reverses* the patch, returning 0: applying an
        # already-applied suggestion would strip the parallelization back out and report
        # success, and the runtime measured afterwards would be of unmodified code.
        # --forward makes patch skip such a patch and fail loudly instead.
        command = [
            "patch",
            "--batch",
            "--forward",
            patch_target.as_posix(),
            patch_file_path,
        ]
        if arguments.verbose:
            print("\tapplying: ", " ".join(command))
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            universal_newlines=True,
            cwd=os.getcwd(),
        )
        if result.returncode != 0:
            if arguments.verbose:
                print("RESULT: ", result.returncode)
                print("STDERR:")
                print(result.stderr)
            print("STDOUT: ")
            print(result.stdout)
            encountered_error = True
            # delete temporary file
            os.remove(patch_target.as_posix() + ".line_mapping_tmp")
            break
        else:
            already_patched.append(patch_file_name)
            # apply modifications to line mapping
            apply_line_mapping_modifications_from_files(
                patch_file_id, patch_target.as_posix() + ".line_mapping_tmp", patch_target.as_posix()
            )
            # delete temporary file
            os.remove(patch_target.as_posix() + ".line_mapping_tmp")

    # cleanup in case of an error
    if encountered_error:
        for patch_file_name in already_patched:
            patch_file_id = int(patch_file_name.rstrip(".patch"))
            patch_target = file_mapping[patch_file_id]
            patch_file_path = os.path.join(patch_generator_dir, suggestion_id, patch_file_name)
            # save original version to calculate diff to calculate line mapping
            shutil.copyfile(patch_target.as_posix(), patch_target.as_posix() + ".line_mapping_tmp")
            command = [
                "patch",
                "--batch",
                "--forward",
                "-R",
                patch_target.as_posix(),
                patch_file_path,
            ]
            if arguments.verbose:
                print("\tcleanup: applying: ", " ".join(command))
            result = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                universal_newlines=True,
                cwd=os.getcwd(),
            )
            if result.returncode != 0:
                if arguments.verbose:
                    print("RESULT: ", result.returncode)
                    print("STDERR:")
                    print(result.stderr)
                print("STDOUT: ")
                print(result.stdout)

            # apply modifications to line mapping
            apply_line_mapping_modifications_from_files(
                patch_file_id, patch_target.as_posix() + ".line_mapping_tmp", patch_target.as_posix()
            )
            # delete temporary file
            os.remove(patch_target.as_posix() + ".line_mapping_tmp")

    return not encountered_error

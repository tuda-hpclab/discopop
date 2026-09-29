#!/bin/bash

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License. See the LICENSE file in the package base
# directory for details.


# this script is given a list of filenames as arguments
# it checks if the files contain the license tag
# if not, it prints an error message and exits with exit code 1
# if all files contain the license tag, it exits with exit code 0
# some files are ignored, see below

ERROR=""
for file in "$@"; do
    # no license tag is required in the following locations:

    # binary files
    [[ "$file" = *".png" ]] && continue
    [[ "$file" = *".svg" ]] && continue
    [[ "$file" = *".ico" ]] && continue

    # python:
    [[ "$file" = *"/_version.py" ]] && continue
    [[ "$file" = *"/__init__.py" ]] && continue # we might want to improve this: only ignore __init__.py files if they are empty
    [[ "$file" = *"/py.typed" ]] && continue
    # not needed, as they are ignored using .gitignore
    #[[ "$file" = *"/__pycache__/"* ]] && continue
    #[[ "$file" = *"/.mypy_cache/"* ]] && continue
    #[[ "$file" = *"/venv/"* ]] && continue
    #[[ "$file" = *"/env/"* ]] && continue
    #[[ "$file" = *".egg-info/"* ]] && continue

    # other
    [[ "$file" = *".git" ]] && continue
    [[ "$file" = *".git/"* ]] && continue
    [[ "$file" = *"test/"* ]] && continue
    [[ "$file" = *"docs/"* ]] && continue
    [[ "$file" = *"build/"* ]] && continue
    [[ "$file" = *"LICENSE" ]] && continue
    [[ "$file" = *"VERSION" ]] && continue
    [[ "$file" = *".clang-format" ]] && continue
    [[ "$file" = *"requirements.txt" ]] && continue
    [[ "$file" = *"CLAUDE.md" ]] && continue

    # third-party software
    [[ "$file" = *"third_party/"* ]] && continue

    # DEBIAN files for .deb creation
    [[ "$file" = *"DEBIAN/"* ]] && continue


    # check for the license tag in the first 20 lines of the file
    FILE_ERROR=""
    head -n 20 ${file} | grep -q "DiscoPoP software" || FILE_ERROR="yes"
    head -n 20 ${file} | grep -q "Technische Universitaet Darmstadt, Germany" || FILE_ERROR="yes"
    head -n 20 ${file} | grep -q "3-Clause BSD License" || FILE_ERROR="yes"
    [ -z "$FILE_ERROR" ] || ERROR="yes"
    [ -z "$FILE_ERROR" ] || echo "Missing License tag at: ${file}"
done

# Report error (1), if license tags are missing
[ -z "$ERROR" ] || exit 1

# Report success (0), if license tags are present
exit 0

#!/bin/bash
# Regenerates the profiler output of the state assignment fixtures (see
# explorer/discopop_explorer/classes/TaskGraph/test_TaskGraph_state_assignment.py), e.g. after a
# change of the profiler's output format.
#
# usage: explorer/test/state_assignment/regenerate.sh [program ...]   (default: all programs)
# requires the profiler in the venv of the repository root (pip install ./profiler)
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
CXX_WRAPPER="$ROOT/venv/bin/discopop_cxx"
FILES="Data.xml dynamic_dependencies.txt instructionID_to_lineID_mapping.txt reduction.txt stateID_to_callpath_mapping.txt static_dependencies.txt"

if [ $# -eq 0 ]; then
    set -- $(cd "$HERE" && ls -d */ | tr -d /)
fi

for program in "$@"; do
    echo "== $program"
    work="$(mktemp -d)"
    cp "$HERE/$program/code.cpp" "$work/"
    (cd "$work" && DP_PROJECT_ROOT_DIR="$work" "$CXX_WRAPPER" -O0 -g code.cpp -o code > build.log 2>&1 && ./code > run.log 2>&1)
    # a binary linked against an outdated runtime library freezes the callpath state, so only 2-3
    # distinct states occur (every fixture program has more)
    states=$(grep -oE '@[0-9]+' "$work/.discopop/profiler/dynamic_dependencies.txt" | sort -u | wc -l)
    if [ "$states" -le 3 ]; then
        echo "error: only $states callpath states in $program, outdated runtime library?" >&2
        exit 1
    fi
    for file in $FILES; do
        cp "$work/.discopop/profiler/$file" "$HERE/$program/$file"
    done
    cp "$work/.discopop/FileMapping.txt" "$HERE/$program/FileMapping.txt"
    # absolute paths of the temporary directory -> paths relative to the fixture
    sed -i "s#$work/##g" "$HERE/$program/FileMapping.txt"
    rm -rf "$work"
done

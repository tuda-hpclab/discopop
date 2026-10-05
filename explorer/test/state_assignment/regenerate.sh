#!/bin/bash
# Regenerates the profiler output of the state assignment fixtures (see
# explorer/discopop_explorer/classes/TaskGraph/test_TaskGraph_state_assignment.py), e.g. after a
# change of the profiler's output format.
#
# usage: explorer/test/state_assignment/regenerate.sh [program ...]   (default: all programs)
# requires the profiler in the venv of the repository root (pip install ./profiler); DISCOPOP_CXX
# overrides the compiler wrapper, e.g. to use the profiler installed in another checkout
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
CXX_WRAPPER="${DISCOPOP_CXX:-$ROOT/venv/bin/discopop_cxx}"
FILES="Data.xml dynamic_dependencies.txt instructionID_to_lineID_mapping.txt loopstate_positions.txt reduction.txt stateID_to_callpath_mapping.txt static_dependencies.txt"

if [ $# -eq 0 ]; then
    set -- $(cd "$HERE" && ls -d */ | tr -d /)
fi

for program in "$@"; do
    echo "== $program"
    work="$(mktemp -d)"
    cp "$HERE/$program/code.cpp" "$work/"
    (cd "$work" && DP_PROJECT_ROOT_DIR="$work" "$CXX_WRAPPER" -O0 -g code.cpp -o code > build.log 2>&1 && ./code > run.log 2>&1)
    # a binary linked against a runtime library older than the split of the return transitions into
    # callpath_state_return_targets.txt freezes the callpath state (only 2-3 distinct states)
    if ! grep -qa callpath_state_return_targets "$work/code"; then
        echo "error: $program is linked against an outdated runtime library" >&2
        exit 1
    fi
    if [ ! -f "$work/.discopop/profiler/loopstate_positions.txt" ]; then
        echo "error: no loopstate_positions.txt for $program, outdated profiler?" >&2
        exit 1
    fi
    states=$(grep -oE '@[0-9]+' "$work/.discopop/profiler/dynamic_dependencies.txt" | sort -u | wc -l)
    echo "   $states distinct callpath states"
    for file in $FILES; do
        cp "$work/.discopop/profiler/$file" "$HERE/$program/$file"
    done
    cp "$work/.discopop/FileMapping.txt" "$HERE/$program/FileMapping.txt"
    # absolute paths of the temporary directory -> paths relative to the fixture
    sed -i "s#$work/##g" "$HERE/$program/FileMapping.txt"
    # the fixtures must not depend on the machine they were generated on
    if grep -lF "$work" "$HERE/$program"/*; then
        echo "error: the files above contain the path of the temporary directory" >&2
        exit 1
    fi
    rm -rf "$work"
done

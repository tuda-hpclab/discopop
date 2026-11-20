#!/bin/bash
# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

# This script is based on a script from the discopop project
# https://github.com/tuda-hpclab/discopop

SCRIPT_PATH="$(readlink -fm "$0")"
LIBS_DIR="$(dirname ${SCRIPT_PATH})"

LLVM_CLANG=""
LLVM_CLANGPP=""
for _v in 22 21 20 19; do
    if command -v clang-$_v &> /dev/null; then
        LLVM_CLANG=$(which clang-$_v)
        LLVM_CLANGPP=$(which clang++-$_v)
        break
    fi
done
if [ -z "$LLVM_CLANG" ]; then
    echo "ERROR: No supported clang version (19-22) found in PATH"
    exit 1
fi

# pthread is bundled into libSystem on macOS; only link explicitly on Linux
PTHREAD_XLINKER_FLAGS=()
[[ "$(uname)" != "Darwin" ]] && PTHREAD_XLINKER_FLAGS=(-Xlinker -lpthread)
# DOT_DISCOPOP not set: the nearest .discopop of the project (see dp_environment.sh), seen by the pass as well
source "${LIBS_DIR}/dp_environment.sh"
dp_resolve_dot_discopop "$@" || true
# OpenMP flags: kept with a warning, removed with DP_STRIP_OPENMP=1 (see dp_openmp.sh); DP_ARGS replaces "$@"
source "${LIBS_DIR}/dp_openmp.sh"
dp_handle_openmp "$@"
${LLVM_CLANG} "${DP_ARGS[@]}" -g -fno-discard-value-names -O0 -Xclang -load -Xclang ${LIBS_DIR}/LLVMHotspotDetection.so -Xclang -fpass-plugin=${LIBS_DIR}/LLVMHotspotDetection.so -Xlinker -L${LIBS_DIR} -Xlinker -lHotspotDetection_RT "${PTHREAD_XLINKER_FLAGS[@]}" -Xlinker -v

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

LLVM_CLANGPP=""
for _v in 22 21 20 19; do
    if command -v clang++-$_v &> /dev/null; then
        LLVM_CLANGPP=$(which clang++-$_v)
        break
    fi
done
if [ -z "$LLVM_CLANGPP" ]; then
    echo "ERROR: No supported clang version (19-22) found in PATH"
    exit 1
fi

# pthread is bundled into libSystem on macOS; only link explicitly on Linux
PTHREAD_FLAG=""; [[ "$(uname)" != "Darwin" ]] && PTHREAD_FLAG="-lpthread"
${LLVM_CLANGPP} "$@" -L${LIBS_DIR} -lHotspotDetection_RT ${PTHREAD_FLAG} -fPIC -v

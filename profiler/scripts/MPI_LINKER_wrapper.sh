#!/bin/bash

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License. See the LICENSE file in the package base
# directory for details.

SCRIPT_PATH="$(readlink -fm "$0")"

# ensure that copy of script in build folder is invoked instead of the "original"
if [[ "${SCRIPT_PATH}" == *"discopop/scripts/"* ]]; then
  echo "ERROR: Invoked script directly from source folder:"
  echo "    ${SCRIPT_PATH}"
  echo "Use the copy located in the DiscoPoP build folder instead."
  echo ""
  exit 1
fi

# ensure that mpic++ can be found
if ! command -v mpic++ &> /dev/null
then
    echo "command: mpic++ could not be found!"
    exit 1
fi

# SETTINGS
DP_BUILD="$(dirname "$(dirname ${SCRIPT_PATH})")"
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
MPI_INCLUDES="$(mpic++ -showme:link)"

# original arguments: "$@"
#echo "WRAPPED MPI LINKING...."
#echo "ARGS: $@"

# script will be located alongside LLVMDiscoPoP.so and libDiscoPoP_RT.a in the python venv/lib/../discopop-profiler.libs
PARENT_PATH=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
# pthread is bundled into libSystem on macOS; only link explicitly on Linux
PTHREAD_FLAG=""; [[ "$(uname)" != "Darwin" ]] && PTHREAD_FLAG="-lpthread"
# libDiscoPoP_RT.a is a static archive, so the linker only pulls in the members that resolve
# an undefined symbol. Nothing in the instrumented code references __dp_init any more -- the
# runtime starts from the .init_array entry in dp_init.cpp -- so that member has to be requested
# explicitly, or the runtime is never brought up.
${LLVM_CLANGPP} ${MPI_INCLUDES} "$@" -L${PARENT_PATH} -Wl,-u,__dp_init -lDiscoPoP_RT ${PTHREAD_FLAG} -fPIC -v

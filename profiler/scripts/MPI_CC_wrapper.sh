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

# ensure that mpicc can be found
if ! command -v mpicc &> /dev/null
then
    echo "command: mpicc could not be found!"
    exit 1
fi

# SETTINGS
DP_BUILD="$(dirname "$(dirname ${SCRIPT_PATH})")"
DP_SCRIPTS=${DP_BUILD}/scripts
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
    if command -v clang &> /dev/null && command -v clang++ &> /dev/null; then
        LLVM_CLANG=$(which clang)
        LLVM_CLANGPP=$(which clang++)
    else
        echo "ERROR: No supported clang version (19-22) found in PATH"
        exit 1
    fi
fi
MPI_INCLUDES="$(mpicc -showme:compile)"

# original arguments: "$@"
#echo "WRAPPED MPI CC COMPILE..."
#echo "ARGS: ${@}"

# script will be located alongside LLVMDiscoPoP.so and libDiscoPoP_RT.a in the python venv/lib/../discopop-profiler.libs
PARENT_PATH=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
${LLVM_CLANG} "${@}" -g -c -O0 -fno-discard-value-names -Xclang -load -Xclang ${PARENT_PATH}/LLVMDiscoPoP.so -Xclang -fpass-plugin=${PARENT_PATH}/LLVMDiscoPoP.so -fPIC ${MPI_INCLUDES} -Xlinker -lstdc++

# WARNING: OUTPUT IS A .ll FILE, ENDING IS .o

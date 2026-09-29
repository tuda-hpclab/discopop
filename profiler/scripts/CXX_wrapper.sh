#!/bin/bash

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License. See the LICENSE file in the package base
# directory for details.

SCRIPT_PATH="$(readlink -fm "$0" 2>/dev/null || readlink -f "$0" 2>/dev/null || echo "$0")"

# ensure that copy of script in build folder is invoked instead of the "original"
if [[ "${SCRIPT_PATH}" == *"discopop/scripts/"* ]]; then
  echo "ERROR: The profiler does not support editable installs (-e)."
  echo ""
  echo "You invoked: pip install -e ./profiler"
  echo "Use instead:  pip install ./profiler"
  echo ""
  echo "Reason: CXX_wrapper.sh and compiled artifacts (LLVMDiscoPoP.so) must be"
  echo "        located in the venv's site-packages for relative paths to resolve."
  echo ""
  exit 1
fi

# SETTINGS
DP_BUILD="$(dirname "$(dirname ${SCRIPT_PATH})")"
LLVM_CLANG=""
LLVM_CLANGPP=""
for _v in 22 21 20 19; do
    if command -v clang-$_v &> /dev/null; then
        LLVM_CLANG=$(which clang-$_v)
        if command -v clang++-$_v &> /dev/null; then
            LLVM_CLANGPP=$(which clang++-$_v)
        elif [ -x "$(dirname "$LLVM_CLANG")/clang++" ]; then
            # Homebrew on macOS ships clang++ not clang++-21
            LLVM_CLANGPP="$(dirname "$LLVM_CLANG")/clang++"
        fi
        break
    fi
done
if [ -z "$LLVM_CLANG" ]; then
    if command -v clang &> /dev/null && command -v clang++ &> /dev/null; then
        LLVM_CLANG=$(which clang)
        LLVM_CLANGPP=$(which clang++)
    fi
fi
# macOS: Homebrew LLVM is keg-only and not on PATH — probe brew prefixes
if [ -z "$LLVM_CLANG" ] && command -v brew &> /dev/null; then
    for _v in 22 21 20 19; do
        _brew_prefix=$(brew --prefix "llvm@$_v" 2>/dev/null)
        if [ -n "$_brew_prefix" ] && [ -x "$_brew_prefix/bin/clang" ]; then
            LLVM_CLANG="$_brew_prefix/bin/clang"
            LLVM_CLANGPP="$_brew_prefix/bin/clang++"
            break
        fi
    done
fi
if [ -z "$LLVM_CLANG" ] || [ -z "$LLVM_CLANGPP" ]; then
    echo "ERROR: No supported clang version (19-22) found in PATH"
    exit 1
fi

# original arguments: "$@"
#echo "WRAPPED CXX COMPILE..."
#echo "ARGS: ${@}"



# script will be located alongside LLVMDiscoPoP.{so,dylib} and libDiscoPoP_RT.a in the python venv/lib/../discopop-profiler.libs
PARENT_PATH=$( cd "$(dirname "${BASH_SOURCE[0]}")" ; pwd -P )
# macOS uses .dylib for LLVM MODULE plugins; Linux uses .so
if [ -f "${PARENT_PATH}/LLVMDiscoPoP.dylib" ]; then
    DISCOPOP_PLUGIN="${PARENT_PATH}/LLVMDiscoPoP.dylib"
else
    DISCOPOP_PLUGIN="${PARENT_PATH}/LLVMDiscoPoP.so"
fi
# pthread is bundled into libSystem on macOS; only link explicitly on Linux
PTHREAD_XLINKER_FLAGS=()
[[ "$(uname)" != "Darwin" ]] && PTHREAD_XLINKER_FLAGS=(-Xlinker -lpthread)
${LLVM_CLANGPP} "$@" -g -O0 -fno-discard-value-names -Xclang -load -Xclang ${DISCOPOP_PLUGIN} -Xclang -fpass-plugin=${DISCOPOP_PLUGIN} -fPIC -Xlinker -L${PARENT_PATH} -Xlinker -lDiscoPoP_RT "${PTHREAD_XLINKER_FLAGS[@]}" -Xlinker -v

# dump ast for later use during pattern detection
if [ -n "$DOT_DISCOPOP" ]; then
  TMP_DOT_DISCOPOP="$DOT_DISCOPOP"
else
  TMP_DOT_DISCOPOP="$PWD/.discopop"
fi
# Unfiltered, clang's JSON AST dump includes every declaration transitively
# reachable from included headers (libc, libstdc++, MPI, ...), which for real
# projects bloats ast_dump.json to multiple GB even though pattern detection
# only ever queries project source locations. Filter it down before writing.
PROJECT_ROOT="$(dirname "${TMP_DOT_DISCOPOP}")"
${LLVM_CLANGPP} "$@" -fsyntax-only -Xclang -ast-dump=json | python3 "${PARENT_PATH}/filter_ast_dump.py" "${PROJECT_ROOT}" >> "$TMP_DOT_DISCOPOP/profiler/ast_dump.json"
# WARNING: OUTPUT IS A .ll FILE, ENDING IS .o

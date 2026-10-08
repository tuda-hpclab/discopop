#!/usr/bin/env bash

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

# Builds the profiler's C++ unit tests (DiscoPoP_UT) with sanitizers and runs them.
# Used by the CI job "Runtime unit tests with sanitizers" (runtime_unit_tests_sanitized); run it from anywhere in the repository.
#
# usage: scripts/dev/run_profiler_sanitizers.sh <sanitizers> [build dir]
#   <sanitizers>  value for -fsanitize= (DP_SANITIZERS), e.g. "address,undefined" or "thread"
#   [build dir]   default: build_asan for address,undefined, build_tsan for thread, build_san otherwise
#
# Findings fail the run. Accepted leaks / races go into test/unit_tests/sanitizers/{lsan,tsan}.supp,
# each with a comment explaining why.

set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <sanitizers, e.g. address,undefined or thread> [build dir]" >&2
  exit 2
fi

SANITIZERS="$1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
case "${SANITIZERS}" in
  address,undefined) DEFAULT_BUILD_DIR=build_asan ;;
  thread) DEFAULT_BUILD_DIR=build_tsan ;;
  *) DEFAULT_BUILD_DIR=build_san ;;
esac
BUILD_DIR="${2:-${REPO_ROOT}/${DEFAULT_BUILD_DIR}}"
SUPP_DIR="${REPO_ROOT}/test/unit_tests/sanitizers"

cmake -S "${REPO_ROOT}" -B "${BUILD_DIR}" -DCMAKE_BUILD_TYPE=Release -DDP_BUILD_UNITTESTS=1 -DDP_SANITIZERS="${SANITIZERS}"
cmake --build "${BUILD_DIR}" --target DiscoPoP_UT -j "$(nproc)"

export ASAN_OPTIONS="halt_on_error=1:detect_leaks=1:detect_stack_use_after_return=1:check_initialization_order=1:strict_init_order=1"
export LSAN_OPTIONS="suppressions=${SUPP_DIR}/lsan.supp:print_suppressions=0"
export UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"
export TSAN_OPTIONS="halt_on_error=1:second_deadlock_stack=1:suppressions=${SUPP_DIR}/tsan.supp"

RUNNER=()
if [[ "${SANITIZERS}" == *thread* ]]; then
  # TSan aborts with "unexpected memory mapping" on kernels with high mmap ASLR entropy
  # (vm.mmap_rnd_bits > 28, e.g. Ubuntu 24.04 kernels); run without ASLR where the personality call is permitted
  # (in Docker, it needs --security-opt seccomp=unconfined)
  if setarch "$(uname -m)" -R true 2>/dev/null; then
    RUNNER=(setarch "$(uname -m)" -R)
  else
    echo "WARNING: cannot disable ASLR, TSan may abort with 'unexpected memory mapping'" >&2
  fi
fi

"${RUNNER[@]}" "${BUILD_DIR}/test/unit_tests/DiscoPoP_UT"

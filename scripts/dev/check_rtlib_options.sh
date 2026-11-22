#!/usr/bin/env bash

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

# Builds the profiler's runtime library (DiscoPoP_RT) once per set of compile time options.
# Used by the CI job "Profiler unit tests" (profiler_unit_tests); run it from anywhere in the repository.
#
# Most of the runtime is configured by -DDP_... options, which switch code in and out with #if. The default
# build compiles only one variant, and code that is switched off is never checked: an option that stops
# compiling goes unnoticed until someone turns it on. This builds the combinations below and fails if one does not.
#
# usage: scripts/dev/check_rtlib_options.sh [build base dir] [name of one configuration]
#   [build base dir]  default: build_options (gitignored); every configuration gets its own subdirectory,
#                     as a CMake cache keeps the options of the earlier configure
#   [name]            build only this configuration, e.g. no_workers
#
# A new option belongs into the list below.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_DIR="${1:-${REPO_ROOT}/build_options}"
ONLY="${2:-}"

# name|cmake options
CONFIGURATIONS=(
  "default|"
  "no_workers|-DDP_NUM_WORKERS=0"
  "pthread_compatibility|-DDP_PTHREAD_COMPATIBILITY_MODE=1"
  "verbose_timer|-DDP_RTLIB_VERBOSE=1 -DDP_INTERNAL_TIMER=1"
  "debug|-DDP_DEBUG=1"
  "all|-DDP_PTHREAD_COMPATIBILITY_MODE=1 -DDP_RTLIB_VERBOSE=1 -DDP_INTERNAL_TIMER=1 -DDP_DEBUG=1"
)

mkdir -p "${BASE_DIR}"
FAILED=()
for entry in "${CONFIGURATIONS[@]}"; do
  name="${entry%%|*}"
  options="${entry#*|}"
  if [[ -n "${ONLY}" && "${ONLY}" != "${name}" ]]; then
    continue
  fi
  echo "=== ${name}: ${options:-no options}"
  build_dir="${BASE_DIR}/${name}"
  # the options are split on purpose
  # shellcheck disable=SC2086
  if ! cmake -S "${REPO_ROOT}" -B "${build_dir}" -DCMAKE_BUILD_TYPE=Release ${options} >"${build_dir}.log" 2>&1 \
    || ! cmake --build "${build_dir}" --target DiscoPoP_RT -j "$(nproc)" >>"${build_dir}.log" 2>&1; then
    echo "FAILED: ${name}, errors:"
    grep -E "error|Error" "${build_dir}.log" | head -n 20
    FAILED+=("${name}")
  fi
done

if [[ ${#FAILED[@]} -gt 0 ]]; then
  echo "These configurations do not build: ${FAILED[*]} (logs: ${BASE_DIR}/<name>.log)" >&2
  exit 1
fi
echo "All configurations build."

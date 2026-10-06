#!/usr/bin/env bash

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

## Profiler leak check (CI job "Profiler leak check (ASan/LSan)", see .github/workflows/ci.yml).
##
## Builds the profiler with its runtime library under AddressSanitizer/LeakSanitizer (DP_SANITIZERS=address)
## and checks
##   1. the runtime library's GoogleTest unit tests (test/unit_tests) for memory errors and leaks,
##   2. instrumented programs: test/leak_check/lsan_finalize_hook.cpp reports LSan's leaks right before and
##      right after __dp_finalize, plus the live heap. test/leak_check/evaluate_leaks.py fails on
##      - leaks of the runtime library that are not known, bounded leaks (test/leak_check/known_leaks.txt),
##      - leaks that grow from a short to a long run of the growth workloads in test/leak_check/programs
##        (workload: loops and heap memory, exceptions: throwing and catching, threads: a target with its own
##        threads, profiled with a runtime built with DP_PTHREAD_COMPATIBILITY_MODE=1),
##      - live heap that grows by more than HEAP_GROWTH_LIMIT_MB from the short to the long run (reachable
##        memory that grows with the run time, which LSan cannot see),
##      - LSan reports it cannot understand (missing canary, parsed leaks not matching LSan's summary).
##   The example program and the profiler test programs (test/profiler) run once each, against the known leaks.
##
## usage: scripts/dev/check_profiler_leaks.sh [--skip-build] [--skip-unit-tests] [--skip-programs]
##
## environment:
##   DP_LEAK_CHECK_BUILD_DIR      build and work directory (default: <repo>/build/leak_check)
##   DP_LEAK_CHECK_JOBS           parallel build jobs (default: 4)
##   DP_LEAK_CHECK_MEMORY_MAX_MB  memory limit of each test run in MB (default: 8192): ASan's hard_rss_limit_mb,
##                                and additionally `systemd-run --user --scope` where available
##
## Requires clang 19-22 with its sanitizer runtime (Debian/Ubuntu: libclang-rt-<version>-dev), the matching
## LLVM development files, llvm-symbolizer, cmake and python3. Leaves the source tree untouched.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
BUILD_DIR="${DP_LEAK_CHECK_BUILD_DIR:-${REPO_ROOT}/build/leak_check}"
JOBS="${DP_LEAK_CHECK_JOBS:-4}"
MEMORY_MAX_MB="${DP_LEAK_CHECK_MEMORY_MAX_MB:-8192}"
LEAK_CHECK_DIR="${REPO_ROOT}/test/leak_check"

# growth workloads: name, runtime variant (default | pthread), steps of the short and the long run
GROWTH_PROGRAMS=(
  "workload default 50 400"
  "exceptions default 200 3200"
  "threads pthread 20 160"
)
# Allowed growth of the live heap from the short to the long run. Measured on the current code (settled live
# heap, see lsan_finalize_hook.cpp): the runs of one program differ by at most one or two access chunks
# (4 MB each) at any step count, independent of the load. The limit can be lowered once the queues are
# bounded per worker (branch profiler_queue_limits).
HEAP_GROWTH_LIMIT_MB=32

# Every unit test suite is checked for leaks, with the suppressions the sanitizers CI job uses for the unit
# tests as well (test/unit_tests/sanitizers/lsan.supp). In CI, the leak check skips the unit tests for that reason.
UNIT_TEST_SUPPRESSIONS="${REPO_ROOT}/test/unit_tests/sanitizers/lsan.supp"

SKIP_BUILD=false
SKIP_UNIT_TESTS=false
SKIP_PROGRAMS=false
for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=true ;;
    --skip-unit-tests) SKIP_UNIT_TESTS=true ;;
    --skip-programs) SKIP_PROGRAMS=true ;;
    -h|--help) sed -n 's/^## \{0,1\}//p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

FAILURES=()
section() { echo; echo "==== $* ===="; }
fail() { echo "LEAK CHECK FAILURE: $*" >&2; FAILURES+=("$*"); }

# ---------------------------------------------------------------------------------------------------------
# toolchain: the clang the profiler's wrapper scripts use (profiler/scripts/CXX_wrapper.sh selects the first
# clang-<N>, N = 22..19, and uses clang++-<N> or the clang++ next to it), with the LLVM of the same version
# ---------------------------------------------------------------------------------------------------------
CLANG=""; CLANGXX=""; LLVM_VERSION=""
for v in 22 21 20 19; do
  if command -v "clang-$v" > /dev/null 2>&1; then
    CLANG="$(command -v "clang-$v")"; LLVM_VERSION="$v"
    if command -v "clang++-$v" > /dev/null 2>&1; then
      CLANGXX="$(command -v "clang++-$v")"
    elif [ -x "$(dirname "$CLANG")/clang++" ]; then
      CLANGXX="$(dirname "$CLANG")/clang++"
    fi
    break
  fi
done
if [ -z "$CLANG" ] || [ -z "$CLANGXX" ]; then
  echo "ERROR: no clang-<19..22> with a clang++ found" >&2
  exit 1
fi
# all parts must use the same sanitizer runtime
if ! "$CLANGXX" --version | grep -q "clang version ${LLVM_VERSION}\."; then
  echo "ERROR: ${CLANGXX} is not clang ${LLVM_VERSION} (the profiler's wrapper scripts use ${CLANG})" >&2
  exit 1
fi
CMAKE_LLVM_ARGS=()
if command -v "llvm-config-${LLVM_VERSION}" > /dev/null 2>&1; then
  CMAKE_LLVM_ARGS=(-DLLVM_DIST_PATH="$("llvm-config-${LLVM_VERSION}" --prefix)")
elif [ -d "/usr/lib/llvm-${LLVM_VERSION}/lib/cmake/llvm" ]; then
  CMAKE_LLVM_ARGS=(-DLLVM_DIST_PATH="/usr/lib/llvm-${LLVM_VERSION}")
fi
for symbolizer in "llvm-symbolizer-${LLVM_VERSION}" "/usr/lib/llvm-${LLVM_VERSION}/bin/llvm-symbolizer" llvm-symbolizer; do
  if command -v "$symbolizer" > /dev/null 2>&1; then
    export ASAN_SYMBOLIZER_PATH="$(command -v "$symbolizer")"
    break
  fi
done
echo "compiler: ${CLANGXX}, symbolizer: ${ASAN_SYMBOLIZER_PATH:-<none found>}, build directory: ${BUILD_DIR}"

# memory cap of every test run (a runaway profile must not take the machine down): ASan's own RSS limit works
# everywhere, a systemd scope additionally where available
CAP=()
if command -v systemd-run > /dev/null 2>&1 && systemd-run --user --scope -q true > /dev/null 2>&1; then
  CAP=(systemd-run --user --scope -q -p "MemoryMax=$((MEMORY_MAX_MB + 512))M" -p MemorySwapMax=0)
fi
ASAN_BASE="hard_rss_limit_mb=${MEMORY_MAX_MB}"
# programs: the hook checks before and after __dp_finalize; without quarantine, freed memory is reused at
# once, so the peak RSS the hook reports is meaningful
ASAN_PROGRAMS="${ASAN_BASE}:detect_leaks=1:leak_check_at_exit=0:quarantine_size_mb=0:thread_local_quarantine_size_kb=0"

# keep the profiler's output next to each program
unset DOT_DISCOPOP DOT_DISCOPOP_PROFILER

# ---------------------------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------------------------
CMAKE_BUILD="${BUILD_DIR}/cmake"
CMAKE_BUILD_PTHREAD="${BUILD_DIR}/cmake_pthread"
INSTALL_DIR="${BUILD_DIR}/install"
LIBS_DIR="${INSTALL_DIR}/discopop-profiler.libs"
LIBS_DIR_PTHREAD="${BUILD_DIR}/install_pthread/discopop-profiler.libs"

configure() { # <source dir> <build dir> <log> [cmake args...]
  local source="$1" build="$2" log="$3"; shift 3
  if ! cmake -S "$source" -B "$build" -DCMAKE_BUILD_TYPE=Release -DDP_SANITIZERS=address \
      -DCMAKE_C_COMPILER="$CLANG" -DCMAKE_CXX_COMPILER="$CLANGXX" "${CMAKE_LLVM_ARGS[@]}" "$@" > "$log" 2>&1; then
    tail -n 40 "$log"; echo "ERROR: configuring failed (${log})" >&2; exit 1
  fi
  local found
  found="$(sed -n 's/.*Using LLVM version \([0-9]*\)\..*/\1/p' "$log" | head -n 1)"
  if [ "$found" != "$LLVM_VERSION" ]; then
    echo "ERROR: CMake found LLVM ${found:-<none>}, but the compiler is clang ${LLVM_VERSION} (${log})" >&2; exit 1
  fi
}

if ! $SKIP_BUILD; then
  section "build profiler and unit tests with DP_SANITIZERS=address"
  start=$SECONDS
  mkdir -p "$BUILD_DIR"
  configure "$LEAK_CHECK_DIR" "$CMAKE_BUILD" "${BUILD_DIR}/configure.log"
  if ! cmake --build "$CMAKE_BUILD" -j "$JOBS" > "${BUILD_DIR}/build.log" 2>&1; then
    grep -E "error|Error" "${BUILD_DIR}/build.log" | head -n 40; echo "ERROR: build failed (${BUILD_DIR}/build.log)" >&2; exit 1
  fi
  rm -rf "$INSTALL_DIR"
  if ! cmake --install "$CMAKE_BUILD" --prefix "$INSTALL_DIR" > "${BUILD_DIR}/install.log" 2>&1; then
    tail -n 20 "${BUILD_DIR}/install.log"; echo "ERROR: install failed" >&2; exit 1
  fi
  # the runtime library for targets with their own threads; the LLVM pass and the scripts are the same
  configure "${REPO_ROOT}/profiler" "$CMAKE_BUILD_PTHREAD" "${BUILD_DIR}/configure_pthread.log" -DDP_PTHREAD_COMPATIBILITY_MODE=1
  if ! cmake --build "$CMAKE_BUILD_PTHREAD" --target DiscoPoP_RT -j "$JOBS" > "${BUILD_DIR}/build_pthread.log" 2>&1; then
    grep -E "error|Error" "${BUILD_DIR}/build_pthread.log" | head -n 40; echo "ERROR: build failed (${BUILD_DIR}/build_pthread.log)" >&2; exit 1
  fi
  rm -rf "$(dirname "$LIBS_DIR_PTHREAD")"; mkdir -p "$(dirname "$LIBS_DIR_PTHREAD")"
  cp -r "$LIBS_DIR" "$LIBS_DIR_PTHREAD"
  cp "${CMAKE_BUILD_PTHREAD}/rtlib/libDiscoPoP_RT.a" "${LIBS_DIR_PTHREAD}/libDiscoPoP_RT.a"
  touch "${BUILD_DIR}/build.stamp"
  echo "built in $((SECONDS - start)) s"
elif [ ! -f "${BUILD_DIR}/build.stamp" ]; then
  echo "ERROR: --skip-build, but there is no build in ${BUILD_DIR}" >&2; exit 1
else
  newer="$(find "${REPO_ROOT}/profiler" "${REPO_ROOT}/test/unit_tests" "$LEAK_CHECK_DIR" -type f -newer "${BUILD_DIR}/build.stamp" -print -quit)"
  [ -z "$newer" ] || echo "WARNING: --skip-build: sources changed since the last build (e.g. ${newer}), the results may be stale"
fi

# ---------------------------------------------------------------------------------------------------------
# 1. unit tests
# ---------------------------------------------------------------------------------------------------------
UNIT_TESTS="${CMAKE_BUILD}/unit_tests/DiscoPoP_UT"
if ! $SKIP_UNIT_TESTS; then
  section "unit tests under AddressSanitizer and LeakSanitizer"
  start=$SECONDS
  if ASAN_OPTIONS="${ASAN_BASE}:detect_leaks=1" LSAN_OPTIONS="suppressions=${UNIT_TEST_SUPPRESSIONS}:print_suppressions=1" \
      "${CAP[@]}" "$UNIT_TESTS" > "${BUILD_DIR}/unit_tests.log" 2>&1; then
    grep -E "^\[  PASSED  \]" "${BUILD_DIR}/unit_tests.log"
    sed -n '/^Suppressions used:/,/^$/p' "${BUILD_DIR}/unit_tests.log"
  else
    grep -E -A 40 "ERROR: (Address|Leak)Sanitizer" "${BUILD_DIR}/unit_tests.log" | head -n 200
    grep -E "^\[  FAILED  \]" "${BUILD_DIR}/unit_tests.log"
    fail "unit tests failed, or ASan/LSan reported a memory error or leak (${BUILD_DIR}/unit_tests.log)"
  fi
  echo "($((SECONDS - start)) s)"
fi

# ---------------------------------------------------------------------------------------------------------
# 2. instrumented programs
# ---------------------------------------------------------------------------------------------------------
# compile with the profiler's wrapper (the target code itself without sanitizer instrumentation), link the
# sanitized runtime library, the sanitizer runtime and the leak check hook
build_program() { # <name> <source file> <libs dir>
  local dir="${PROGRAMS_DIR}/$1"
  rm -rf "$dir"; mkdir -p "$dir"
  cp "$2" "$dir/"
  (
    cd "$dir" || exit 1
    "${3}/CXX_wrapper.sh" -c "$(basename "$2")" -o program.o \
      && "${3}/LINKER_wrapper.sh" program.o "${PROGRAMS_DIR}/lsan_finalize_hook.o" -fsanitize=address \
        -Wl,--wrap=__dp_finalize -o program
  ) > "$dir/build.log" 2>&1
}

run_program() { # <name> <log> [args...]
  local name="$1" log="$2"; shift 2
  (
    cd "${PROGRAMS_DIR}/${name}" || exit 1
    ASAN_OPTIONS="$ASAN_PROGRAMS" "${CAP[@]}" ./program "$@"
  ) > "$log" 2>&1
  local rc=$?
  [ $rc -eq 0 ] || fail "${name} $* exited with code ${rc} (${log})"
}

if ! $SKIP_PROGRAMS; then
  PROGRAMS_DIR="${BUILD_DIR}/programs"
  rm -rf "$PROGRAMS_DIR"; mkdir -p "$PROGRAMS_DIR"
  if ! "$CLANGXX" -c -g -O1 -fsanitize=address "${LEAK_CHECK_DIR}/lsan_finalize_hook.cpp" -o "${PROGRAMS_DIR}/lsan_finalize_hook.o"; then
    echo "ERROR: compiling the leak check hook failed (is the sanitizer runtime of ${CLANGXX} installed?)" >&2; exit 1
  fi

  section "build instrumented programs (${JOBS} in parallel)"
  start=$SECONDS
  declare -A SOURCES=() LIBS=()
  for spec in "${GROWTH_PROGRAMS[@]}"; do
    read -r name variant _ _ <<< "$spec"
    SOURCES[$name]="${LEAK_CHECK_DIR}/programs/${name}.cpp"
    if [ "$variant" = pthread ]; then LIBS[$name]="$LIBS_DIR_PTHREAD"; else LIBS[$name]="$LIBS_DIR"; fi
  done
  SINGLE_RUN=(example)
  SOURCES[example]="${REPO_ROOT}/example/example.cpp"; LIBS[example]="$LIBS_DIR"
  for source in "${REPO_ROOT}"/test/profiler/*/*/test.cpp; do
    case_dir="$(dirname "$source")"
    name="profiler_$(basename "$(dirname "$case_dir")")_$(basename "$case_dir")"
    SOURCES[$name]="$source"; LIBS[$name]="$LIBS_DIR"; SINGLE_RUN+=("$name")
  done
  for name in "${!SOURCES[@]}"; do
    while [ "$(jobs -rp | wc -l)" -ge "$JOBS" ]; do wait -n; done
    build_program "$name" "${SOURCES[$name]}" "${LIBS[$name]}" &
  done
  wait
  for name in "${!SOURCES[@]}"; do
    [ -x "${PROGRAMS_DIR}/${name}/program" ] || fail "building ${name} failed (${PROGRAMS_DIR}/${name}/build.log)"
  done
  echo "built ${#SOURCES[@]} programs in $((SECONDS - start)) s"

  section "run instrumented programs"
  start=$SECONDS
  GROW_ARGS=()
  for spec in "${GROWTH_PROGRAMS[@]}"; do
    read -r name _ short long <<< "$spec"
    [ -x "${PROGRAMS_DIR}/${name}/program" ] || continue
    # DP_LEAK_CHECK_SETTLE: measure the live heap after the workers have drained their queues
    DP_LEAK_CHECK_SETTLE=1 run_program "$name" "${PROGRAMS_DIR}/${name}_short.log" "$short"
    DP_LEAK_CHECK_SETTLE=1 run_program "$name" "${PROGRAMS_DIR}/${name}_long.log" "$long"
    GROW_ARGS+=(--grow "${PROGRAMS_DIR}/${name}_short.log" "${PROGRAMS_DIR}/${name}_long.log")
  done
  LOGS=()
  for name in $(printf '%s\n' "${SINGLE_RUN[@]}" | sort); do
    [ -x "${PROGRAMS_DIR}/${name}/program" ] || continue
    run_program "$name" "${PROGRAMS_DIR}/${name}.log"
    LOGS+=("${PROGRAMS_DIR}/${name}.log")
  done
  echo "ran in $((SECONDS - start)) s"

  section "evaluate LeakSanitizer reports and live heap"
  if ! python3 "${LEAK_CHECK_DIR}/evaluate_leaks.py" --known-leaks "${LEAK_CHECK_DIR}/known_leaks.txt" \
      --heap-growth-limit-mb "$HEAP_GROWTH_LIMIT_MB" "${GROW_ARGS[@]}" "${LOGS[@]}"; then
    fail "leaks or growing memory of the runtime library in instrumented programs (see the report above)"
  fi
fi

section "summary"
if [ ${#FAILURES[@]} -ne 0 ]; then
  printf 'FAILED: %s\n' "${FAILURES[@]}"
  exit 1
fi
echo "profiler leak check passed"

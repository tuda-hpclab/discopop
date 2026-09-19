#!/usr/bin/env bash

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

# Measures how much of the runtime library (profiler/rtlib) the C++ unit tests execute.
#
# Uses clang's source based coverage rather than gcov: the runtime is full of header-inlined
# templates, and llvm-cov merges their instantiations by name, which gcov does not.
#
# Note that this only reports the code that DiscoPoP_UT links. The callbacks the LLVM pass
# injects (profiler/rtlib/injected_functions) are not part of the test binary; they are covered
# by the end-to-end suites instead, which this script does not measure.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD_DIR="${REPO_ROOT}/build_coverage"
MARKDOWN_OUT=""
MIN_LINE_COVERAGE=""
HTML_OUT=""
JOBS="$(nproc 2>/dev/null || echo 4)"

usage() {
    cat <<'EOF'
Usage: run_rtlib_coverage.sh [options]

  --build-dir <path>       build directory to use (default: <repo>/build_coverage)
  --markdown-out <file>    write a markdown summary, for use as a CI job summary
  --html-out <dir>         write a browsable HTML report
  --min-line-coverage <n>  exit non-zero if total line coverage drops below n percent
  -j, --jobs <n>           parallel build jobs (default: nproc)
  -h, --help               show this message
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --build-dir) BUILD_DIR="$2"; shift 2 ;;
        --markdown-out) MARKDOWN_OUT="$2"; shift 2 ;;
        --html-out) HTML_OUT="$2"; shift 2 ;;
        --min-line-coverage) MIN_LINE_COVERAGE="$2"; shift 2 ;;
        -j|--jobs) JOBS="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage >&2; exit 1 ;;
    esac
done

# The three tools have to agree on the profile format, so they are picked as a set: a versioned
# clang is matched with the llvm-profdata and llvm-cov of the same major version.
CLANG=""
CLANGPP=""
PROFDATA=""
COV=""
for _v in 22 21 20 19; do
    if command -v "clang-$_v" >/dev/null 2>&1 \
        && command -v "clang++-$_v" >/dev/null 2>&1 \
        && command -v "llvm-profdata-$_v" >/dev/null 2>&1 \
        && command -v "llvm-cov-$_v" >/dev/null 2>&1; then
        CLANG="clang-$_v"
        CLANGPP="clang++-$_v"
        PROFDATA="llvm-profdata-$_v"
        COV="llvm-cov-$_v"
        break
    fi
done
if [ -z "$CLANG" ]; then
    if command -v clang >/dev/null 2>&1 \
        && command -v clang++ >/dev/null 2>&1 \
        && command -v llvm-profdata >/dev/null 2>&1 \
        && command -v llvm-cov >/dev/null 2>&1; then
        CLANG=clang
        CLANGPP=clang++
        PROFDATA=llvm-profdata
        COV=llvm-cov
    else
        echo "ERROR: need clang, clang++, llvm-profdata and llvm-cov of a matching version" >&2
        exit 1
    fi
fi
echo "Using ${CLANGPP}, ${PROFDATA}, ${COV}"

# -O0 keeps the line numbers in the report meaningful. GTEST_HAS_CXXABI_H_=0 keeps GoogleTest from
# including the cxxabi.h that ships with LLVM, which conflicts with the one of the system libstdc++.
CXX_COVERAGE_FLAGS="-O0 -g -DGTEST_HAS_CXXABI_H_=0 -fprofile-instr-generate -fcoverage-mapping"

CC="$CLANG" CXX="$CLANGPP" cmake \
    -S "$REPO_ROOT" \
    -B "$BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DDP_BUILD_UNITTESTS=1 \
    -DCMAKE_C_FLAGS_RELEASE="-O0 -g" \
    -DCMAKE_CXX_FLAGS_RELEASE="$CXX_COVERAGE_FLAGS" \
    -DCMAKE_EXE_LINKER_FLAGS="-fprofile-instr-generate"

cmake --build "$BUILD_DIR" --target DiscoPoP_UT -j "$JOBS"

TEST_BINARY="${BUILD_DIR}/test/unit_tests/DiscoPoP_UT"
PROFRAW="${BUILD_DIR}/rtlib.profraw"
PROFDATA_FILE="${BUILD_DIR}/rtlib.profdata"

rm -f "$PROFRAW" "$PROFDATA_FILE"
LLVM_PROFILE_FILE="$PROFRAW" "$TEST_BINARY"
"$PROFDATA" merge -sparse "$PROFRAW" -o "$PROFDATA_FILE"

REPORT_ARGS=("$TEST_BINARY" "-instr-profile=$PROFDATA_FILE" "${REPO_ROOT}/profiler/rtlib")

echo
"$COV" report "${REPORT_ARGS[@]}" | sed "s|${REPO_ROOT}/profiler/rtlib/||"

if [ -n "$HTML_OUT" ]; then
    "$COV" show "${REPORT_ARGS[@]}" -format=html -output-dir="$HTML_OUT" -show-line-counts-or-regions
    echo
    echo "HTML report written to ${HTML_OUT}/index.html"
fi

# The totals are read back from the machine readable export rather than scraped off the table.
SUMMARY_JSON="$("$COV" export "${REPORT_ARGS[@]}" -summary-only)"
read -r LINE_PCT FUNC_PCT REGION_PCT BRANCH_PCT <<<"$(
    printf '%s' "$SUMMARY_JSON" | python3 -c '
import json, sys
totals = json.load(sys.stdin)["data"][0]["totals"]
print(" ".join("%.2f" % totals[k]["percent"] for k in ("lines", "functions", "regions", "branches")))
'
)"

echo
echo "rtlib coverage from the unit tests: lines ${LINE_PCT}%, functions ${FUNC_PCT}%, regions ${REGION_PCT}%, branches ${BRANCH_PCT}%"

if [ -n "$MARKDOWN_OUT" ]; then
    {
        echo "## Runtime library coverage (unit tests)"
        echo
        echo "| Metric | Coverage |"
        echo "| --- | ---: |"
        echo "| Lines | ${LINE_PCT}% |"
        echo "| Functions | ${FUNC_PCT}% |"
        echo "| Regions | ${REGION_PCT}% |"
        echo "| Branches | ${BRANCH_PCT}% |"
        echo
        echo '<details><summary>Per file</summary>'
        echo
        echo '```'
        "$COV" report "${REPORT_ARGS[@]}" | sed "s|${REPO_ROOT}/profiler/rtlib/||"
        echo '```'
        echo
        echo '</details>'
        echo
        echo "_Excludes \`profiler/rtlib/injected_functions\`: the callbacks the LLVM pass injects are"
        echo "not linked into the unit test binary and are covered by the end-to-end suites instead._"
    } > "$MARKDOWN_OUT"
    echo "Markdown summary written to ${MARKDOWN_OUT}"
fi

if [ -n "$MIN_LINE_COVERAGE" ]; then
    if python3 -c "import sys; sys.exit(0 if float('$LINE_PCT') < float('$MIN_LINE_COVERAGE') else 1)"; then
        echo "ERROR: line coverage ${LINE_PCT}% is below the required ${MIN_LINE_COVERAGE}%" >&2
        exit 1
    fi
    echo "Line coverage ${LINE_PCT}% meets the required ${MIN_LINE_COVERAGE}%"
fi

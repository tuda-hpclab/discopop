#!/bin/bash

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License. See the LICENSE file in the package base
# directory for details.

# Sourced by CC_wrapper.sh, CXX_wrapper.sh and the MPI wrappers (a copy of this file is sourced by the wrappers of the
# hotspot detection, hotspot_detection/scripts/dp_openmp.sh; the two packages are installed independently and have to
# agree): decides what happens to the OpenMP flags of a compiler call.
#
# By default the flags are kept and a warning says that the program is profiled with OpenMP enabled and how to remove
# the flags. DP_STRIP_OPENMP=1 removes them (the program is then profiled as the sequential code its pragmas annotate).
# The result is the array DP_ARGS, which the wrapper uses instead of "$@" for every compiler call (the instrumented
# compilation as well as the AST dump, which must see the same flags).
#
# The first call of a build that sees an OpenMP flag records that in "$DOT_DISCOPOP/openmp_flags_seen.json" (the project
# manager reads it after the build to show the warning in its own words, and removes it before a build); only that call
# prints the warning. DP_OPENMP_QUIET=1 (set by the project manager) records without printing.

# Flags that enable OpenMP (matched as a whole argument). -fopenmp-simd creates no threads: it is removed together with
# the others but is no reason to warn.
dp_is_openmp_flag() {
  case "$1" in
    -fopenmp | -fopenmp=* | -qopenmp | -qopenmp=* | -openmp | -lomp | -lgomp | -liomp5) return 0 ;;
  esac
  return 1
}

# Sets DP_ARGS from the arguments "$@" (see above), exports nothing.
dp_handle_openmp() {
  DP_ARGS=()
  local strip=0 found="" arg next flag skip i=0
  local args=("$@") n=$#
  case "${DP_STRIP_OPENMP:-}" in
    1 | yes | YES | true | TRUE | on | ON) strip=1 ;;
  esac

  while [ "$i" -lt "$n" ]; do
    arg="${args[$i]}"
    flag=""
    skip=1
    if dp_is_openmp_flag "$arg"; then
      flag="$arg"
    elif [ "$arg" = "-fopenmp-simd" ]; then
      if [ "$strip" -eq 1 ]; then
        i=$((i + 1))
        continue
      fi
    elif [ "$arg" = "-Xclang" ] || [ "$arg" = "-Xpreprocessor" ]; then
      # the spelling of the Homebrew libomp recipes: -Xpreprocessor -fopenmp
      next="${args[$((i + 1))]:-}"
      if [ "$next" = "-fopenmp" ]; then
        flag="${arg} ${next}"
        skip=2
      fi
    fi
    if [ -n "$flag" ]; then
      found="${found:+${found} }${flag}"
      if [ "$strip" -eq 1 ]; then
        i=$((i + skip))
        continue
      fi
    fi
    DP_ARGS+=("$arg")
    i=$((i + 1))
  done

  [ -n "$found" ] || return 0
  dp_report_openmp "$found" "$strip"
}

# Prints the warning (strip=0) or the note (strip=1) once per build.
dp_report_openmp() {
  local found="$1" strip="$2" dot="${DOT_DISCOPOP:-$PWD/.discopop}" marker first=1 stripped=false
  [ "$strip" -eq 1 ] && stripped=true
  marker="${dot}/openmp_flags_seen.json"
  if [ -d "$dot" ]; then
    # noclobber: the first of several concurrent compiler calls creates the file and reports
    ( set -o noclobber; printf '{"flags": "%s", "stripped": %s}\n' "${found//[\"\\]/}" "$stripped" > "$marker" ) 2>/dev/null || first=0
  fi
  [ "$first" -eq 1 ] || return 0
  [ "${DP_OPENMP_QUIET:-}" = "1" ] && return 0

  if [ "$strip" -eq 1 ]; then
    echo "DiscoPoP: NOTE: removed the OpenMP flags (${found}) from the compiler call (DP_STRIP_OPENMP=1)." >&2
    echo "          The pragmas are ignored: the program is profiled as the sequential code. Code that calls omp_* functions" >&2
    echo "          needs #ifdef _OPENMP guards, as it no longer links against the OpenMP runtime." >&2
    return 0
  fi
  echo "DiscoPoP: WARNING: the compiler call contains OpenMP flags (${found}); they are kept." >&2
  echo "          The OpenMP pragmas of the program are active while it is profiled: their threads are instrumented as" >&2
  echo "          concurrent code, the dependences found depend on the thread schedule, the pattern detection does not know" >&2
  echo "          that a loop is parallel already, and the runtime may need DP_PTHREAD_COMPATIBILITY_MODE=1." >&2
  echo "          To profile the sequential code instead, remove the OpenMP flags from the instrumented build:" >&2
  echo "            - set the environment variable DP_STRIP_OPENMP=1 for the build (discopop_cc / discopop_cxx)," >&2
  echo "            - or pass --strip-openmp to discopop_project_manager," >&2
  echo "            - or enable 'Remove OpenMP flags' in the Project Setup stage of the project manager GUI." >&2
}

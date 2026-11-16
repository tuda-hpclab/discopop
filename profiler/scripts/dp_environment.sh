#!/bin/bash

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License. See the LICENSE file in the package base
# directory for details.

# Sourced by CC_wrapper.sh and CXX_wrapper.sh: finds the .discopop directory of the project when DOT_DISCOPOP is not set,
# so that the compiler calls of any build (in the project directory, in a build directory below it, in a subdirectory)
# write to the same directory, as DOT_DISCOPOP set to the same absolute path would make them. The rule is the one of
# dputil::FindDotDiscopop (share/lib/DPUtils.cpp), which the pass applies to a compilation without the wrapper.

# Prints the nearest directory named .discopop in the directory $1 or one of its ancestors (symbolic links resolved);
# returns 1 if there is none. A .discopop without a project/ subdirectory (a leftover of a build that wrote to the
# current directory) is still the nearest, but the use of it is questioned if a farther one holds the project
# configuration of discopop_project_manager --init.
dp_find_dot_discopop() {
  local dir nearest="" farther=""
  dir="$(cd "$1" 2>/dev/null && pwd -P)" || return 1
  while :; do
    if [ -d "${dir}/.discopop" ]; then
      if [ -z "$nearest" ]; then
        nearest="${dir}/.discopop"
        [ -d "${nearest}/project" ] && break
      elif [ -d "${dir}/.discopop/project" ]; then
        farther="${dir}/.discopop"
        break
      fi
    fi
    [ "$dir" = "/" ] && break
    dir="$(dirname "$dir")"
  done
  [ -n "$nearest" ] || return 1
  if [ -n "$farther" ]; then
    echo "DiscoPoP: WARNING: using ${nearest}, which holds no project configuration, although ${farther} does." >&2
    echo "          Remove the former if an earlier build left it behind, or set DOT_DISCOPOP." >&2
  fi
  printf '%s\n' "$nearest"
}

# If DOT_DISCOPOP is unset or empty: exports the .discopop directory found from the current directory or, if there is
# none, from the directory of a source file among the arguments "$@" (a build outside of the project). DP_PROJECT_ROOT_DIR,
# if unset, becomes the directory that holds it. Returns 1 if there is none (nothing is changed then). A DOT_DISCOPOP that
# is set always wins.
dp_resolve_dot_discopop() {
  [ -n "${DOT_DISCOPOP:-}" ] && return 0
  local found="" arg
  found="$(dp_find_dot_discopop "$PWD")" || found=""
  if [ -z "$found" ]; then
    for arg in "$@"; do
      case "$arg" in
        *.c | *.cc | *.cpp | *.cxx | *.c++ | *.C | *.cu | *.m | *.mm)
          if [ -f "$arg" ]; then
            found="$(dp_find_dot_discopop "$(dirname "$arg")")" || found=""
            [ -n "$found" ] && break
          fi
          ;;
      esac
    done
  fi
  [ -n "$found" ] || return 1
  export DOT_DISCOPOP="$found"
  if [ -z "${DP_PROJECT_ROOT_DIR:-}" ]; then
    DP_PROJECT_ROOT_DIR="$(dirname "$found")"
    export DP_PROJECT_ROOT_DIR
  fi
  return 0
}

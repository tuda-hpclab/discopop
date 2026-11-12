# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License. See the LICENSE file in the package base
# directory for details.

# Sourced by CC_wrapper.sh and CXX_wrapper.sh.
#
# dp_dump_ast <clang> <dot discopop dir> <output file> <compiler arguments...>
#
# Writes the AST of the translation unit that the compiler arguments compile to <output file>, reduced to what the
# explorer queries: the declarations located in the files of FileMapping.txt (without one: below DP_PROJECT_ROOT_DIR,
# else below the directory holding .discopop), without type nodes (see filter_ast_dump.py). Needs PARENT_PATH to be
# the directory of the profiler's files.
#
# Clang's JSON AST dump includes every declaration transitively reachable from included headers (libc, libstdc++,
# MPI, Boost, ...), which for real projects is tens of GB per translation unit. With the AST export plugin
# (DiscoPoPASTExport-<clang major>.so, built if the Clang development files exist) the unwanted declarations are never
# written. Without it, or if it fails, the complete dump is filtered while it is written.
# DP_AST_NO_PLUGIN=1 uses the filtered dump even if the plugin exists. The directories of DP_PROJECT_EXCLUDE_DIRS
# (separated by ':', absolute or relative to DP_PROJECT_ROOT_DIR), which the pass does not count as part of the
# project, are left out by both.
dp_dump_ast() {
  local clang="$1" dot_dp="$2" out_file="$3"
  shift 3
  local project_root file_mapping major plugin raw_tmp
  # the directory the pass instruments (DP_PROJECT_ROOT_DIR, the instrumentation scope), else the one holding
  # .discopop; it decides without a FileMapping.txt, and relative entries of DP_PROJECT_EXCLUDE_DIRS are taken
  # relative to it. A relative scope is taken relative to the current directory and normalized ("." and ".."
  # resolved), as the absolute paths of the AST are compared with it.
  if [ -n "${DP_PROJECT_ROOT_DIR:-}" ]; then
    project_root="$(python3 -c 'import os, sys; print(os.path.normpath(os.path.abspath(sys.argv[1])))' \
      "$DP_PROJECT_ROOT_DIR")"
  else
    project_root="$(dirname "${dot_dp}")"
  fi
  file_mapping="${dot_dp}/FileMapping.txt"

  if [ -z "${DP_AST_NO_PLUGIN:-}" ]; then
    major="$("$clang" --version 2>/dev/null | sed -n 's/.*clang version \([0-9][0-9]*\).*/\1/p' | head -n 1)"
    plugin="${PARENT_PATH}/DiscoPoPASTExport-${major}.so"
    if [ -n "$major" ] && [ -f "$plugin" ]; then
      raw_tmp="$(mktemp "${dot_dp}/profiler/ast_export.XXXXXX")" || return 1
      if "$clang" "$@" -fsyntax-only -Xclang -load -Xclang "$plugin" -Xclang -add-plugin -Xclang dp-ast-export \
        -Xclang -plugin-arg-dp-ast-export -Xclang "filemap=${file_mapping}" \
        -Xclang -plugin-arg-dp-ast-export -Xclang "root=${project_root}" \
        -Xclang -plugin-arg-dp-ast-export -Xclang "exclude=${DP_PROJECT_EXCLUDE_DIRS:-}" \
        -Xclang -plugin-arg-dp-ast-export -Xclang "out=${raw_tmp}" &&
        python3 "${PARENT_PATH}/filter_ast_dump.py" "${project_root}" "${file_mapping}" <"$raw_tmp" >"$out_file"; then
        rm -f -- "$raw_tmp"
        return 0
      fi
      rm -f -- "$raw_tmp"
      echo "DiscoPoP: the AST export plugin failed, filtering the AST dump of clang instead" >&2
      : >"$out_file"
    fi
  fi

  (
    set -o pipefail
    "$clang" "$@" -fsyntax-only -Xclang -ast-dump=json |
      python3 "${PARENT_PATH}/filter_ast_dump.py" "${project_root}" "${file_mapping}" >"$out_file"
  )
}

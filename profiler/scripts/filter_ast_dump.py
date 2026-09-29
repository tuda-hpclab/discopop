#!/usr/bin/env python3
# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Prune a clang ``-ast-dump=json`` tree down to declarations under a project root.

Clang's JSON AST dump includes every declaration transitively reachable from
included headers (libc, libstdc++, MPI, ...), not just the user's own source.
For real C++ projects this makes the dump many times larger than what
DiscoPoP's explorer pattern detection ever queries (it only ever looks up AST
nodes by a project file path resolved from FileMapping.txt). This script sits
between clang and the on-disk ast_dump.json and drops any subtree whose
resolved source location falls outside the project directory.

Reads clang's JSON on stdin, writes the pruned JSON to stdout. Handles the
same file/line "unchanged from previous sibling" omission rules as
``discopop_explorer.utilities.ASTUtils.ASTGraph.ClangASTGraph`` -- a node's
effective file must be resolved the same way here as it is when the pruned
dump is later loaded, and the resolved file is written back explicitly into
every kept node so a kept node cutting on the topology when a preceding
sibling is dropped.
"""

import json
import sys
from typing import Any, Optional


def _resolve_macro_loc(loc: dict[str, Any]) -> dict[str, Any]:
    """Prefer expansionLoc (macro use site) over spellingLoc (macro definition site).

    Mirrors ``ClangASTGraph._resolve_macro_loc``: a macro-expanded position's
    ``spellingLoc`` can point into an unrelated system header (the macro's
    definition site), while ``expansionLoc`` is always the actual use site in
    the file being compiled.
    """
    if "expansionLoc" in loc:
        return loc["expansionLoc"]
    if "spellingLoc" in loc:
        return loc["spellingLoc"]
    return loc


def _own_file(node: dict[str, Any], inherited_file: Optional[str]) -> Optional[str]:
    """Resolve a node's own effective file, inheriting from the previous sibling."""
    loc = _resolve_macro_loc(node.get("loc", {}))
    return loc.get("file", inherited_file)


def _is_kept(file_: Optional[str], project_root: str) -> bool:
    # None means the node's location could not be resolved at all (e.g. a
    # structural wrapper with no context yet) -- keep rather than risk
    # dropping project code on an inheritance-resolution edge case.
    if file_ is None:
        return True
    # Clang records the file passed on the compile command line, and any
    # quote-included ("...") header resolved relative to it, as a bare or
    # relative path (e.g. "main.cpp", "utils.hpp") -- these are always the
    # project's own files. Angle-bracket (<...>) includes resolved via the
    # system/library search path come back as absolute paths. Both project
    # source passed with an absolute path and project headers pulled in via
    # an absolute -I are covered by the project_root prefix check.
    if not file_.startswith("/"):
        return True
    return file_.startswith(project_root)


def _bake_file(node: dict[str, Any], own_file: Optional[str]) -> None:
    """Write the resolved file back into the node's own loc, if it was inherited.

    Once preceding siblings are pruned, the "unchanged from previous sibling"
    omission Clang relies on no longer holds, so a kept node whose file was
    only implicit must carry it explicitly for the pruned dump to be
    self-consistent when reloaded.
    """
    if own_file is None:
        return
    loc = node.get("loc")
    if not isinstance(loc, dict):
        return
    resolved = _resolve_macro_loc(loc)
    if "file" not in resolved:
        resolved["file"] = own_file


def _filter_children(
    children: list[dict[str, Any]], inherited_file: Optional[str], project_root: str
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    ctx_file = inherited_file
    for child in children:
        own_file = _own_file(child, ctx_file)
        if _is_kept(own_file, project_root):
            _filter_subtree(child, own_file, project_root)
            kept.append(child)
        # The next sibling's inheritance context advances regardless of
        # whether *this* sibling survived the filter.
        ctx_file = own_file
    return kept


def _filter_subtree(node: dict[str, Any], own_file: Optional[str], project_root: str) -> None:
    _bake_file(node, own_file)
    children = node.get("inner")
    if children:
        node["inner"] = _filter_children(children, own_file, project_root)


def filter_ast_dump(text: str, project_root: str) -> str:
    """Parse one or more concatenated top-level JSON objects and prune each.

    Concatenated objects occur when multiple translation units are dumped
    into the same file (one clang invocation per source file, appended).
    """
    if not project_root.endswith("/"):
        project_root += "/"

    decoder = json.JSONDecoder()
    stripped = text.lstrip()
    pos = 0
    out_parts: list[str] = []

    while pos < len(stripped):
        obj, end = decoder.raw_decode(stripped, pos)
        obj["inner"] = _filter_children(obj.get("inner", []), None, project_root)
        out_parts.append(json.dumps(obj))
        pos = end
        while pos < len(stripped) and stripped[pos] in " \t\n\r":
            pos += 1

    return "\n".join(out_parts)


def main() -> None:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <project_root>", file=sys.stderr)
        sys.exit(1)

    project_root = sys.argv[1]
    text = sys.stdin.read()
    if not text.strip():
        return
    sys.stdout.write(filter_ast_dump(text, project_root))


if __name__ == "__main__":
    main()

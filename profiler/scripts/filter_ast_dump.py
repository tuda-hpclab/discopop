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

The input is processed one top-level declaration at a time (the declarations of
the translation unit are the items of its ``inner`` array), so the memory
needed does not scale with the size of the unfiltered dump, which is dominated
by system headers.
"""

import io
import json
import re
import sys
from typing import Any, Optional, TextIO


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


class _Reader:
    """Incremental reader that decodes JSON values from a text stream without reading it all at once."""

    _MIN_CHUNK = 1 << 20

    def __init__(self, source: TextIO) -> None:
        self.source = source
        self.buf = ""
        self.pos = 0
        self.eof = False
        self.decoder = json.JSONDecoder()

    def fill(self) -> bool:
        """Read more input, doubling the amount each time (so re-decoding a huge value stays linear)."""
        if self.eof:
            return False
        chunk = self.source.read(max(self._MIN_CHUNK, len(self.buf) - self.pos))
        if not chunk:
            self.eof = True
            return False
        self.buf = self.buf[self.pos :] + chunk
        self.pos = 0
        return True

    def compact(self) -> None:
        if self.pos > self._MIN_CHUNK:
            self.buf = self.buf[self.pos :]
            self.pos = 0

    def skip_ws(self) -> Optional[str]:
        """Advance to the next non-whitespace character and return it (None at the end of the input)."""
        while True:
            while self.pos < len(self.buf) and self.buf[self.pos] in " \t\n\r":
                self.pos += 1
            if self.pos < len(self.buf):
                return self.buf[self.pos]
            if not self.fill():
                return None

    def decode_value(self) -> Any:
        while True:
            try:
                obj, end = self.decoder.raw_decode(self.buf, self.pos)
            except json.JSONDecodeError:
                # the value may continue beyond the buffer; a genuine syntax error surfaces at the end of the input
                if not self.fill():
                    raise
                continue
            self.pos = end
            return obj


_INNER_START = re.compile(r'"inner"\s*:\s*\[')


def _find_header_end(reader: _Reader) -> Optional[int]:
    """Position behind the ``[`` of the top-level ``inner`` array, or None if the object has no such header."""
    search_from = reader.pos
    while True:
        match = _INNER_START.search(reader.buf, search_from)
        if match is not None:
            header = reader.buf[reader.pos : match.start()].rstrip()
            try:
                json.loads(header.rstrip(",") + "}")
            except ValueError:
                return None
            return match.end()
        if not reader.fill():
            return None
        # fill() moved the unread data to the buffer start
        search_from = 0


def _stream_object(reader: _Reader, out: TextIO, project_root: str) -> None:
    """Prune one top-level object, holding only one declaration of its ``inner`` array in memory at a time."""
    header_end = _find_header_end(reader)
    if header_end is None:
        # no ``inner`` array in the header (unexpected for a clang dump): prune the object as a whole
        obj = reader.decode_value()
        obj["inner"] = _filter_children(obj.get("inner", []), None, project_root)
        out.write(json.dumps(obj))
        return

    out.write(reader.buf[reader.pos : header_end])
    reader.pos = header_end
    ctx_file: Optional[str] = None
    first = True
    while True:
        reader.compact()
        ch = reader.skip_ws()
        if ch is None:
            raise ValueError("truncated AST dump: the top-level 'inner' array is not closed")
        if ch == ",":
            reader.pos += 1
            continue
        if ch == "]":
            reader.pos += 1
            break
        child = reader.decode_value()
        own_file = _own_file(child, ctx_file)
        if _is_kept(own_file, project_root):
            _filter_subtree(child, own_file, project_root)
            out.write(("" if first else ", ") + json.dumps(child))
            first = False
        # the next sibling's inheritance context advances regardless of whether this one survived
        ctx_file = own_file
        del child
    out.write("]")

    # whatever follows the array inside the top-level object (normally just the closing brace)
    ch = reader.skip_ws()
    if ch == ",":
        # turn the comma into the opening brace, so that the remaining members decode as an object
        reader.buf = reader.buf[: reader.pos] + "{" + reader.buf[reader.pos + 1 :]
        extra = reader.decode_value()
        if extra:
            out.write(", " + json.dumps(extra)[1:-1])
        out.write("}")
    elif ch == "}":
        reader.pos += 1
        out.write("}")
    else:
        raise ValueError("malformed AST dump: unexpected content behind the top-level 'inner' array")


def filter_ast_stream(source: TextIO, out: TextIO, project_root: str) -> None:
    """Prune one or more concatenated top-level JSON objects read from ``source`` and write them to ``out``.

    The objects are processed declaration by declaration: the memory needed is that of the largest single
    top-level declaration plus the read buffer, not that of the whole (unfiltered) dump.
    """
    if not project_root.endswith("/"):
        project_root += "/"
    reader = _Reader(source)
    first = True
    while reader.skip_ws() is not None:
        if not first:
            out.write("\n")
        first = False
        _stream_object(reader, out, project_root)


def filter_ast_dump(text: str, project_root: str) -> str:
    """Prune one or more concatenated top-level JSON objects given as a string (see ``filter_ast_stream``).

    Concatenated objects occur when multiple translation units are dumped
    into the same file (one clang invocation per source file, appended).
    """
    out = io.StringIO()
    filter_ast_stream(io.StringIO(text), out, project_root)
    return out.getvalue()


def main() -> None:
    if len(sys.argv) != 2:
        print(f"usage: {sys.argv[0]} <project_root>", file=sys.stderr)
        sys.exit(1)

    filter_ast_stream(sys.stdin, sys.stdout, sys.argv[1])


if __name__ == "__main__":
    main()

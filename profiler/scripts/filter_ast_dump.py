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

The input is streamed: a declaration is only held in memory as a whole if it is
small, larger ones (namespaces, huge class templates) are read member by member,
so the memory needed scales with neither the unfiltered dump, which is dominated
by system headers, nor with the largest declaration.
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

    def ensure(self, n: int) -> None:
        """Make at least ``n`` unread characters available, as far as the input has them."""
        while len(self.buf) - self.pos < n and self.fill():
            pass

    def decode_value(self, limit: Optional[int] = None) -> Any:
        """Decode the next JSON value; raise ``_TooLarge`` if it does not fit into ``limit`` characters of buffer."""
        while True:
            try:
                obj, end = self.decoder.raw_decode(self.buf, self.pos)
            except json.JSONDecodeError:
                # the value may continue beyond the buffer; a genuine syntax error surfaces at the end of the input
                if limit is not None and len(self.buf) - self.pos >= limit:
                    raise _TooLarge() from None
                if not self.fill():
                    raise
                continue
            self.pos = end
            return obj


class _TooLarge(Exception):
    """A value is larger than the amount that may be decoded as a whole."""


# A declaration is decoded as a whole (fast, in C) if it fits into this many characters. A larger one -- the
# declarations of a namespace such as ``std`` or ``boost``, but also a single class template whose type sugar spans
# gigabytes -- is read member by member instead, so memory does not grow with the size of any declaration.
_MAX_DECODE = 64 << 20
# Namespaces and linkage specifications nearly always are large: stream them directly, instead of first buffering
# up to _MAX_DECODE in vain. Clang writes ``id`` and ``kind`` first.
_CONTAINER_HINT = re.compile(r'\{\s*"id"\s*:\s*"[^"]*"\s*,\s*"kind"\s*:\s*"(?:NamespaceDecl|LinkageSpecDecl)"')
_HINT_WINDOW = 1024


def _stream_children(reader: _Reader, out: TextIO, project_root: str, ctx_file: Optional[str], emit: bool) -> None:
    """Process the elements of an ``inner`` array whose ``[`` was consumed; write the kept ones if ``emit`` is set."""
    first = True
    while True:
        reader.compact()
        ch = reader.skip_ws()
        if ch is None:
            raise ValueError("truncated AST dump: an 'inner' array is not closed")
        if ch == ",":
            reader.pos += 1
            continue
        if ch == "]":
            reader.pos += 1
            return
        if ch != "{":
            raise ValueError("malformed AST dump: an element of an 'inner' array is not an object")
        sep = "" if first else ", "
        reader.ensure(_HINT_WINDOW)
        streamed = _CONTAINER_HINT.match(reader.buf, reader.pos) is not None
        if not streamed:
            try:
                child = reader.decode_value(_MAX_DECODE)
            except _TooLarge:
                streamed = True
        if streamed:
            own_file, wrote = _stream_object(reader, out, project_root, ctx_file, emit, sep)
        else:
            own_file = _own_file(child, ctx_file)
            wrote = emit and _is_kept(own_file, project_root)
            if wrote:
                _filter_subtree(child, own_file, project_root)
                out.write(sep + json.dumps(child))
            del child
        if wrote:
            first = False
        # the next sibling's inheritance context advances regardless of whether this one survived
        ctx_file = own_file


def _stream_object(
    reader: _Reader, out: TextIO, project_root: str, ctx_file: Optional[str], emit: bool, sep: str
) -> tuple[Optional[str], bool]:
    """Read the object at the reader's position member by member; write it (preceded by ``sep``) if it is kept.

    Clang writes ``loc`` before ``inner``, so whether the object is kept is known when the ``inner`` array starts and
    its elements can be processed one at a time. Returns the object's own file and whether it was written.
    """
    reader.pos += 1  # "{"
    members: dict[str, Any] = {}
    after_inner: dict[str, Any] = {}
    own_file: Optional[str] = None
    keep = False
    seen_inner = False
    while True:
        ch = reader.skip_ws()
        if ch is None:
            raise ValueError("truncated AST dump: an object is not closed")
        if ch == ",":
            reader.pos += 1
            continue
        if ch == "}":
            reader.pos += 1
            break
        key = reader.decode_value()
        if not isinstance(key, str) or reader.skip_ws() != ":":
            raise ValueError("malformed AST dump: expected a member name followed by ':'")
        reader.pos += 1
        value_start = reader.skip_ws()
        if key == "inner" and not seen_inner and value_start == "[":
            seen_inner = True
            own_file = _own_file(members, ctx_file)
            keep = emit and _is_kept(own_file, project_root)
            if keep:
                _bake_file(members, own_file)
                out.write(sep + (json.dumps(members)[:-1] + ", " if members else "{") + '"inner": [')
            reader.pos += 1  # "["
            _stream_children(reader, out, project_root, own_file, keep)
            if keep:
                out.write("]")
        else:
            (after_inner if seen_inner else members)[key] = reader.decode_value()
    if not seen_inner:
        own_file = _own_file(members, ctx_file)
        keep = emit and _is_kept(own_file, project_root)
        if keep:
            _bake_file(members, own_file)
            out.write(sep + json.dumps(members))
    elif keep:
        out.write((", " + json.dumps(after_inner)[1:-1] if after_inner else "") + "}")
    return own_file, keep


def filter_ast_stream(source: TextIO, out: TextIO, project_root: str) -> None:
    """Prune one or more concatenated top-level JSON objects read from ``source`` and write them to ``out``.

    A declaration is held in memory as a whole only if it is small (``_MAX_DECODE``); larger ones are read member by
    member, so the memory needed does not depend on the size of the (unfiltered) dump or of any declaration.
    """
    # type trees nest deeply, and the pruning of a decoded declaration recurses over them
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))
    if not project_root.endswith("/"):
        project_root += "/"
    reader = _Reader(source)
    first = True
    while (ch := reader.skip_ws()) is not None:
        if ch != "{":
            raise ValueError("malformed AST dump: a top-level value is not an object")
        if not first:
            out.write("\n")
        first = False
        _stream_object(reader, out, project_root, None, True, "")


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

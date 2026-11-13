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
nodes by a file path resolved from FileMapping.txt). This script sits between
clang and the on-disk ast_dump.json and drops any subtree whose resolved source
location is not one of the files in FileMapping.txt (or, without it, outside the
project directory), as well as the type nodes (see ``_Policy``).

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
import os
import re
import sys
import time
from typing import Any, Callable, Optional, Protocol, TextIO


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


def _load_file_mapping(path: str) -> tuple[frozenset[str], int]:
    """The files of ``FileMapping.txt`` (lines ``<id><TAB><path>``), as normalized and as resolved paths, and their
    number."""
    files: set[str] = set()
    count = 0
    try:
        with open(path, "r") as f:
            for line in f:
                _, tab, name = line.rstrip("\n").partition("\t")
                if tab and name:
                    count += 1
                    files.add(os.path.normpath(name))
                    files.add(os.path.realpath(name))
    except OSError:
        pass
    return frozenset(files), count


def _excluded_directories(entries: str, roots: tuple[str, ...]) -> tuple[str, ...]:
    """The directories of a ``:`` separated list, absolute or relative to the project root, in every spelling (each
    root, with and without symbolic links resolved), with a trailing ``/`` (so ``_deps`` does not exclude ``_deps2``).
    """
    directories: list[str] = []
    for entry in entries.split(":"):
        if not entry:
            continue
        candidates = [entry] if entry.startswith("/") else [os.path.join(root, entry) for root in roots]
        for candidate in candidates:
            for spelling in (os.path.normpath(candidate), os.path.realpath(candidate)):
                directory = os.path.join(spelling, "")
                if directory not in directories:
                    directories.append(directory)
    return tuple(directories)


class _Policy:
    """What is kept: declarations located in files the profiler instrumented, and no type nodes.

    The explorer looks AST nodes up by the files of ``FileMapping.txt`` (the files the LLVM pass registered while
    instrumenting), so everything located elsewhere is dead weight, wherever it lives: system headers, but also
    dependencies below the project directory (``_deps`` of a CMake build) and project headers without code. Without a
    file mapping (not written yet, or empty) the fallback is the project directory.

    Files in one of the excluded directories (``DP_PROJECT_EXCLUDE_DIRS`` of the command line tool, the variable the
    LLVM pass uses as well: separated by ``:``, absolute or relative to the project root) are never kept, with or
    without a file mapping.

    Type nodes (``ElaboratedType``, ``TemplateSpecializationType``, ...) have no location and are never queried: the
    explorer reads types from the ``type`` of the declarations and expressions. Template metaprogramming makes them
    huge (single type aliases of many GB).
    """

    def __init__(
        self,
        project_root: str,
        file_mapping: Optional[str] = None,
        prune_types: bool = True,
        excluded_dirs: str = "",
    ) -> None:
        self.project_root = project_root if project_root.endswith("/") else project_root + "/"
        # a checkout reached through a symbolic link (/home/... -> /mnt/storage/...) is named either way, depending on
        # who resolved what: compare with both forms
        self.project_root_real = os.path.join(os.path.realpath(project_root), "")
        self.excluded_dirs = excluded_dirs
        self.excluded = _excluded_directories(excluded_dirs, (self.project_root, self.project_root_real))
        self.file_mapping = file_mapping
        self.mapped, self.mapped_files = _load_file_mapping(file_mapping) if file_mapping else (frozenset(), 0)
        self.prune_types = prune_types
        self._cache: dict[str, bool] = {}
        # what happened, for the status messages: nodes kept, and subtrees dropped as a whole
        self.kept = 0
        self.dropped_unselected = 0
        self.dropped_types = 0
        self.streamed = 0

    def keeps_file(self, file_: Optional[str]) -> bool:
        # None means the node's location could not be resolved at all (e.g. a
        # structural wrapper with no context yet) -- keep rather than risk
        # dropping project code on an inheritance-resolution edge case.
        if file_ is None:
            return True
        cached = self._cache.get(file_)
        if cached is None:
            cached = self._cache[file_] = self._decide(file_)
        return cached

    def _decide(self, file_: str) -> bool:
        # Clang records the file passed on the compile command line, and quote-included headers resolved relative to
        # it, as relative paths (of the working directory, which the wrapper shares)
        absolute = file_ if file_.startswith("/") else os.path.join(os.getcwd(), file_)
        if self.excluded and (
            os.path.normpath(absolute).startswith(self.excluded) or os.path.realpath(absolute).startswith(self.excluded)
        ):
            return False
        if self.mapped:
            return os.path.normpath(absolute) in self.mapped or os.path.realpath(absolute) in self.mapped
        # Clang records the file passed on the compile command line, and any
        # quote-included ("...") header resolved relative to it, as a bare or
        # relative path (e.g. "main.cpp", "utils.hpp") -- these are always the
        # project's own files. Angle-bracket (<...>) includes resolved via the
        # system/library search path come back as absolute paths. Both project
        # source passed with an absolute path and project headers pulled in via
        # an absolute -I are covered by the project_root prefix check.
        if not file_.startswith("/"):
            return True
        roots = (self.project_root, self.project_root_real)
        return file_.startswith(roots) or os.path.realpath(file_).startswith(roots)

    def keeps(self, file_: Optional[str], kind: Optional[str]) -> bool:
        if self.prune_types and isinstance(kind, str) and kind.endswith("Type"):
            self.dropped_types += 1
            return False
        if not self.keeps_file(file_):
            self.dropped_unselected += 1
            return False
        self.kept += 1
        return True


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
    children: list[dict[str, Any]], inherited_file: Optional[str], policy: _Policy
) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    ctx_file = inherited_file
    for child in children:
        own_file = _own_file(child, ctx_file)
        if policy.keeps(own_file, child.get("kind")):
            _filter_subtree(child, own_file, policy)
            kept.append(child)
        # The next sibling's inheritance context advances regardless of
        # whether *this* sibling survived the filter.
        ctx_file = own_file
    return kept


def _filter_subtree(node: dict[str, Any], own_file: Optional[str], policy: _Policy) -> None:
    _bake_file(node, own_file)
    children = node.get("inner")
    if children:
        node["inner"] = _filter_children(children, own_file, policy)


class _Writer(Protocol):
    def write(self, text: str, /) -> int: ...


class _CountingWriter:
    """Passes what is written on and counts it (the output is ASCII, so characters are bytes)."""

    def __init__(self, target: _Writer) -> None:
        self.target = target
        self.count = 0

    def write(self, text: str, /) -> int:
        self.count += len(text)
        return self.target.write(text)


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def _size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1000 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1000
    return f"{n:.1f} GB"  # not reached


class _Status:
    """Status messages of a run (to ``log``, stderr in the command line tool: stdout carries the pruned AST)."""

    PREFIX = "DiscoPoP AST filter: "
    PROGRESS_INTERVAL = 10.0  # seconds; short runs only print the first and the last message

    def __init__(self, log: TextIO, policy: "_Policy", reader: "_Reader", out: _CountingWriter) -> None:
        self.log = log
        self.policy = policy
        self.reader = reader
        self.out = out
        self.started = time.monotonic()
        self.last_progress = self.started

    def _say(self, text: str) -> None:
        print(self.PREFIX + text, file=self.log, flush=True)

    def _dropped(self) -> str:
        return (
            f"dropped {_plural(self.policy.dropped_unselected, 'subtree')} outside the "
            f"{'mapped files' if self.policy.mapped else 'project directory'}, "
            f"{_plural(self.policy.dropped_types, 'type node')}"
        )

    def start(self) -> None:
        policy = self.policy
        if policy.mapped:
            selection = (
                f"keeping the declarations of the {_plural(policy.mapped_files, 'file')} of {policy.file_mapping}"
            )
        elif policy.file_mapping:
            selection = (
                f"{policy.file_mapping} is missing or empty (no files are mapped yet), keeping the declarations "
                f"below {policy.project_root}"
            )
        else:
            selection = f"no file mapping given, keeping the declarations below {policy.project_root}"
        if policy.excluded_dirs:
            selection += f", without the excluded directories {policy.excluded_dirs}"
        self._say(selection + ("; type nodes are dropped" if policy.prune_types else "; type nodes are kept"))

    def progress(self) -> None:
        now = time.monotonic()
        if now - self.last_progress < self.PROGRESS_INTERVAL:
            return
        self.last_progress = now
        elapsed = now - self.started
        read = self.reader.chars_read
        self._say(
            f"{elapsed:.0f} s: read {_size(read)} ({_size(read / elapsed)}/s), wrote {_size(self.out.count)}, "
            f"kept {_plural(self.policy.kept, 'node')}, {self._dropped()}"
        )

    def finish(self) -> None:
        self._say(
            f"done in {time.monotonic() - self.started:.1f} s: read {_size(self.reader.chars_read)}, "
            f"wrote {_size(self.out.count)}, kept {_plural(self.policy.kept, 'node')}, {self._dropped()}; "
            f"{_plural(self.policy.streamed, 'large declaration')} read member by member"
        )


class _Reader:
    """Incremental reader that decodes JSON values from a text stream without reading it all at once."""

    _MIN_CHUNK = 1 << 20

    def __init__(self, source: TextIO) -> None:
        self.source = source
        self.chars_read = 0
        # called after every read of the source (the status messages hook in here)
        self.on_read: Optional[Callable[[], None]] = None
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
        self.chars_read += len(chunk)
        self.buf = self.buf[self.pos :] + chunk
        self.pos = 0
        if self.on_read is not None:
            self.on_read()
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


def _stream_children(reader: _Reader, out: _Writer, policy: _Policy, ctx_file: Optional[str], emit: bool) -> None:
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
            policy.streamed += 1
            own_file, wrote = _stream_object(reader, out, policy, ctx_file, emit, sep)
        else:
            own_file = _own_file(child, ctx_file)
            wrote = emit and policy.keeps(own_file, child.get("kind"))
            if wrote:
                _filter_subtree(child, own_file, policy)
                out.write(sep + json.dumps(child))
            del child
        if wrote:
            first = False
        # the next sibling's inheritance context advances regardless of whether this one survived
        ctx_file = own_file


def _stream_object(
    reader: _Reader, out: _Writer, policy: _Policy, ctx_file: Optional[str], emit: bool, sep: str
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
            keep = emit and policy.keeps(own_file, members.get("kind"))
            if keep:
                _bake_file(members, own_file)
                out.write(sep + (json.dumps(members)[:-1] + ", " if members else "{") + '"inner": [')
            reader.pos += 1  # "["
            _stream_children(reader, out, policy, own_file, keep)
            if keep:
                out.write("]")
        else:
            (after_inner if seen_inner else members)[key] = reader.decode_value()
    if not seen_inner:
        own_file = _own_file(members, ctx_file)
        keep = emit and policy.keeps(own_file, members.get("kind"))
        if keep:
            _bake_file(members, own_file)
            out.write(sep + json.dumps(members))
    elif keep:
        out.write((", " + json.dumps(after_inner)[1:-1] if after_inner else "") + "}")
    return own_file, keep


def filter_ast_stream(source: TextIO, out: _Writer, policy: _Policy, log: Optional[TextIO] = None) -> None:
    """Prune one or more concatenated top-level JSON objects read from ``source`` and write them to ``out``.

    A declaration is held in memory as a whole only if it is small (``_MAX_DECODE``); larger ones are read member by
    member, so the memory needed does not depend on the size of the (unfiltered) dump or of any declaration.
    Status messages go to ``log`` if one is given.
    """
    # type trees nest deeply, and the pruning of a decoded declaration recurses over them
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 20000))
    reader = _Reader(source)
    counted_out = _CountingWriter(out)
    status = _Status(log, policy, reader, counted_out) if log is not None else None
    if status is not None:
        status.start()
        reader.on_read = status.progress
    first = True
    while (ch := reader.skip_ws()) is not None:
        if ch != "{":
            raise ValueError("malformed AST dump: a top-level value is not an object")
        if not first:
            counted_out.write("\n")
        first = False
        _stream_object(reader, counted_out, policy, None, True, "")
    if status is not None:
        status.finish()


def filter_ast_dump(
    text: str,
    project_root: str,
    file_mapping: Optional[str] = None,
    prune_types: bool = True,
    excluded_dirs: str = "",
) -> str:
    """Prune one or more concatenated top-level JSON objects given as a string (see ``filter_ast_stream``).

    Concatenated objects occur when multiple translation units are dumped
    into the same file (one clang invocation per source file, appended).
    """
    out = io.StringIO()
    filter_ast_stream(io.StringIO(text), out, _Policy(project_root, file_mapping, prune_types, excluded_dirs))
    return out.getvalue()


def main() -> None:
    args = sys.argv[1:]
    if len(args) not in (1, 2):
        print(f"usage: {sys.argv[0]} <project_root> [<FileMapping.txt>]", file=sys.stderr)
        sys.exit(1)

    # DP_AST_QUIET=1 silences the status messages (they go to stderr: stdout is the pruned AST)
    log = None if os.environ.get("DP_AST_QUIET") else sys.stderr
    # the directories the LLVM pass does not count as part of the project either
    excluded_dirs = os.environ.get("DP_PROJECT_EXCLUDE_DIRS", "")
    policy = _Policy(args[0], args[1] if len(args) == 2 else None, excluded_dirs=excluded_dirs)
    filter_ast_stream(sys.stdin, sys.stdout, policy, log)


if __name__ == "__main__":
    main()

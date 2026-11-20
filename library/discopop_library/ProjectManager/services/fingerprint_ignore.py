# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The files of the project that do not decide whether a build is current, e.g. a build directory inside it.

The fingerprint of a build (``configurations/builds.py``) covers every file of the project that git knows or does not
ignore. A build directory of the project's own build system that is not listed in ``.gitignore`` (``dp_build/`` of a
compile script that builds in place, for example) therefore makes every build stale as soon as something is compiled
in the project directory itself. The patterns stored here leave such files out of the fingerprint.

Stored in ``.discopop/project/fingerprint_ignore.json`` (kept by "Reset Project", like the configurations). A pattern
is matched against the path of a file relative to the project directory, ``/`` separated:

- ``dir/`` (trailing ``/``) or a pattern without wildcards: the file itself or everything below that path,
- otherwise a shell wildcard pattern (``fnmatch``: ``*``, ``?``, ``[...]``; ``*`` also matches ``/``) on the whole
  path; a pattern without ``/`` is also matched against the file name alone, as in ``.gitignore`` (``*.log``).

Unlike the excluded directories (``services/excluded_directories.py``), which decide what is instrumented, this list
only decides what the fingerprint looks at: the files are still compiled. Toolkit-free.
"""

import fnmatch
import json
import os
import posixpath
from typing import Iterable, List, Optional, Sequence

FINGERPRINT_IGNORE_FILE = "fingerprint_ignore.json"
_WILDCARDS = ("*", "?", "[")


def fingerprint_ignore_path(project_dir: str) -> str:
    """The file of the list; ``project_dir`` is ``.discopop/project`` (``ProjectManagerArguments.project_dir``)."""
    return os.path.join(project_dir, FINGERPRINT_IGNORE_FILE)


def normalize(pattern: str) -> Optional[str]:
    """``pattern`` as stored: ``/`` separated and stripped, a directory keeps its trailing ``/``; None if it is empty,
    absolute or leaves the project directory."""
    text = pattern.replace(os.sep, "/").strip()
    if not text or text.startswith("/"):
        return None
    directory = text.endswith("/")
    if not any(character in text for character in _WILDCARDS):
        text = posixpath.normpath(text)
        if text in ("", ".") or text == ".." or text.startswith("../"):
            return None
    else:
        text = text.rstrip("/")
    return text + "/" if directory else text


def clean(patterns: Iterable[str]) -> List[str]:
    """``patterns`` normalized, without duplicates, in their order."""
    result: List[str] = []
    for pattern in patterns:
        normalized = normalize(pattern)
        if normalized is not None and normalized not in result:
            result.append(normalized)
    return result


def matches(path: str, pattern: str) -> bool:
    """Whether the file ``path`` (relative, ``/`` separated) is ignored by the normalized ``pattern``."""
    if not any(character in pattern for character in _WILDCARDS):
        prefix = pattern.rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    stripped = pattern.rstrip("/")
    if fnmatch.fnmatchcase(path, stripped) or fnmatch.fnmatchcase(path, stripped + "/*"):
        return True
    if "/" not in stripped:
        # as in .gitignore: a name pattern matches in every directory, a directory name everything below it
        segments = path.split("/")
        return any(fnmatch.fnmatchcase(segment, stripped) for segment in segments)
    return False


def is_ignored(path: str, patterns: Sequence[str]) -> bool:
    return any(matches(path, pattern) for pattern in patterns)


def load_fingerprint_ignore(project_dir: str) -> List[str]:
    """The stored patterns; empty if there are none or they cannot be read (an unreadable file must not stop a
    build: it only makes builds stale more often)."""
    try:
        with open(fingerprint_ignore_path(project_dir), "r") as file:
            content = json.load(file)
    except (OSError, ValueError):
        return []
    entries = content.get("patterns") if isinstance(content, dict) else None
    if not isinstance(entries, list):
        return []
    return clean(entry for entry in entries if isinstance(entry, str))


def save_fingerprint_ignore(project_dir: str, patterns: Sequence[str]) -> List[str]:
    """Store ``patterns`` (cleaned) and return what was stored."""
    stored = clean(patterns)
    os.makedirs(project_dir, exist_ok=True)
    path = fingerprint_ignore_path(project_dir)
    temporary = path + ".tmp"
    with open(temporary, "w") as file:
        json.dump({"patterns": stored}, file, indent=2)
        file.write("\n")
    os.replace(temporary, path)
    return stored


def add_patterns(project_dir: str, patterns: Sequence[str]) -> List[str]:
    """Add ``patterns`` to the stored ones; returns the stored list."""
    return save_fingerprint_ignore(project_dir, load_fingerprint_ignore(project_dir) + list(patterns))


def suggest_patterns(paths: Sequence[str]) -> List[str]:
    """Patterns that would ignore the changed files ``paths``: the top-level directories they lie in (``dp_build/``)
    and the top-level files themselves. Meant as a proposal the user confirms, not to be stored unseen."""
    suggestions: List[str] = []
    for path in paths:
        head, separator, _rest = path.partition("/")
        suggestion = head + "/" if separator else head
        if suggestion not in suggestions:
            suggestions.append(suggestion)
    return suggestions

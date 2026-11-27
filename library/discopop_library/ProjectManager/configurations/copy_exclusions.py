# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What a copy of the project leaves out: configured build directories, and the paths the project lists.

A copy of the project (a build tree, a candidate of the autotuner) is compiled at another path than the project.
A build directory configured in the project does not work there: CMake stores the absolute source and build
directories in ``CMakeCache.txt``, so ``cmake ..`` in the copy stops (``CMakeCache.txt directory ... is different``),
and ``make`` in the copy silently builds and links the *project's* sources into the *project's* build directory --
the copy's patched sources are never compiled. Compile scripts only escape this as long as they delete their build
directory first. The copy therefore leaves such directories out:

- a directory holding a ``CMakeCache.txt`` of an out-of-source build (its ``CMAKE_HOME_DIRECTORY`` is another
  existing directory): the whole directory
- an in-source CMake build (``CMAKE_HOME_DIRECTORY`` is the directory itself, does not exist or is unreadable): only
  ``CMakeCache.txt`` and ``CMakeFiles``, so that the sources next to them are copied
- a meson build directory (``meson-private``; meson builds out of source only): the whole directory
- an autotools build directory outside the sources (``config.status`` and ``config.log`` without a ``configure`` next
  to them): the whole directory; an in-source autotools build is copied, its scripts configure again anyway

Build systems that leave no such marker are covered by the project's own list (``services/copy_exclude.py``).

Toolkit-free.
"""

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set

PATH = str

CMAKE_CACHE = "CMakeCache.txt"
CMAKE_FILES = "CMakeFiles"
MESON_PRIVATE = "meson-private"
AUTOTOOLS_STATUS = "config.status"
AUTOTOOLS_CONFIGURE = "configure"
AUTOTOOLS_LOG = "config.log"
_CMAKE_HOME_KEY = "CMAKE_HOME_DIRECTORY:INTERNAL="


def _cmake_home_of(cache_file: PATH) -> Optional[PATH]:
    """The source directory a ``CMakeCache.txt`` was configured for, None if it cannot be read."""
    try:
        with open(cache_file, "r", errors="replace") as file:
            for line in file:
                if line.startswith(_CMAKE_HOME_KEY):
                    return line[len(_CMAKE_HOME_KEY) :].strip()
    except OSError:
        return None
    return None


def _same_directory(first: PATH, second: PATH) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return os.path.realpath(first) == os.path.realpath(second)


WHOLE = "whole"
IN_SOURCE = "in_source"


def build_directory_kind(directory: PATH) -> Optional[str]:
    """How ``directory`` belongs to a configured build: :data:`WHOLE` (an out-of-source build directory, left out as
    a whole), :data:`IN_SOURCE` (an in-source CMake configuration: only ``CMakeCache.txt`` and ``CMakeFiles`` are left
    out) or None. The one rule for the copies and the build fingerprint; see the module docstring."""
    cache = os.path.join(directory, CMAKE_CACHE)
    if os.path.isfile(cache):
        home = _cmake_home_of(cache)
        # out of source only if the sources it was configured for exist elsewhere: a tree that was moved or copied
        # by hand has a home that does not exist any more, and may well hold sources next to its cache
        if home is not None and os.path.isdir(home) and not _same_directory(home, directory):
            return WHOLE
        return IN_SOURCE
    if os.path.isdir(os.path.join(directory, MESON_PRIVATE)):
        return WHOLE
    if (
        os.path.isfile(os.path.join(directory, AUTOTOOLS_STATUS))
        and os.path.isfile(os.path.join(directory, AUTOTOOLS_LOG))
        and not os.path.exists(os.path.join(directory, AUTOTOOLS_CONFIGURE))
    ):
        return WHOLE
    return None


def is_build_directory(directory: PATH) -> bool:
    """Whether ``directory`` as a whole is a configured build directory (out of source); see the module docstring."""
    return build_directory_kind(directory) == WHOLE


def in_source_build_files(directory: PATH, names: Sequence[str]) -> List[str]:
    """The names of ``directory`` that belong to an in-source CMake configuration (``CMakeCache.txt`` and
    ``CMakeFiles``); empty unless the directory holds a ``CMakeCache.txt`` and is not left out as a whole."""
    if CMAKE_CACHE not in names or build_directory_kind(directory) != IN_SOURCE:
        return []
    return [name for name in (CMAKE_CACHE, CMAKE_FILES) if name in names]


# the file names whose presence makes a directory a candidate for build_directory_kind (meson: a directory)
_MARKER_FILES = (CMAKE_CACHE, AUTOTOOLS_STATUS)
_MESON_COMPONENT = "/" + MESON_PRIVATE + "/"


def left_out_paths(root: PATH, names: Iterable[str], listed: Sequence[str] = ()) -> List[str]:
    """The paths (relative to ``root``, ``/`` separated) a copy of ``root`` leaves out, as far as they concern the
    files ``names``: configured build directories (or the cache files of in-source ones) and the ``listed`` paths
    (``services/copy_exclude.py``).

    The candidates are found from the names alone (a ``CMakeCache.txt`` or ``config.status`` file, a
    ``meson-private`` directory), so that no walk of the project is needed; they are classified on disk by
    :func:`build_directory_kind`, as in the copy. The root itself is never left out as a whole.
    """
    candidates: Set[str] = set()
    for name in names:
        directory, _, base = name.rpartition("/")
        if base in _MARKER_FILES:
            candidates.add(directory)
        position = ("/" + name).find(_MESON_COMPONENT)
        if position >= 0:
            candidates.add(name[: max(position - 1, 0)] if position else "")
    whole: Set[str] = set()
    left_out: List[str] = []
    for directory in sorted(candidates, key=lambda d: (d.count("/"), d)):
        if directory and _has_prefix_in(directory, whole):
            continue
        kind = build_directory_kind(os.path.join(root, directory) if directory else root)
        prefix = directory + "/" if directory else ""
        if kind == WHOLE and directory:
            whole.add(directory)
            left_out.append(directory)
        elif kind == IN_SOURCE:
            left_out.extend((prefix + CMAKE_CACHE, prefix + CMAKE_FILES))
    return left_out + [path for path in listed if path not in left_out]


def _has_prefix_in(path: str, prefixes: Set[str]) -> bool:
    """Whether ``path`` or one of its parent directories is in ``prefixes``."""
    while path:
        if path in prefixes:
            return True
        path = path.rpartition("/")[0]
    return False


def drop_below(entries: Dict[str, Any], paths: Iterable[str]) -> Dict[str, Any]:
    """``entries`` without the files at or below one of ``paths``."""
    prefixes = set(paths)
    if not prefixes:
        return entries
    return {name: value for name, value in entries.items() if not _has_prefix_in(name, prefixes)}


def without_left_out(root: PATH, entries: Dict[str, Any], listed: Sequence[str] = ()) -> Dict[str, Any]:
    """``entries`` (files relative to ``root``) without those a copy of ``root`` leaves out
    (:func:`left_out_paths`)."""
    return drop_below(entries, left_out_paths(root, entries, listed))


@dataclass
class CopyExclusions:
    """What a copy of ``root`` leaves out, as relative paths (``/`` separated); filled while copying."""

    root: PATH
    # paths relative to ``root`` that the project lists (``services/copy_exclude.py``), normalized
    listed: Sequence[str] = ()
    # names in the project's ``.discopop`` that are not copied (data of earlier runs, see ``DATA_LEFT_OUT_OF_BUILDS``)
    dot_discopop: Sequence[str] = ()
    # what was left out because it is a configured build directory (or part of an in-source one)
    build_directories: List[str] = field(default_factory=list)
    # what of ``listed`` existed and was left out
    listed_left_out: List[str] = field(default_factory=list)

    def ignore(self) -> Callable[[str, List[str]], List[str]]:
        """An ``ignore`` callable for :func:`shutil.copytree` of ``root``."""
        root = os.path.abspath(self.root)
        dot_discopop = os.path.join(root, ".discopop")
        listed: Set[str] = set(self.listed)

        def ignore(directory: str, names: List[str]) -> List[str]:
            directory = os.path.abspath(directory)
            if directory == dot_discopop:
                return [name for name in names if name in self.dot_discopop]
            relative_dir = os.path.relpath(directory, root)
            prefix = "" if relative_dir == "." else relative_dir.replace(os.sep, "/") + "/"
            left_out: List[str] = []
            for name in names:
                relative = prefix + name
                if relative in listed:
                    left_out.append(name)
                    self.listed_left_out.append(relative)
                    continue
                path = os.path.join(directory, name)
                # a link to a build directory is left out too: the copy follows links (copytree's default)
                if name != ".discopop" and os.path.isdir(path) and is_build_directory(path):
                    left_out.append(name)
                    self.build_directories.append(relative)
            for name in in_source_build_files(directory, names):
                if name not in left_out:
                    left_out.append(name)
                    self.build_directories.append(prefix + name)
            return left_out

        return ignore

    def report(self) -> Optional[str]:
        """One line naming what was left out, None if nothing was."""
        parts = []
        if self.build_directories:
            parts.append(
                "configured build directories (they belong to the project's path): "
                + ", ".join(sorted(self.build_directories))
            )
        if self.listed_left_out:
            parts.append("listed in copy_exclude.json: " + ", ".join(sorted(self.listed_left_out)))
        if not parts:
            return None
        return "Not copied: " + "; ".join(parts) + "."

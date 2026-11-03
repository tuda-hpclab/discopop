# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The single definition of "the sources of a project" and their content fingerprint."""

import hashlib
import os
import threading
from dataclasses import dataclass
from typing import Dict, List, Tuple

SOURCE_SUFFIXES = (".c", ".cc", ".cpp", ".cxx", ".c++", ".h", ".hh", ".hpp", ".hxx")
PRUNED_DIR_NAMES = frozenset({"build", "venv", "__pycache__", "node_modules", "CMakeFiles"})


@dataclass(frozen=True)
class SourceFingerprint:
    digest: str  # "sha256:<hex>"
    files: Dict[str, str]  # relative path -> "sha256:<hex>" of the content


def _is_pruned(dirpath: str, name: str) -> bool:
    if name.startswith(".") or name in PRUNED_DIR_NAMES:
        return True
    # a CMake build tree under another name
    return os.path.isfile(os.path.join(dirpath, name, "CMakeCache.txt"))


def source_files(project_root: str) -> List[str]:
    """Relative POSIX paths of the source files below project_root, sorted."""
    found: List[str] = []
    root = os.path.abspath(project_root)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _is_pruned(dirpath, d)]
        for name in filenames:
            if name.lower().endswith(SOURCE_SUFFIXES):
                rel = os.path.relpath(os.path.join(dirpath, name), root)
                found.append(rel.replace(os.sep, "/"))
    return sorted(found)


# {abs_path: (st_mtime_ns, st_size, filehash)}; the mtime is only a cache key, never a decision
_HASH_CACHE: Dict[str, Tuple[int, int, str]] = {}
_CACHE_LOCK = threading.Lock()


def _hash_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _file_hash_cached(path: str) -> str:
    st = os.stat(path)
    key = (st.st_mtime_ns, st.st_size)
    with _CACHE_LOCK:
        cached = _HASH_CACHE.get(path)
    if cached is not None and cached[:2] == key:
        return cached[2]
    value = _hash_file(path)
    with _CACHE_LOCK:
        _HASH_CACHE[path] = (key[0], key[1], value)
    return value


def source_fingerprint(project_root: str) -> SourceFingerprint:
    root = os.path.abspath(project_root)
    files: Dict[str, str] = {}
    for rel in source_files(root):
        try:
            files[rel] = _file_hash_cached(os.path.join(root, rel))
        except OSError:
            continue  # removed while walking
    outer = hashlib.sha256()
    for rel in sorted(files):
        outer.update(f"{rel}\0{files[rel]}\n".encode("utf-8"))
    return SourceFingerprint(digest="sha256:" + outer.hexdigest(), files=files)


def changed_files(old: Dict[str, str], new: Dict[str, str]) -> List[str]:
    """Added, removed and modified files between two file->hash maps, sorted."""
    return sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p))

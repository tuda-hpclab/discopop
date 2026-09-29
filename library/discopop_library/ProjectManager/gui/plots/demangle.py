# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Demangle C++ symbol names for display.

The hotspot instrumentation pass records ``Function::getName()`` into
``cs_id.txt``, which for C++ is the mangled symbol (``_Z5heavyi``). That is
exactly what a region key should be built from -- it is stable and unambiguous --
but it is unreadable in a table, so the *display* layers run it through this
module first.

Demangling is delegated to whichever of ``llvm-cxxfilt`` / ``c++filt`` is on PATH
(both pass non-mangled input through unchanged) and every result is cached for the
life of the process, since the same handful of names is re-rendered on every
refresh. With no demangler available, or if it fails, names are shown as-is: an
unreadable name is a far better outcome than a broken panel.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Dict, Iterable, List, Optional

# Candidate demanglers, in preference order.
_DEMANGLERS = ("llvm-cxxfilt", "c++filt")

# The Itanium C++ ABI prefix. Names without it are not mangled, so they need no
# subprocess at all -- which is the common case for C projects.
_MANGLED_PREFIX = "_Z"

_cache: Dict[str, str] = {}


def _find_demangler() -> Optional[str]:
    for candidate in _DEMANGLERS:
        path = shutil.which(candidate)
        if path is not None:
            return path
    return None


def prefetch(names: Iterable[str]) -> None:
    """Demangle every not-yet-cached mangled name in ``names`` in one batch.

    Call this once per refresh before rendering, so a table of many regions costs
    a single subprocess rather than one per row.
    """
    pending: List[str] = []
    seen = set()
    for name in names:
        if not name.startswith(_MANGLED_PREFIX) or name in _cache or name in seen:
            continue
        seen.add(name)
        pending.append(name)
    if not pending:
        return

    demangler = _find_demangler()
    if demangler is None:
        # Remember the identity mapping so we do not retry the lookup per render.
        for name in pending:
            _cache[name] = name
        return

    try:
        completed = subprocess.run(
            [demangler],
            input="\n".join(pending) + "\n",
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        for name in pending:
            _cache[name] = name
        return

    lines = completed.stdout.splitlines()
    for index, name in enumerate(pending):
        demangled = lines[index].strip() if index < len(lines) else ""
        _cache[name] = demangled or name


def demangle(name: str) -> str:
    """A readable form of ``name``; the input itself if it is not mangled."""
    if not name.startswith(_MANGLED_PREFIX):
        return name
    if name not in _cache:
        prefetch([name])
    return _cache.get(name, name)

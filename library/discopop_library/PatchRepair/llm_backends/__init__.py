# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The registry of LLM backends -- the coding agents a repair can be asked through.

A declarative table the CLI and the GUI both read, so the two cannot drift from each
other. Each backend is an adapter module fulfilling the contract documented in
``base.py``; everything that is *not* agent-specific -- running the process, the
timeout, extracting the answer -- lives in ``base.py`` and is re-exported here, so a
caller needs this one import.
"""

from typing import Any, Dict, List, Optional

from discopop_library.PatchRepair.llm_backends import claude, opencode
from discopop_library.PatchRepair.llm_backends.base import (
    RESERVED_KEYS,
    FieldSpec,
    Invocation,
    check_fields,
    run_agent,
)

__all__ = [
    "BACKENDS",
    "DEFAULT_BACKEND",
    "FieldSpec",
    "Invocation",
    "RESERVED_KEYS",
    "available_backends",
    "backend_descriptions",
    "backend_of",
    "fields_of",
    "first_installed_backend",
    "get",
    "for_profile",
    "resolve_options",
    "run_agent",
    "stored_options",
    "unknown_backends",
]

# name -> adapter module. Registration order is display order.
BACKENDS = {
    opencode.NAME: opencode,
    claude.NAME: claude,
}

# A backend field that shadowed a shared connection key would silently pick up the
# wrong value, so the clash is refused at import rather than at the first run that
# hits it.
for _backend in BACKENDS.values():
    check_fields(_backend)
del _backend

DEFAULT_BACKEND = opencode.NAME


def available_backends() -> List[str]:
    """Every registered backend name, in display order.

    "Available" as in "DiscoPoP knows how to drive it" -- not as in "its binary is
    installed". Whether it can actually be run is ``get(name).available()``, which is a
    probe and belongs where its outcome can be reported to the user.
    """
    return list(BACKENDS)


def get(name: Optional[str]) -> Any:
    """The adapter module for ``name``, defaulting when it is empty.

    Raises KeyError for an unknown backend, so a configuration naming one that was
    renamed or removed fails loudly rather than silently using a different agent than
    the one that was asked for.
    """
    return BACKENDS[str(name or DEFAULT_BACKEND)]


def first_installed_backend() -> Optional[str]:
    """The first registered backend whose binary can actually be run, or None.

    What ``--backend`` defaults to: on a machine with exactly one agent installed,
    which is the common case, nothing has to be configured at all.
    """
    for name, module in BACKENDS.items():
        if module.available():
            return name
    return None


def backend_of(profile: Dict[str, Any]) -> str:
    """The backend name a connection uses."""
    return str((profile or {}).get("backend") or DEFAULT_BACKEND)


def for_profile(profile: Dict[str, Any]) -> Any:
    """The adapter module a connection is driven through."""
    return get(backend_of(profile))


def unknown_backends(names: Any) -> List[str]:
    """Requested backend names that are not registered."""
    return sorted({str(n) for n in names if str(n) not in BACKENDS})


def fields_of(name: Optional[str]) -> List[FieldSpec]:
    """The backend-specific settings ``name`` understands."""
    try:
        return list(get(name).FIELDS)
    except KeyError:
        return []


def resolve_options(profile: Dict[str, Any], defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The backend-specific settings of ``profile``, every declared field filled in.

    Four layers, most specific first:

    1. what the connection stores under ``backend_options``;
    2. what it stores at the *top* level, i.e. an explicit per-connection value
       written next to the shared settings;
    3. ``defaults``, the backend-wide defaults from the configuration's ``backends``
       section, so a value that is the same for every connection through one agent is
       written once;
    4. the field's own default.

    A stored key the backend no longer declares is kept rather than dropped: a setting
    that stops being understood is worth seeing in the file instead of vanishing on the
    next save.
    """
    stored = dict(profile.get("backend_options") or {})
    fallback = dict(defaults or {})
    resolved: Dict[str, Any] = {}
    for spec in fields_of(profile.get("backend")):
        if spec.key in stored:
            resolved[spec.key] = stored[spec.key]
        elif spec.key in profile:
            resolved[spec.key] = profile[spec.key]
        elif spec.key in fallback:
            resolved[spec.key] = fallback[spec.key]
        else:
            resolved[spec.key] = spec.default
    for key, value in stored.items():
        resolved.setdefault(key, value)
    return resolved


def stored_options(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Only the backend settings the connection itself sets -- no defaults filled in.

    The counterpart of :func:`resolve_options`, for an editor: it has to show what was
    *decided* here, because a blank field means "inherit" and a field prefilled with an
    inherited value would silently freeze it into the connection on the next save.
    """
    stored = dict(profile.get("backend_options") or {})
    for spec in fields_of(profile.get("backend")):
        if spec.key not in stored and spec.key in profile:
            stored[spec.key] = profile[spec.key]
    return stored


def backend_descriptions() -> Dict[str, str]:
    """``{name: description}`` for a selector's mouse-over text."""
    return {name: str(getattr(module, "DESCRIPTION", "") or "") for name, module in BACKENDS.items()}

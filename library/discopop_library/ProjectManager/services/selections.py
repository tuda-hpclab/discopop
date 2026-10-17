# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Selections of suggestion ids: the ``1,3,5-8`` syntax and the persisted de-selection per selector."""

import json
import os
from typing import Any, Dict, Iterable, List, Set

from discopop_library.ProjectManager.services.patches import sort_suggestion_ids


def parse_id_ranges(spec: str, available: List[str]) -> Set[str]:
    """Parse a ``1,3,5-8`` style spec into the set of matching available IDs.

    Tokens that don't resolve to an available ID (bad syntax, out of range) are
    silently ignored so a typo never raises. ``a-b`` with ``a > b`` is treated
    as the same range as ``b-a``.
    """
    available_set = set(available)
    result: Set[str] = set()
    for raw in spec.split(","):
        token = raw.strip()
        if not token:
            continue
        if "-" in token:
            lo_str, _, hi_str = token.partition("-")
            try:
                lo, hi = int(lo_str), int(hi_str)
            except ValueError:
                continue
            if lo > hi:
                lo, hi = hi, lo
            for value in range(lo, hi + 1):
                candidate = str(value)
                if candidate in available_set:
                    result.add(candidate)
        else:
            if token in available_set:
                result.add(token)
            else:
                # tolerate leading zeros / non-canonical integer spelling
                try:
                    canonical = str(int(token))
                except ValueError:
                    continue
                if canonical in available_set:
                    result.add(canonical)
    return result


def selections_path(dot_dp_path: str) -> str:
    return os.path.join(dot_dp_path, "project", "manager", "suggestion_selections.json")


def _load_all(dot_dp_path: str) -> Dict[str, Any]:
    path = selections_path(dot_dp_path)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def load_deselected(dot_dp_path: str, storage_key: str) -> Set[str]:
    """The ids the user de-selected in the selector stored under ``storage_key``."""
    entry = _load_all(dot_dp_path).get(storage_key, {})
    if isinstance(entry, dict):
        return set(str(s) for s in entry.get("deselected", []))
    return set()


def save_deselected(dot_dp_path: str, storage_key: str, deselected: Iterable[str]) -> None:
    """Store the de-selected ids of one selector, leaving the other selectors' entries as they are."""
    data = _load_all(dot_dp_path)
    data[storage_key] = {"deselected": sort_suggestion_ids(deselected)}
    path = selections_path(dot_dp_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass

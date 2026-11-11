# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the suggestion table of the GUI shows: one row per suggestion, without a toolkit.

The suggestion ids are the directory names below ``<dot_dp>/patch_generator`` (see :mod:`patches`); they equal the
``pattern_id`` of the entry in ``<dot_dp>/explorer/patterns.json`` the patch generator wrote the patches for. The
other columns are read from that entry, ``FileMapping.txt`` and the hotspot results. Whatever is missing or
unreadable leaves the corresponding fields empty; nothing here raises.
"""

import ast
import json
import logging
import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from discopop_library.HostpotLoader.HotspotLoaderArguments import HotspotLoaderArguments
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.hostpot_loader import run as load_hotspots
from discopop_library.HostpotLoader.utilities import get_patterns_by_hotspot_type
from discopop_library.ProjectManager.plots import demangle
from discopop_library.ProjectManager.services.patches import discover_suggestion_ids

logger = logging.getLogger("Suggestions")

# the keys below "patterns" of patterns.json and the short names shown for them
PATTERN_TYPE_NAMES = {
    "do_all": "doall",
    "reduction": "reduction",
    "task": "task",
    "merged_pattern": "merged",
    "optimizer_output": "optimizer",
}

_HOTNESS_NAMES = {HotspotType.YES: "YES", HotspotType.MAYBE: "MAYBE", HotspotType.NO: "NO"}


@dataclass(frozen=True)
class SuggestionInfo:
    id: str  # the name of the patch_generator directory
    pattern_type: str = ""
    file_name: str = ""
    file_path: str = ""
    start_line: int = 0
    end_line: int = 0
    pragma: str = ""
    function: str = ""
    hotness: str = ""  # "YES" / "MAYBE" / "NO", "" if unknown
    variables: Tuple[Tuple[str, str], ...] = ()  # (label, value) of the data sharing clauses that are not empty

    @property
    def location(self) -> str:
        """``file.cpp:20``, or ``""`` if the location is unknown."""
        if not self.file_name or self.start_line <= 0:
            return ""
        return f"{self.file_name}:{self.start_line}"


def _read_json(path: str) -> Optional[Any]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _read_file_mapping(dot_dp: str) -> Dict[int, str]:
    mapping: Dict[int, str] = {}
    try:
        with open(os.path.join(dot_dp, "FileMapping.txt"), "r") as f:
            lines = f.read().splitlines()
    except (OSError, ValueError):
        return mapping
    for line in lines:
        file_id, _, path = line.partition("\t")
        if file_id.strip().isdigit() and path.strip():
            mapping[int(file_id)] = path.strip()
    return mapping


def _read_patterns(dot_dp: str) -> Dict[str, Tuple[str, Dict[str, Any]]]:
    """Map every pattern id (as string) of patterns.json to (pattern type, entry); the first entry of an id wins."""
    data = _read_json(os.path.join(dot_dp, "explorer", "patterns.json"))
    result: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    if not isinstance(data, dict) or not isinstance(data.get("patterns"), dict):
        return result
    for key, entries in data["patterns"].items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):  # entries may be stored as JSON strings
                try:
                    entry = json.loads(entry)
                except ValueError:
                    continue
            if isinstance(entry, dict) and "pattern_id" in entry:
                result.setdefault(str(entry["pattern_id"]), (PATTERN_TYPE_NAMES.get(key, str(key)), entry))
    return result


def _split_location(value: Any) -> Tuple[int, int]:
    """``"<file id>:<line>"`` to (file id, line), (-1, 0) if malformed."""
    try:
        file_id, line = str(value).split(":")[:2]
        return int(file_id), int(line)
    except ValueError:
        return -1, 0


def _as_list(value: Any) -> List[Any]:
    """A list-valued field, which older results stored as the string representation of a list."""
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.startswith("["):
        try:
            parsed = ast.literal_eval(value)
        except (ValueError, SyntaxError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _function_name(entry: Dict[str, Any]) -> str:
    """The first of the ``affected_functions`` (``"<file id>:<line>:<name>"``), without its location."""
    for function in _as_list(entry.get("affected_functions")):
        parts = str(function).split(":", 2)
        if len(parts) == 3 and parts[2]:
            return parts[2]
    return ""


def _attached_hotspot_type(entry: Dict[str, Any]) -> Optional[HotspotType]:
    value = entry.get("hotspot_type")
    try:
        if isinstance(value, str) and not value.isdigit():
            return HotspotType[value.upper()]
        return HotspotType(int(value)) if value is not None else None
    except (KeyError, ValueError, TypeError):
        return None


class _PatternView:
    """The part of a patterns.json entry :func:`get_patterns_by_hotspot_type` reads."""

    def __init__(self, entry: Dict[str, Any]) -> None:
        self.applicable_pattern = True  # it has a patch directory, so it is applicable on its own
        self.standalone_pattern = True
        self.start_line = str(entry.get("start_line", ""))
        self.end_line = str(entry.get("end_line", ""))
        self.hotspot_type = _attached_hotspot_type(entry)


class _PatternStorageView:
    def __init__(self, patterns: Dict[int, _PatternView]) -> None:
        self._patterns = patterns

    def get_pattern_ids(self) -> List[int]:
        return list(self._patterns)

    def get_pattern_from_id(self, pattern_id: int) -> _PatternView:
        return self._patterns[pattern_id]


def _hotness_by_suggestion(dot_dp: str, entries: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """The hotness bucket of each suggestion, classified like the patch repair and the auto-tuner do it.

    Empty without hotspot results. A suggestion no hotspot region matches has no bucket either.
    """
    patterns: Dict[int, _PatternView] = {}
    for suggestion_id, entry in entries.items():
        if suggestion_id.isdigit() and _split_location(entry.get("start_line"))[0] >= 0:
            if _split_location(entry.get("end_line"))[0] >= 0:
                patterns[int(suggestion_id)] = _PatternView(entry)
    if not patterns:
        return {}
    try:
        arguments = HotspotLoaderArguments("WARNING", False, False, dot_dp, True, False, True, True, True)
        hotspot_information = load_hotspots(arguments)
        if not hotspot_information:
            return {}
        by_type = get_patterns_by_hotspot_type(
            SimpleNamespace(patterns=_PatternStorageView(patterns)),  # type: ignore[arg-type]
            hotspot_information,
        )
    except Exception as e:  # corrupt hotspot files must not break the suggestion table
        logger.warning("could not classify the suggestions by hotspot: %s", e)
        return {}
    result: Dict[str, str] = {}
    for hotspot_type in (HotspotType.YES, HotspotType.MAYBE, HotspotType.NO):  # the patch repair's priority
        for pattern_id in by_type.get(hotspot_type, []):
            result.setdefault(str(pattern_id), _HOTNESS_NAMES[hotspot_type])
    return result


def _clause(entry: Dict[str, Any], key: str) -> str:
    return ", ".join(str(item) for item in _as_list(entry.get(key)))


def load_suggestions(dot_dp: str) -> List[SuggestionInfo]:
    """One :class:`SuggestionInfo` per suggestion with patches, ordered like ``discover_suggestion_ids``."""
    ids = discover_suggestion_ids(dot_dp)
    if not ids:
        return []
    patterns = _read_patterns(dot_dp)
    file_mapping = _read_file_mapping(dot_dp)
    entries = {suggestion_id: patterns[suggestion_id][1] for suggestion_id in ids if suggestion_id in patterns}
    hotness = _hotness_by_suggestion(dot_dp, entries)

    raw_functions = {suggestion_id: _function_name(entry) for suggestion_id, entry in entries.items()}
    demangle.prefetch(name for name in raw_functions.values() if name)

    infos: List[SuggestionInfo] = []
    for suggestion_id in ids:
        if suggestion_id not in patterns:
            infos.append(SuggestionInfo(id=suggestion_id))
            continue
        pattern_type, entry = patterns[suggestion_id]
        file_id, start_line = _split_location(entry.get("start_line"))
        end_line = _split_location(entry.get("end_line"))[1]
        file_path = file_mapping.get(file_id, "")
        variables = tuple(
            (label, text)
            for label, key in (
                ("Private", "private"),
                ("First private", "first_private"),
                ("Last private", "last_private"),
                ("Shared", "shared"),
                ("Reduction", "reduction"),
            )
            if (text := _clause(entry, key))
        )
        function = raw_functions[suggestion_id]
        infos.append(
            SuggestionInfo(
                id=suggestion_id,
                pattern_type=pattern_type,
                file_name=os.path.basename(file_path),
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                pragma=str(entry.get("pragma") or ""),
                function=demangle.demangle(function) if function else "",
                hotness=hotness.get(suggestion_id, ""),
                variables=variables,
            )
        )
    return infos


def suggestion_detail_fields(info: SuggestionInfo) -> List[Tuple[str, str]]:
    """The (label, value) rows of the detail pane of a suggestion; unknown values are left out."""
    fields: List[Tuple[str, str]] = [("Suggestion", info.id)]
    optional = [
        ("Pattern", info.pattern_type),
        ("File", info.file_path),
        ("Lines", f"{info.start_line}-{info.end_line}" if info.start_line > 0 else ""),
        ("Function", info.function),
        ("Hotness", info.hotness),
        ("Pragma", info.pragma),
    ]
    fields.extend((label, value) for label, value in optional if value)
    fields.extend(info.variables)
    return fields

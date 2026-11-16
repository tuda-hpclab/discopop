# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Pruning of the call path states of the profiler with the results of the hotspot detection.

The LLVM pass can fold the call path states of functions that are not relevant according to ``Hotspots.json`` into
the state of their caller (``profiler/DiscoPoP/static_analysis/hotspot_relevance.hpp``). It only does so if the
environment variable ``DP_CALLPATH_HOTSPOTS`` names that file, so the project manager has to pass it: this module
holds the project's setting (``.discopop/project/callpath_pruning.json``, off by default, edited in the Build stage
of the GUI), decides whether a ``Hotspots.json`` is *current* and builds the variables for an instrumented
(``dp``) build. Toolkit-free.
"""

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from typing import Dict, FrozenSet, Mapping, Optional, Tuple

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.project_environment import (
    INSTRUMENTED_DIRECTORIES_FILE,
    stale_directories_message,
)
from discopop_library.ProjectManager.plots import hotspot_data

CALLPATH_PRUNING_FILE = "callpath_pruning.json"

HOTSPOTS_VARIABLE = "DP_CALLPATH_HOTSPOTS"
HOT_DEPTH_VARIABLE = "DP_CALLPATH_HOT_DEPTH"
UNCLASSIFIED_VARIABLE = "DP_CALLPATH_UNCLASSIFIED"
SEEDS_VARIABLE = "DP_CALLPATH_SEEDS"
HOTNESS_VARIABLE = "DP_CALLPATH_HOTNESS"
VARIABLES = (HOTSPOTS_VARIABLE, HOT_DEPTH_VARIABLE, UNCLASSIFIED_VARIABLE, SEEDS_VARIABLE, HOTNESS_VARIABLE)

HOTNESS_CHOICES = ("yes", "maybe")
UNCLASSIFIED_CHOICES = ("keep", "prune")
SEEDS_CHOICES = ("both", "loops", "functions")
DEFAULT_HOT_DEPTH = 2
MAX_HOT_DEPTH = 50


@dataclass(frozen=True)
class CallpathPruning:
    """The setting: whether the profiler build prunes, and the parameters of the pruning (see
    ``hotspot_relevance.hpp`` for their meaning)."""

    enabled: bool = False
    hot_depth: int = DEFAULT_HOT_DEPTH
    unclassified: str = "keep"
    seeds: str = "both"
    hotness: str = "yes,maybe"


def callpath_pruning_path(project_dir: str) -> str:
    """The file of the setting; ``project_dir`` is ``.discopop/project``."""
    return os.path.join(project_dir, CALLPATH_PRUNING_FILE)


def load_callpath_pruning(project_dir: str) -> CallpathPruning:
    """The stored setting; the default (off) if there is none; invalid fields fall back to their defaults (an
    unreadable file must not stop a build)."""
    default = CallpathPruning()
    try:
        with open(callpath_pruning_path(project_dir), "r") as file:
            content = json.load(file)
    except (OSError, ValueError):
        return default
    if not isinstance(content, dict):
        return default
    depth = content.get("hot_depth")
    unclassified = content.get("unclassified")
    seeds = content.get("seeds")
    hotness = content.get("hotness")
    return CallpathPruning(
        enabled=content.get("enabled") is True,
        hot_depth=(
            depth
            if isinstance(depth, int) and not isinstance(depth, bool) and 0 <= depth <= MAX_HOT_DEPTH
            else default.hot_depth
        ),
        unclassified=unclassified if unclassified in UNCLASSIFIED_CHOICES else default.unclassified,
        seeds=seeds if seeds in SEEDS_CHOICES else default.seeds,
        hotness=hotness if isinstance(hotness, str) and hotness_classes(hotness) else default.hotness,
    )


def save_callpath_pruning(project_dir: str, pruning: CallpathPruning) -> None:
    """Store ``pruning``; the file is only written if the setting changes (its modification time marks results as
    stale for the MCP server)."""
    if load_callpath_pruning(project_dir) == pruning:
        return
    os.makedirs(project_dir, exist_ok=True)
    path = callpath_pruning_path(project_dir)
    temporary = path + ".tmp"
    with open(temporary, "w") as file:
        json.dump(asdict(pruning), file, indent=2)
        file.write("\n")
    os.replace(temporary, path)


# What was read from a Hotspots.json, by (path, modification time, size): the GUI asks after every event, and the
# fingerprint of a build hashes the file.
_file_facts: Dict[Tuple[str, int, int], Tuple[FrozenSet[str], str]] = {}


def hotness_classes(hotness: str) -> FrozenSet[str]:
    """The classes of a ``hotness`` setting (comma separated, as ``DP_CALLPATH_HOTNESS``), lower case."""
    return frozenset(part.strip().lower() for part in hotness.split(",") if part.strip())


def _classes_in(dot_dp: str) -> FrozenSet[str]:
    """The ``hotness`` classes (lower case) the regions of Hotspots.json have; like the hotspot loader, all top-level
    lists count."""
    data = hotspot_data.load_json_file(hotspot_data.hotspots_json_path(dot_dp))
    if data is None:
        return frozenset()
    classes = set()
    for entries in data.values():
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict) and "hotness" in entry:
                    classes.add(str(entry["hotness"]).strip().lower())
    return frozenset(classes)


def _hotspots_facts(dot_dp: str) -> Optional[Tuple[str, FrozenSet[str], str]]:
    """``(path, classes of its regions, content hash)`` of the project's Hotspots.json; None if there is none."""
    path = os.path.abspath(hotspot_data.hotspots_json_path(dot_dp))
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (path, stat.st_mtime_ns, stat.st_size)
    if key not in _file_facts:
        try:
            with open(path, "rb") as file:
                digest = hashlib.sha256(file.read()).hexdigest()
        except OSError:
            return None
        if len(_file_facts) > 32:
            _file_facts.clear()
        _file_facts[key] = (_classes_in(dot_dp), digest)
    return (path, *_file_facts[key])


def current_hotspots_file(arguments: ProjectManagerArguments, config: Optional[str]) -> Optional[str]:
    """The absolute path of ``Hotspots.json`` if it is current, else None.

    Current: it exists, classifies at least one region with one of the configured hotness classes (otherwise there
    is nothing to prune by), was not
    created with other project directories than the stored ones (``stale_directories_message``) and the sources
    did not change since the instrumented build it belongs to (the same rule as the *Hotspot Detection* stage: the
    functions and lines of the file would not fit any more). ``config`` is the configuration whose build is
    compared; without one, the sources are not compared.
    """
    facts = _hotspots_facts(arguments.dot_dp)
    if facts is None or not facts[1] & hotness_classes(load_callpath_pruning(arguments.project_dir).hotness):
        return None
    if stale_directories_message(arguments.dot_dp, "hd", arguments.project_dir) is not None:
        return None
    if config:
        # imported here: the hotspot session needs the builds, which need this module
        from discopop_library.ProjectManager.services.hotspot_build import BUILD_MISMATCH
        from discopop_library.ProjectManager.services.hotspot_session import HotspotSession

        if HotspotSession(arguments).build_state(config)[0] == BUILD_MISMATCH:
            return None
    return facts[0]


def environment(arguments: ProjectManagerArguments, config: Optional[str]) -> Dict[str, str]:
    """The variables a ``dp`` build of ``config`` gets: empty if pruning is off or there is no current
    ``Hotspots.json``."""
    pruning = load_callpath_pruning(arguments.project_dir)
    if not pruning.enabled:
        return {}
    hotspots = current_hotspots_file(arguments, config)
    if hotspots is None:
        return {}
    return {
        HOTSPOTS_VARIABLE: hotspots,
        HOT_DEPTH_VARIABLE: str(pruning.hot_depth),
        UNCLASSIFIED_VARIABLE: pruning.unclassified,
        SEEDS_VARIABLE: pruning.seeds,
        HOTNESS_VARIABLE: pruning.hotness,
    }


def inactive_warning(
    arguments: ProjectManagerArguments, config: Optional[str], *, at_setting: bool = False
) -> Optional[str]:
    """A warning if pruning is off although a current ``Hotspots.json`` exists, else None.

    ``at_setting``: the warning is shown at the setting itself (the GUI section), so it need not say where it is.
    """
    if load_callpath_pruning(arguments.project_dir).enabled or current_hotspots_file(arguments, config) is None:
        return None
    where = "" if at_setting else ' (GUI: Build stage, "Call path pruning")'
    return (
        "Call path pruning is not activated although current hotspot detection results exist. Activating it"
        + where
        + " folds the call path states of functions without hotspots, which makes profiling faster and the data "
        "smaller; it takes effect with the next profiling build."
    )


def no_hotspots_warning(arguments: ProjectManagerArguments, config: Optional[str]) -> Optional[str]:
    """A warning if pruning is on but there is no current ``Hotspots.json`` to prune with, else None."""
    if not load_callpath_pruning(arguments.project_dir).enabled or current_hotspots_file(arguments, config):
        return None
    return (
        "Call path pruning is activated, but there are no current hotspot detection results (none, none that "
        "classifies a region with a configured hotness class, or the sources changed since): the call path states "
        "are not pruned. Run the hotspot detection first."
    )


def state_of(variables: Mapping[str, str], dot_dp: str) -> str:
    """What decides how a build prunes: the variables and the content of the file they name. Part of the
    fingerprint of a ``dp`` build and recorded with the profiling data."""
    hotspots = variables.get(HOTSPOTS_VARIABLE)
    content = ""
    if hotspots is not None:
        facts = _hotspots_facts(dot_dp)
        content = facts[2] if facts is not None and facts[0] == hotspots else "unreadable"
    return json.dumps({"variables": dict(variables), "hotspots": content}, sort_keys=True)


def record_state(dot_discopop: str, state: str) -> None:
    """Note in ``instrumented_project_directories.json`` that the ``dp`` data of ``dot_discopop`` was pruned as
    ``state`` says. Best effort."""
    path = os.path.join(dot_discopop, INSTRUMENTED_DIRECTORIES_FILE)
    try:
        with open(path, "r") as file:
            recorded = json.load(file)
        recorded["dp"]["callpath_pruning"] = state
        with open(path, "w") as file:
            json.dump(recorded, file, indent=2)
    except (OSError, ValueError, KeyError, TypeError):
        pass


def recorded_state(dot_discopop: str) -> Optional[str]:
    """How the ``dp`` data of ``dot_discopop`` was pruned (see :func:`state_of`); None if unknown."""
    try:
        with open(os.path.join(dot_discopop, INSTRUMENTED_DIRECTORIES_FILE), "r") as file:
            state = json.load(file)["dp"]["callpath_pruning"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return state if isinstance(state, str) else None


def stale_message(arguments: ProjectManagerArguments, config: Optional[str]) -> Optional[str]:
    """A message if the profiling data was pruned differently than a build now would (pruning switched, other
    parameters or newer hotspot results); None if it matches or its pruning is unknown (older data)."""
    recorded = recorded_state(arguments.dot_dp)
    if recorded is None:
        return None
    current = state_of(environment(arguments, config), arguments.dot_dp)
    if recorded == current:
        return None
    return (
        "The profiling data was pruned with other call path pruning settings or hotspot results than the current "
        "ones. Profile again to update it."
    )


# printed by the pass (static_analysis/path_enumeration.cpp) once per instrumented module that was pruned
_PRUNED_LINE = re.compile(r"Enumerated (\d+) call path states with hotspot pruning")


def pruning_note(hotspots: str, output: str) -> str:
    """The note for the console after a build that was given ``hotspots`` for pruning: whether the pass pruned
    (from its ``output``) and how many call path states the pruned modules have."""
    counts = [int(count) for count in _PRUNED_LINE.findall(output)]
    if not counts:
        return (
            "Call path pruning was requested with "
            + hotspots
            + ", but the pass did not report any pruned module (the build output may not show it, or no module was "
            "instrumented)."
        )
    return (
        "Call path states were pruned with the hotspot detection results ("
        + hotspots
        + "): "
        + str(len(counts))
        + " module(s), "
        + str(sum(counts))
        + " call path states left."
    )

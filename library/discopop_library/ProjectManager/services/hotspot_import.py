# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Bring the result of a hotspot run in a build into the ``.discopop`` of the project, without a toolkit.

A hotspot run (``configurations/running.py``) writes ``hotspot_result_<N>.txt`` into a run directory of its own, in the
region ids and file ids of its build, and the paths in them are those of the build tree. The accumulated data of the
project (``.discopop/hotspot_detection/private``, ``FileMapping.txt``) is one id space over all builds: a region that
is new gets the next id, a file that is new the next file id, and every run is stored as the next
``hotspot_result_<N>.txt`` in those ids, with the paths of the project in place of those of the build tree. That is
the state the instrumentation in the project directory used to leave, so everything that reads it (the analysis, the
views, the MCP server) is unchanged.
"""

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

from discopop_library.ProjectManager.plots import hotspot_data
from discopop_library.ProjectManager.plots.hotspot_data import RegionKey

PATH = str

_KIND_WORDS = {hotspot_data.KIND_FUNCTION: "func", hotspot_data.KIND_LOOP: "loop"}


@dataclass(frozen=True)
class ImportedRun:
    """A run as stored in the project: its result file number and its runtimes by region key (idle regions left out)."""

    index: int
    regions: Dict[str, float]


def _read(path: PATH) -> str:
    try:
        with open(path, "r") as f:
            return f.read()
    except OSError:
        return ""


def _result_names(private: PATH) -> List[str]:
    try:
        names = os.listdir(private)
    except OSError:
        return []
    return sorted(
        (name for name in names if name.startswith("hotspot_result_") and name.endswith(".txt")),
        key=lambda name: (len(name), name),
    )


def build_region_keys(tree: PATH, root: PATH) -> Dict[int, RegionKey]:
    """The regions the instrumented build in ``tree`` contains, with the paths of the project in ``root``."""
    dot = os.path.join(tree, ".discopop")
    cs_id = hotspot_data.parse_cs_id(_read(os.path.join(dot, "hotspot_detection", "private", "cs_id.txt")))
    mapping = hotspot_data.parse_file_mapping(_read(os.path.join(dot, "FileMapping.txt")).replace(tree, root))
    return hotspot_data.resolve_keys(cs_id, mapping)


def _project_file_ids(dot_dp: PATH, paths: List[str]) -> Dict[str, int]:
    """The file id of every path in the ``FileMapping.txt`` of the project; paths it lacks are appended to it."""
    mapping_path = os.path.join(dot_dp, "FileMapping.txt")
    text = _read(mapping_path)
    mapping = hotspot_data.parse_file_mapping(text)
    by_path: Dict[str, int] = {}
    for fid, path in sorted(mapping.items()):
        by_path.setdefault(path, fid)
    appended = ""
    for path in paths:
        if path in by_path or path.startswith("file_"):
            continue
        fid = max(list(mapping) + [0]) + 1
        mapping[fid] = path
        by_path[path] = fid
        appended += f"{fid}\t{path}\n"
    if appended:
        os.makedirs(dot_dp, exist_ok=True)
        with open(mapping_path, "a") as f:
            if text and not text.endswith("\n"):
                f.write("\n")
            f.write(appended)
    return by_path


def import_run(project_root: PATH, dot_dp: PATH, tree: PATH, run_dot: PATH) -> List[ImportedRun]:
    """Store the result files of the run ``run_dot`` of a build in ``tree`` in the data of the project.

    Returns one :class:`ImportedRun` per result file the run wrote (none if it wrote none, i.e. the program was not
    instrumented).
    """
    root = os.path.abspath(project_root)
    tree = os.path.abspath(tree)
    run_private = os.path.join(os.path.abspath(run_dot), "hotspot_detection", "private")
    names = _result_names(run_private)
    if not names:
        return []

    cs_id = hotspot_data.parse_cs_id(_read(os.path.join(run_private, "cs_id.txt")))
    mapping = hotspot_data.parse_file_mapping(_read(os.path.join(os.path.abspath(run_dot), "FileMapping.txt")))
    mapping = {fid: path.replace(tree, root) for fid, path in mapping.items()}
    keys = hotspot_data.resolve_keys(cs_id, mapping)
    file_ids = _project_file_ids(dot_dp, sorted({key.path for key in keys.values()}))

    private = hotspot_data.private_dir(dot_dp)
    os.makedirs(private, exist_ok=True)
    project_cs_path = hotspot_data.cs_id_path(dot_dp)
    project_cs = hotspot_data.parse_cs_id(_read(project_cs_path))
    known: Dict[Tuple[str, int, int, str], int] = {entry: csid for csid, entry in project_cs.items()}
    next_id = max(list(project_cs) + [0]) + 1
    new_lines = ""
    global_ids: Dict[int, int] = {}
    for csid, key in sorted(keys.items()):
        entry = (key.kind, key.line, file_ids.get(key.path, 0), key.name)
        if entry not in known:
            known[entry] = next_id
            fid = entry[2]
            new_lines += (
                f"{next_id} {_KIND_WORDS[key.kind]} {key.line} {fid} {key.name}\n"
                if key.kind == hotspot_data.KIND_FUNCTION
                else f"{next_id} {_KIND_WORDS[key.kind]} {key.line} {fid}\n"
            )
            next_id += 1
        global_ids[csid] = known[entry]
    if new_lines:
        existing = _read(project_cs_path)
        with open(project_cs_path, "a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(new_lines)

    taken = [index for index in hotspot_data.result_file_indices(private)]
    index = max(taken + [-1]) + 1
    imported: List[ImportedRun] = []
    for name in names:
        runtimes = hotspot_data.parse_hotspot_result(_read(os.path.join(run_private, name)))
        regions: Dict[str, float] = {}
        lines = ""
        for csid, runtime in sorted(runtimes.items()):
            # a region that never ran carries no information (the program writes a row for every region)
            if runtime <= 0 or csid not in global_ids:
                continue
            lines += f"{global_ids[csid]} {runtime:.9f}\n"
            regions[keys[csid].serialize()] = runtime
        with open(os.path.join(private, f"hotspot_result_{index}.txt"), "w") as f:
            f.write(lines)
        imported.append(ImportedRun(index, regions))
        index += 1

    _record_instrumented_directories(os.path.abspath(run_dot), dot_dp)
    return imported


def _record_instrumented_directories(run_dot: PATH, dot_dp: PATH) -> None:
    """Take over which project directories the hotspot data was instrumented with (the stale data warning)."""
    name = "instrumented_project_directories.json"
    try:
        with open(os.path.join(run_dot, name), "r") as f:
            run_entries = json.load(f)
        entry = run_entries["hd"]
    except (OSError, ValueError, KeyError, TypeError):
        return
    path = os.path.join(dot_dp, name)
    try:
        with open(path, "r") as f:
            recorded = json.load(f)
        if not isinstance(recorded, dict):
            recorded = {}
    except (OSError, ValueError):
        recorded = {}
    recorded["hd"] = entry
    try:
        with open(path, "w") as f:
            json.dump(recorded, f, indent=2)
    except OSError:
        pass

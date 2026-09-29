# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Pure data-reduction helpers for the Hotspot Detection tab.

Everything here is free of Tk and matplotlib so it can be unit-tested directly,
mirroring :mod:`discopop_library.ProjectManager.gui.plots.data`.

Three artefacts of the hotspot detection tooling are read:

* ``hotspot_detection/private/cs_id.txt`` -- the code-region id table written by
  the instrumentation pass: ``<id> loop <line> <fid>`` or
  ``<id> func <line> <fid> <name>``.
* ``hotspot_detection/private/hotspot_result_<N>.txt`` -- one profiled run:
  ``<id> <runtime>`` per line.
* ``hotspot_detection/Hotspots.json`` -- the analyzer's output, one entry per
  code region with its per-run runtimes and its ``YES``/``MAYBE``/``NO`` hotness.

Regions are identified by a resolved :class:`RegionKey` (source path, line, kind
and name) rather than by the raw numeric id, because ids are only stable within
one instrumented build. That identity, the parsers for the two raw files, and
the cross-build run merging built on top of them are not GUI concerns and live
in :mod:`discopop_hotspot_analyzer.region_keys`, next to the instrumentation
pass that writes the files; they are re-exported here so this module remains the
single import site for the tab. :func:`region_fingerprint` turns the resolved key
set into a hash the GUI stores alongside its accumulated runs, so a change in
which regions a build contains is detected exactly rather than guessed at from
file mtimes.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from discopop_hotspot_analyzer.region_keys import (  # noqa: F401  (re-exported)
    KIND_FUNCTION,
    KIND_LOOP,
    MERGED_DIRNAME,
    MeasurementRun,
    RegionKey,
    canonical_region_keys,
    collect_runs,
    cs_id_path,
    hotspot_dir,
    invert_file_mapping,
    merged_cs_id_path,
    merged_dir,
    parse_cs_id,
    parse_file_mapping,
    parse_hotspot_result,
    private_dir,
    render_merged_analysis_input,
    resolve_keys,
    result_file_indices,
    write_merged_analysis_input,
)

# Re-exported for the tab's other modules, which import everything hotspot
# related from here. Listed explicitly because the project's mypy configuration
# sets no_implicit_reexport.
__all__ = [
    "KIND_FUNCTION",
    "KIND_LOOP",
    "MERGED_DIRNAME",
    "MeasurementRun",
    "RegionKey",
    "canonical_region_keys",
    "collect_runs",
    "cs_id_path",
    "hotspot_dir",
    "invert_file_mapping",
    "merged_cs_id_path",
    "merged_dir",
    "parse_cs_id",
    "parse_file_mapping",
    "parse_hotspot_result",
    "private_dir",
    "render_merged_analysis_input",
    "resolve_keys",
    "result_file_indices",
    "write_merged_analysis_input",
]

# Hotness values as written by discopop_hotspot_analyzer.
HOTNESS_YES = "YES"
HOTNESS_MAYBE = "MAYBE"
HOTNESS_NO = "NO"
HOTNESS_ORDER = (HOTNESS_YES, HOTNESS_MAYBE, HOTNESS_NO)

# Hotness values the explorer's HotspotLoader keeps (get_YES / get_MAYBE, get_NO=False).
EXPLORER_RELEVANT_HOTNESS = (HOTNESS_YES, HOTNESS_MAYBE)

SIDECAR_FILENAME = "measurement_runs.json"
_FINGERPRINT_PREFIX = "sha1:"


@dataclass
class HotspotRegion:
    """One code region of the analyzer's output, with derived display fields."""

    key: RegionKey
    csid: int
    runtimes: List[float]
    avg: float
    minimum: float
    maximum: float
    ratio: float
    hotness: str
    share: float = 0.0  # avg / sum of all avgs; filled in by parse_hotspots_json


@dataclass
class MeasurementLog:
    """The GUI's sidecar: an instrumented build plus the runs recorded against it."""

    region_fingerprint: Optional[str] = None
    instrumented_at: Optional[str] = None
    compile_script: Optional[str] = None
    runs: List[MeasurementRun] = field(default_factory=list)


# ---------------------------------------------------------------------------
# which regions a build contains
# ---------------------------------------------------------------------------


def region_fingerprint(keys: Iterable[RegionKey]) -> str:
    """A stable hash over a set of region keys.

    Order-independent (the key set is sorted first) so it depends only on which
    regions the build contains, not on the order the pass happened to emit them.
    """
    digest = hashlib.sha1()
    for serialized in sorted(key.serialize() for key in keys):
        digest.update(serialized.encode("utf-8"))
        digest.update(b"\n")
    return _FINGERPRINT_PREFIX + digest.hexdigest()


# ---------------------------------------------------------------------------
# Hotspots.json
# ---------------------------------------------------------------------------


def parse_hotspots_json(data: Dict[str, Any], keys: Dict[int, RegionKey]) -> List[HotspotRegion]:
    """Flatten ``Hotspots.json`` into :class:`HotspotRegion`s, sorted by avg desc.

    ``keys`` resolves ids to source locations. Entries whose id is missing from
    it are still kept, using the ``fid``/``lineNum``/``name`` recorded in the
    JSON itself, so a stale id table degrades the location display rather than
    hiding regions.
    """
    regions: List[HotspotRegion] = []
    for entry in data.get("code_regions", []):
        try:
            csid = int(entry["csid"])
        except (KeyError, TypeError, ValueError):
            continue
        kind = str(entry.get("typ", KIND_LOOP))
        name = str(entry.get("name", ""))
        key = keys.get(csid)
        if key is None:
            key = RegionKey(
                path=f"file_{entry.get('fid', 0)}",
                line=int(entry.get("lineNum", 0)),
                kind=kind,
                name=name,
            )
        runtimes = [float(value) for value in entry.get("runtimes", [])]
        regions.append(
            HotspotRegion(
                key=key,
                csid=csid,
                runtimes=runtimes,
                avg=float(entry.get("avr", 0.0)),
                minimum=float(entry.get("minVal", 0.0)),
                maximum=float(entry.get("maxVal", 0.0)),
                ratio=float(entry.get("ratio", 0.0)),
                hotness=str(entry.get("hotness", HOTNESS_NO)),
            )
        )

    total = sum(region.avg for region in regions)
    if total > 0:
        for region in regions:
            region.share = region.avg / total

    regions.sort(key=lambda region: region.avg, reverse=True)
    return regions


def hotspots_available_for_explorer(dot_dp: str) -> bool:
    """Whether ``Hotspots.json`` holds hotspot information the explorer can use.

    Mirrors :mod:`discopop_library.HostpotLoader`: it reads
    ``hotspot_detection/Hotspots.json`` and keeps only the ``YES``/``MAYBE``
    entries, so a missing file and a file that classifies every region as ``NO``
    are equivalent from the explorer's point of view -- neither restricts the
    analysis. Iterating over all top-level lists rather than ``code_regions``
    alone matches the loader, which does the same.
    """
    data = load_json_file(hotspots_json_path(dot_dp))
    if data is None:
        return False
    for entries in data.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and str(entry.get("hotness", "")) in EXPLORER_RELEVANT_HOTNESS:
                return True
    return False


def quadrant_thresholds(regions: Sequence[HotspotRegion]) -> Tuple[float, float]:
    """The ``(mean(avg), mean(ratio))`` thresholds the analyzer classifies against.

    Reproduces ``hotspot_analyzer.run``'s ``np.mean`` over both metrics so the
    crosshairs drawn on the quadrant chart agree exactly with the hotness labels
    the analyzer already wrote. Returns ``(0.0, 0.0)`` for an empty input.
    """
    if not regions:
        return (0.0, 0.0)
    count = len(regions)
    return (
        sum(region.avg for region in regions) / count,
        sum(region.ratio for region in regions) / count,
    )


def hotness_counts(regions: Iterable[HotspotRegion]) -> Dict[str, int]:
    """Number of regions per hotness value, always covering all three keys."""
    counts = {hotness: 0 for hotness in HOTNESS_ORDER}
    for region in regions:
        if region.hotness in counts:
            counts[region.hotness] += 1
    return counts


def ratio_is_degenerate(regions: Sequence[HotspotRegion]) -> bool:
    """Whether the ``ratio`` criterion carries no information.

    ``ratio = 1/((min/max)+1)`` is exactly ``0.5`` for every region when only a
    single run was profiled, because ``min == max``. The classifier then reduces
    to "average above the mean", and the ratio axis of the quadrant chart is
    meaningless -- the charts say so rather than presenting it as signal.
    """
    if not regions:
        return True
    return all(abs(region.ratio - 0.5) < 1e-9 for region in regions)


# ---------------------------------------------------------------------------
# the GUI's measurement-run sidecar
# ---------------------------------------------------------------------------


def deserialize_log(data: Dict[str, Any]) -> MeasurementLog:
    """Build a :class:`MeasurementLog` from parsed sidecar JSON."""
    runs: List[MeasurementRun] = []
    for entry in data.get("runs", []):
        try:
            index = int(entry["run"])
        except (KeyError, TypeError, ValueError):
            continue
        raw_regions = entry.get("regions", {})
        regions = {str(key): float(value) for key, value in raw_regions.items()}
        runs.append(
            MeasurementRun(
                index=index,
                config=entry.get("config"),
                timestamp=entry.get("ts"),
                time=entry.get("time"),
                code=entry.get("code"),
                regions=regions,
            )
        )
    runs.sort(key=lambda run: run.index)
    return MeasurementLog(
        region_fingerprint=data.get("region_fingerprint"),
        instrumented_at=data.get("instrumented_at"),
        compile_script=data.get("compile_script"),
        runs=runs,
    )


def serialize_log(log: MeasurementLog) -> Dict[str, Any]:
    """Render a :class:`MeasurementLog` as the JSON the sidecar stores."""
    return {
        "region_fingerprint": log.region_fingerprint,
        "instrumented_at": log.instrumented_at,
        "compile_script": log.compile_script,
        "runs": [
            {
                "run": run.index,
                "config": run.config,
                "ts": run.timestamp,
                "time": run.time,
                "code": run.code,
                "regions": run.regions,
            }
            for run in log.runs
        ],
    }


# ---------------------------------------------------------------------------
# reconciling the sidecar with the runs on disk
# ---------------------------------------------------------------------------


def merge_external_runs(log: MeasurementLog, known_indices: Sequence[int]) -> List[MeasurementRun]:
    """The runs present on disk, with unrecorded indices synthesized as external.

    ``known_indices`` are the indices of the ``hotspot_result_*.txt`` files that
    actually exist. Indices the sidecar knows about but which no longer have a
    result file are dropped; indices with a file but no sidecar entry are
    returned as external runs (``config is None``).
    """
    recorded = {run.index: run for run in log.runs}
    merged: List[MeasurementRun] = []
    for index in sorted(set(known_indices)):
        merged.append(recorded.get(index) or MeasurementRun(index=index))
    return merged


# ---------------------------------------------------------------------------
# filesystem layout
# ---------------------------------------------------------------------------


def hotspots_json_path(dot_dp: str) -> str:
    return os.path.join(hotspot_dir(dot_dp), "Hotspots.json")


def sidecar_path(dot_dp: str) -> str:
    return os.path.join(hotspot_dir(dot_dp), SIDECAR_FILENAME)


def load_json_file(path: str) -> Optional[Dict[str, Any]]:
    """Read a JSON object from ``path``, or ``None`` if absent/unreadable.

    Used for both ``Hotspots.json`` and the sidecar: a partially written or
    hand-edited file must degrade the display, never crash the GUI.
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None

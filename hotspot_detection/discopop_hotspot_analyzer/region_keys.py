# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Build-independent identity of profiled code regions, and run merging.

The instrumentation pass numbers code regions per *build*: it appends to
``hotspot_detection/private/cs_id.txt`` and resumes numbering from ``temp.txt``,
so compiling a second time gives the same source region a second id, and the new
binary writes ``0.0`` for every id of the previous build. Region ids are
therefore only meaningful within one build, and joining runs by raw id -- which
is what analyzing ``private/`` directly does -- silently mixes measurements of
different regions.

This matters because a meaningful hotness classification *needs* several runs
with differing inputs: the analyzer's ``ratio`` criterion is derived from a
region's min/max runtime across runs, so with a single run every ratio is 0.5
and hotness degenerates to "above average runtime". Differing inputs generally
mean differing run configurations, which generally mean differing builds.

:class:`RegionKey` (source path, line, kind and name) is stable across builds,
so runs from separately instrumented builds can be combined after all:
:func:`collect_runs` resolves each run's measurements through the current
``cs_id.txt`` into region keys -- dropping the ``0.0`` entries a build writes for
regions it does not contain -- and :func:`write_merged_analysis_input` renumbers
them into one canonical id space the analyzer can read as a single measurement
series.

``fid`` is not usable as a key either: ``FileMapping.txt`` is appended to as
well, so its ids depend on compile order.

Everything here is pure stdlib, so the lightweight hotspot detection package
keeps its dependency footprint. The Project Manager GUI re-exports these names
from :mod:`discopop_library.ProjectManager.gui.plots.hotspot_data`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Code region kinds as written into cs_id.txt / Hotspots.json.
KIND_LOOP = "LOOP"
KIND_FUNCTION = "FUNCTION"

# cs_id.txt spells the kinds in lower case and abbreviates functions.
_CS_ID_KINDS = {"loop": KIND_LOOP, "func": KIND_FUNCTION}

# Directory holding the merged, cross-build analyzer input.
MERGED_DIRNAME = "merged"


@dataclass(frozen=True)
class RegionKey:
    """Identity of a code region that survives re-instrumentation.

    ``name`` is empty for loops (the instrumentation pass records no name for
    them), so loops are identified by ``(path, line)`` and functions
    additionally by their name.
    """

    path: str
    line: int
    kind: str
    name: str = ""

    def serialize(self) -> str:
        """``path:line:KIND[:name]`` -- the form stored in the sidecar."""
        base = f"{self.path}:{self.line}:{self.kind}"
        return f"{base}:{self.name}" if self.name else base

    @staticmethod
    def deserialize(text: str) -> Optional["RegionKey"]:
        """Invert :meth:`serialize`, or ``None`` if ``text`` is not a region key.

        Paths may contain colons, so the split is anchored on the ``KIND`` token
        rather than on a field count: the first ``LOOP``/``FUNCTION`` preceded by
        an integer delimits ``path``, ``line`` and the optional trailing ``name``.
        Scanning left to right resolves the (pathological) case of a function
        whose own name contains ``:LOOP``.
        """
        parts = text.split(":")
        for position in range(1, len(parts)):
            if parts[position] not in (KIND_LOOP, KIND_FUNCTION):
                continue
            try:
                line = int(parts[position - 1])
            except ValueError:
                continue
            return RegionKey(
                path=":".join(parts[: position - 1]),
                line=line,
                kind=parts[position],
                name=":".join(parts[position + 1 :]),
            )
        return None

    @property
    def location(self) -> str:
        """``basename:line``, for display in tables and chart labels."""
        return f"{os.path.basename(self.path)}:{self.line}"

    def display_name(self) -> str:
        """The function name if there is one, else the location."""
        return self.name if self.name else self.location


@dataclass
class MeasurementRun:
    """One accumulated profiling run.

    ``config`` is ``None`` for runs that were not recorded by a caller keeping
    its own log (the Project Manager GUI does; the CLI, the MCP server and the
    benchmark harnesses do not), which are synthesized from the result files on
    disk and displayed as external.
    """

    index: int
    config: Optional[str] = None
    timestamp: Optional[str] = None
    time: Optional[float] = None
    code: Optional[int] = None
    regions: Dict[str, float] = field(default_factory=dict)

    @property
    def is_external(self) -> bool:
        return self.config is None


# ---------------------------------------------------------------------------
# cs_id.txt / hotspot_result_<N>.txt
# ---------------------------------------------------------------------------


def parse_cs_id(text: str) -> Dict[int, Tuple[str, int, int, str]]:
    """Parse ``cs_id.txt`` into ``{id: (kind, line, fid, name)}``.

    Handles both line formats the instrumentation pass writes -- 4 fields for
    loops and 5 for functions -- and skips malformed lines rather than raising,
    since the file is appended to by a compiler pass the reader does not control.

    A later entry for an already-seen id wins: the pass appends without
    truncating, so after a re-instrumentation the newest table is the one that
    matches the current binary.
    """
    regions: Dict[int, Tuple[str, int, int, str]] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 4:
            continue
        kind = _CS_ID_KINDS.get(fields[1])
        if kind is None:
            continue
        try:
            csid = int(fields[0])
            line_number = int(fields[2])
            fid = int(fields[3])
        except ValueError:
            continue
        name = fields[4] if len(fields) > 4 else ""
        regions[csid] = (kind, line_number, fid, name)
    return regions


def parse_file_mapping(text: str) -> Dict[int, str]:
    """Parse ``FileMapping.txt`` (``<fid>\\t<path>`` per line) into ``{fid: path}``.

    Deliberately more tolerant than
    :func:`discopop_library.PathManagement.PathManagement.load_file_mapping`,
    which drops entries whose file no longer exists and warns about them. Here the
    path only identifies a region, so keeping it is strictly better than degrading
    that region to ``file_<fid>``; and the file is appended to by the
    instrumentation pass, so a later duplicate entry for an id wins.
    """
    mapping: Dict[int, str] = {}
    for line in text.splitlines():
        if "\t" not in line:
            continue
        raw_fid, _, path = line.partition("\t")
        path = path.strip()
        if not path:
            continue
        try:
            mapping[int(raw_fid)] = path
        except ValueError:
            continue
    return mapping


def resolve_keys(
    cs_id: Dict[int, Tuple[str, int, int, str]],
    file_mapping: Dict[int, Any],
) -> Dict[int, RegionKey]:
    """Map region ids to :class:`RegionKey`\\ s using a ``FileMapping`` dict.

    ``file_mapping`` is ``{fid: path}`` as returned by
    :func:`discopop_library.PathManagement.PathManagement.load_file_mapping`
    (whose values are ``Path`` objects; anything ``str()``-able works). Ids whose
    ``fid`` is absent from the mapping fall back to ``file_<fid>`` so a region is
    never silently dropped.
    """
    keys: Dict[int, RegionKey] = {}
    for csid, (kind, line_number, fid, name) in cs_id.items():
        mapped = file_mapping.get(fid)
        path = str(mapped) if mapped is not None else f"file_{fid}"
        keys[csid] = RegionKey(path=path, line=line_number, kind=kind, name=name)
    return keys


def parse_hotspot_result(text: str) -> Dict[int, float]:
    """Parse one ``hotspot_result_<N>.txt`` into ``{id: runtime}``."""
    runtimes: Dict[int, float] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 2:
            continue
        try:
            runtimes[int(fields[0])] = float(fields[1])
        except ValueError:
            continue
    return runtimes


# ---------------------------------------------------------------------------
# merging runs across builds
# ---------------------------------------------------------------------------


def invert_file_mapping(file_mapping: Dict[int, Any]) -> Dict[str, int]:
    """``{path: fid}`` from a ``{fid: path}`` mapping, lowest fid winning.

    ``FileMapping.txt`` is appended to by the instrumentation pass, so the same
    path can appear under several ids; the lowest is the one the earliest build
    used and is as good as any for identifying the file downstream.
    """
    inverted: Dict[str, int] = {}
    for fid, path in sorted(file_mapping.items()):
        inverted.setdefault(str(path), fid)
    return inverted


def _fid_for_path(path: str, inverted_mapping: Dict[str, int]) -> int:
    """The ``FileMapping`` id for ``path``, or 0 if it cannot be determined.

    Recognises the ``file_<fid>`` placeholder :func:`resolve_keys` substitutes
    for an unmapped id, so a region resolved against a partial ``FileMapping``
    still reaches the explorer with its original ``fid``.
    """
    fid = inverted_mapping.get(path)
    if fid is not None:
        return fid
    if path.startswith("file_"):
        try:
            return int(path[len("file_") :])
        except ValueError:
            return 0
    return 0


def canonical_region_keys(runs: Sequence[MeasurementRun]) -> List[RegionKey]:
    """The union of the region keys measured by ``runs``, in a stable order.

    This is the id space the merged analysis is expressed in: one entry per
    *source* region rather than per (build, region) pair, which is what lets runs
    from separately instrumented builds be combined at all.
    """
    keys = {
        key
        for run in runs
        for key in (RegionKey.deserialize(serialized) for serialized in run.regions)
        if key is not None
    }
    return sorted(keys, key=lambda key: (key.path, key.line, key.kind, key.name))


def collect_runs(private: str, keys: Dict[int, RegionKey]) -> List[MeasurementRun]:
    """Every ``hotspot_result_<N>.txt`` in ``private``, keyed by region key.

    Measurements of ``0`` are dropped rather than kept as zeroes. A binary emits
    a row for *every* id in ``cs_id.txt``, so after a second build the rows of
    the previous build's ids are all ``0.0``; keeping them would make the
    analyzer treat a region as having run for no time at all (``roundMin``
    rewrites the zero to ``1e-6``, which drives its ratio to ~1.0). Dropping
    them is also what separates the two builds' id ranges from each other, since
    only the ids of the build that produced a run carry a measurement.
    """
    runs: List[MeasurementRun] = []
    for index in result_file_indices(private):
        try:
            with open(os.path.join(private, f"hotspot_result_{index}.txt"), "r") as f:
                text = f.read()
        except OSError:
            continue
        regions: Dict[str, float] = {}
        for csid, runtime in parse_hotspot_result(text).items():
            key = keys.get(csid)
            if key is not None and runtime > 0:
                regions[key.serialize()] = runtime
        if regions:
            runs.append(MeasurementRun(index=index, regions=regions))
    return runs


def write_merged_analysis_input(
    runs: Sequence[MeasurementRun],
    file_mapping: Dict[int, Any],
    dest_dir: str,
) -> int:
    """Render ``runs`` as a single-id-space analyzer input in ``dest_dir``.

    Writes a ``cs_id.txt`` numbering every region of :func:`canonical_region_keys`
    from 1, plus one contiguous ``hotspot_result_<i>.txt`` per run. Regions the
    run did not measure are **omitted** rather than written as ``0.0``: the
    analyzer averages over the lines a region actually has, so omission is what
    makes a region absent from one build count as missing data instead of as a
    zero that collapses its ``min``/``max`` ratio.

    Returns the number of canonical regions written.
    """
    keys = canonical_region_keys(runs)
    ids = {key.serialize(): position + 1 for position, key in enumerate(keys)}
    inverted_mapping = invert_file_mapping(file_mapping)

    os.makedirs(dest_dir, exist_ok=True)
    for stale in os.listdir(dest_dir):
        if stale.startswith("hotspot_result_") and stale.endswith(".txt"):
            os.remove(os.path.join(dest_dir, stale))

    with open(os.path.join(dest_dir, "cs_id.txt"), "w") as f:
        for key in keys:
            fid = _fid_for_path(key.path, inverted_mapping)
            if key.kind == KIND_FUNCTION:
                f.write(f"{ids[key.serialize()]} func {key.line} {fid} {key.name}\n")
            else:
                f.write(f"{ids[key.serialize()]} loop {key.line} {fid}\n")

    for position, run in enumerate(sorted(runs, key=lambda run: run.index)):
        with open(os.path.join(dest_dir, f"hotspot_result_{position}.txt"), "w") as f:
            for serialized, runtime in sorted(run.regions.items()):
                csid = ids.get(serialized)
                if csid is not None:
                    f.write(f"{csid} {runtime:.9f}\n")

    return len(keys)


def render_merged_analysis_input(dot_dp: str) -> Optional[int]:
    """Build the merged analyzer input for ``dot_dp`` from its ``private/`` data.

    Reads ``private/cs_id.txt`` and ``FileMapping.txt``, resolves every result
    file into region keys and writes the renumbered series to ``merged/``.

    Returns the number of canonical regions, or ``None`` if there is nothing to
    merge -- no ``cs_id.txt``, or no run with a single non-zero measurement. The
    caller then falls back to reading ``private/`` directly, which is equivalent
    whenever there is only one build to begin with.
    """
    private = private_dir(dot_dp)
    try:
        with open(cs_id_path(dot_dp), "r") as f:
            cs_id = parse_cs_id(f.read())
    except OSError:
        return None
    if not cs_id:
        return None

    file_mapping: Dict[int, str] = {}
    try:
        with open(os.path.join(dot_dp, "FileMapping.txt"), "r") as f:
            file_mapping = parse_file_mapping(f.read())
    except OSError:
        # Regions then resolve to their "file_<fid>" placeholder, which is still
        # build-independent and round-trips back to the original fid.
        pass

    runs = collect_runs(private, resolve_keys(cs_id, file_mapping))
    if not runs:
        return None
    return write_merged_analysis_input(runs, file_mapping, merged_dir(dot_dp))


# ---------------------------------------------------------------------------
# filesystem layout
# ---------------------------------------------------------------------------


def hotspot_dir(dot_dp: str) -> str:
    return os.path.join(dot_dp, "hotspot_detection")


def private_dir(dot_dp: str) -> str:
    return os.path.join(hotspot_dir(dot_dp), "private")


def merged_dir(dot_dp: str) -> str:
    """Where the cross-build analyzer input is rendered.

    Kept separate from ``private/``, which belongs to the instrumentation pass and
    the runtime: they append to its ``cs_id.txt`` and resume region numbering from
    its ``temp.txt``, so it must not be rewritten.
    """
    return os.path.join(hotspot_dir(dot_dp), MERGED_DIRNAME)


def cs_id_path(dot_dp: str) -> str:
    return os.path.join(private_dir(dot_dp), "cs_id.txt")


def merged_cs_id_path(dot_dp: str) -> str:
    return os.path.join(merged_dir(dot_dp), "cs_id.txt")


def result_file_indices(directory: str) -> List[int]:
    """Indices of the ``hotspot_result_<N>.txt`` files in ``directory``, sorted.

    Note that the analyzer stops at the first missing index, so a gap truncates
    the data it sees; callers listing runs show what is on disk regardless.
    """
    if not os.path.isdir(directory):
        return []
    indices: List[int] = []
    for entry in os.listdir(directory):
        if not (entry.startswith("hotspot_result_") and entry.endswith(".txt")):
            continue
        stem = entry[len("hotspot_result_") : -len(".txt")]
        try:
            indices.append(int(stem))
        except ValueError:
            continue
    return sorted(indices)

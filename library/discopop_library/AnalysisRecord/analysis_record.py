# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The analysis record: which pipeline steps produced the data in a .discopop directory, and for which sources.

Currentness is decided by a content fingerprint of the sources (see sources.py), never by file mtimes. The
only mtime comparison is the legacy fallback for data written before this record existed.
"""

import datetime
import glob
import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from discopop_library.AnalysisRecord.sources import (
    SourceFingerprint,
    changed_files,
    source_files,
    source_fingerprint,
)

logger = logging.getLogger(__name__)

# the definition of "the full pattern detection" for every DiscoPoP tool
DEFAULT_PATTERNS: Tuple[str, ...] = ("doall", "reduction", "task")

RECORD_FILENAME = "analysis_record.json"
RECORD_FORMAT = 1
LEGACY_PROFILED_CONFIGURATIONS = "hotspot_detection/profiled_configurations.json"

STEPS: Tuple[str, ...] = (
    "hotspot_detection",
    "hotspot_analysis",
    "dependence_profiling",
    "pattern_detection",
    "patch_generation",
)

# the steps whose results a step is derived from
UPSTREAM: Dict[str, Tuple[str, ...]] = {
    "hotspot_detection": (),
    "hotspot_analysis": ("hotspot_detection",),
    "dependence_profiling": (),
    "pattern_detection": ("dependence_profiling", "hotspot_analysis"),
    "patch_generation": ("pattern_detection",),
}

# outputs that must exist, relative to the .discopop directory; entries with a wildcard need >= 1 match
OUTPUTS: Dict[str, Tuple[str, ...]] = {
    "hotspot_detection": ("hotspot_detection/private/hotspot_result_*.txt",),
    "hotspot_analysis": ("hotspot_detection/Hotspots.json",),
    "dependence_profiling": ("profiler/Data.xml", "profiler/dynamic_dependencies.txt"),
    "pattern_detection": ("explorer/patterns.json",),
    "patch_generation": ("patch_generator",),
}


@dataclass(frozen=True)
class StepStatus:
    step: str
    state: str  # "missing" | "current" | "stale"
    basis: str  # "fingerprint" | "mtime" (legacy fallback) | "none"
    reason: str
    completed_at: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    changed_files: List[str] = field(default_factory=list)
    run_id: Optional[str] = None  # the recorded run of the step (None without a record)


# ---------------------------------------------------------------- record file


def _d(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _record_path(dot_discopop: str) -> str:
    return os.path.join(dot_discopop, RECORD_FILENAME)


def _normalize_root(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def _default_project_root(dot_discopop: str) -> str:
    return os.path.dirname(os.path.abspath(dot_discopop))


def _read_record(dot_discopop: str) -> Optional[Dict[str, Any]]:
    """The record, or None when absent or unreadable (a warning is logged for the latter)."""
    path = _record_path(dot_discopop)
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("steps"), dict):
            raise ValueError("unexpected structure")
        return data
    except (OSError, ValueError) as e:
        logger.warning("Ignoring unreadable analysis record %s: %s", path, e)
        return None


def _write_record(dot_discopop: str, record: Dict[str, Any]) -> None:
    fd, tmp = tempfile.mkstemp(prefix=RECORD_FILENAME + ".", suffix=".tmp", dir=dot_discopop)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(record, f, indent=2, sort_keys=True)
        os.replace(tmp, _record_path(dot_discopop))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _version() -> str:
    try:
        from discopop_library.global_data.version.utils import get_version

        return get_version()
    except Exception:
        return "unknown"


def _relative_script(compile_script: str, project_root: str) -> str:
    """The compile script relative to the project root when it lies inside it."""
    if not compile_script or not os.path.isabs(compile_script):
        return compile_script
    try:
        rel = os.path.relpath(compile_script, project_root)
    except ValueError:
        return compile_script
    return compile_script if rel.startswith("..") else rel


def _make_entry(
    steps: Dict[str, Any], step: str, params: Dict[str, Any], fingerprint: SourceFingerprint
) -> Dict[str, Any]:
    inputs = {
        up: steps[up]["run_id"] for up in UPSTREAM[step] if isinstance(steps.get(up), dict) and "run_id" in steps[up]
    }
    return {
        "run_id": uuid.uuid4().hex,
        "completed_at": datetime.datetime.now().replace(microsecond=0).isoformat(),
        "discopop_version": _version(),
        "sources": {"digest": fingerprint.digest, "files": dict(fingerprint.files)},
        "params": params,
        "inputs": inputs,
    }


def _load_for_update(dot_discopop: str, root: str) -> Dict[str, Any]:
    record = _read_record(dot_discopop)
    # the project_root is recorded once: steps of another location cannot stay beside new ones
    if record is None or record.get("format") != RECORD_FORMAT or record.get("project_root") != root:
        return {"format": RECORD_FORMAT, "project_root": root, "steps": {}}
    return record


def record_step(dot_discopop: str, step: str, params: Dict[str, Any], project_root: Optional[str] = None) -> None:
    """Record that step finished for the current sources. Never raises."""
    try:
        if step not in STEPS:
            raise ValueError(f"unknown step '{step}'")
        root = _normalize_root(project_root if project_root is not None else _default_project_root(dot_discopop))
        record = _load_for_update(dot_discopop, root)
        steps: Dict[str, Any] = record["steps"]
        params = dict(params)
        if step == "hotspot_analysis" and "configs" not in params:
            detection = steps.get("hotspot_detection")
            if isinstance(detection, dict):
                params["configs"] = sorted(detection.get("params", {}).get("configs", {}))
        steps[step] = _make_entry(steps, step, params, source_fingerprint(root))
        _write_record(dot_discopop, record)
    except Exception as e:
        logger.warning("Could not record step '%s' in %s: %s", step, dot_discopop, e)


def record_hotspot_run(dot_discopop: str, config: str, compile_script: str, project_root: Optional[str] = None) -> None:
    """Record one hotspot detection run; runs on unchanged sources accumulate. Never raises."""
    try:
        root = _normalize_root(project_root if project_root is not None else _default_project_root(dot_discopop))
        record = _load_for_update(dot_discopop, root)
        steps: Dict[str, Any] = record["steps"]
        fingerprint = source_fingerprint(root)
        configs: Dict[str, str] = {}
        previous = steps.get("hotspot_detection")
        if isinstance(previous, dict) and previous.get("sources", {}).get("digest") == fingerprint.digest:
            old = previous.get("params", {}).get("configs", {})
            if isinstance(old, dict):
                configs.update(old)
        configs[config] = _relative_script(compile_script, root)
        steps["hotspot_detection"] = _make_entry(steps, "hotspot_detection", {"configs": configs}, fingerprint)
        _write_record(dot_discopop, record)
    except Exception as e:
        logger.warning("Could not record hotspot run '%s' in %s: %s", config, dot_discopop, e)


def clear_record(dot_discopop: str) -> None:
    """Remove the record file. Never raises."""
    try:
        os.unlink(_record_path(dot_discopop))
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning("Could not remove the analysis record in %s: %s", dot_discopop, e)


def clear_steps(dot_discopop: str, *steps: str) -> None:
    """Forget the given steps, for a caller that deletes their outputs. Never raises.

    Deleting outputs alone is not enough where a step accumulates: a later hotspot run on unchanged sources merges
    into the recorded configurations, which would then claim runs whose data is gone.
    """
    try:
        record = _read_record(dot_discopop)
        if record is None:
            return
        for step in steps:
            record["steps"].pop(step, None)
        _write_record(dot_discopop, record)
    except Exception as e:
        logger.warning("Could not clear steps %s in %s: %s", ", ".join(steps), dot_discopop, e)


# ---------------------------------------------------------------- status


def _output_mtime(dot_discopop: str, step: str) -> Optional[float]:
    """Oldest mtime over the step's outputs; None if any is missing."""
    mtimes: List[float] = []
    for pattern in OUTPUTS[step]:
        matches = glob.glob(os.path.join(glob.escape(dot_discopop), pattern))
        if not matches:
            return None
        try:
            if "*" in pattern:
                mtimes.append(min(os.stat(m).st_mtime for m in matches))
            elif os.path.isdir(matches[0]):
                newest = os.stat(matches[0]).st_mtime
                for dirpath, _dirs, names in os.walk(matches[0]):
                    for n in names:
                        try:
                            newest = max(newest, os.stat(os.path.join(dirpath, n)).st_mtime)
                        except OSError:
                            continue
                mtimes.append(newest)
            else:
                mtimes.append(os.stat(matches[0]).st_mtime)
        except OSError:
            return None
    return min(mtimes)


def _legacy_params(dot_discopop: str, step: str) -> Dict[str, Any]:
    try:
        if step == "pattern_detection":
            with open(os.path.join(dot_discopop, "explorer", "patterns.json")) as f:
                patterns = json.load(f).get("enabled_patterns") or []
            return {"enabled_patterns": sorted(str(p) for p in patterns)}
        if step == "hotspot_detection":
            with open(os.path.join(dot_discopop, LEGACY_PROFILED_CONFIGURATIONS)) as f:
                names = json.load(f)
            if isinstance(names, list):
                return {"configs": {str(n): "" for n in names}}
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return {}


class _Context:
    def __init__(self, dot_discopop: str, project_root: Optional[str]) -> None:
        self.dot = dot_discopop
        self.root = _normalize_root(project_root if project_root is not None else _default_project_root(dot_discopop))
        self.record = _read_record(dot_discopop)
        self._fingerprint: Optional[SourceFingerprint] = None
        self._newest_mtime: Optional[float] = None
        self._newest_done = False

    def fingerprint(self) -> SourceFingerprint:
        if self._fingerprint is None:
            self._fingerprint = source_fingerprint(self.root)
        return self._fingerprint

    def newest_source_mtime(self) -> Optional[float]:
        if not self._newest_done:
            times: List[float] = []
            for rel in source_files(self.root):
                try:
                    times.append(os.stat(os.path.join(self.root, rel)).st_mtime)
                except OSError:
                    continue
            self._newest_mtime = max(times, default=None)
            self._newest_done = True
        return self._newest_mtime


def _describe_changes(files: List[str]) -> str:
    if not files:
        return "the sources changed since the step ran"
    if len(files) == 1:
        return f"{files[0]} changed since the step ran"
    if len(files) <= 3:
        return f"{', '.join(files)} changed since the step ran"
    return f"{', '.join(files[:3])} and {len(files) - 3} more files changed since the step ran"


def _compute(ctx: _Context, step: str, done: Dict[str, StepStatus]) -> StepStatus:
    mtime = _output_mtime(ctx.dot, step)
    if mtime is None:
        return StepStatus(step, "missing", "none", "the step's outputs do not exist")

    entry = ctx.record["steps"].get(step) if ctx.record is not None else None
    if not isinstance(entry, dict):
        # legacy: data from a DiscoPoP predating the record
        params = _legacy_params(ctx.dot, step)
        newest = ctx.newest_source_mtime()
        if newest is not None and newest > mtime:
            return StepStatus(step, "stale", "mtime", "sources are newer than the step's outputs", None, params, [])
        return StepStatus(step, "current", "mtime", "no record; outputs are newer than the sources", None, params, [])

    assert ctx.record is not None
    completed_at = entry.get("completed_at")
    params = _d(entry.get("params"))
    run_id = entry.get("run_id")

    def result(state: str, reason: str, changed: Optional[List[str]] = None) -> StepStatus:
        return StepStatus(step, state, "fingerprint", reason, completed_at, params, changed or [], run_id)

    recorded_root = ctx.record.get("project_root")
    if recorded_root != ctx.root:
        return result("stale", f"produced for another location ({recorded_root})")
    sources = _d(entry.get("sources"))
    fp = ctx.fingerprint()
    if sources.get("digest") != fp.digest:
        old_files = _d(sources.get("files"))
        changed = changed_files(old_files, fp.files)
        return result("stale", _describe_changes(changed), changed)
    inputs = _d(entry.get("inputs"))
    for up in UPSTREAM[step]:
        up_status = done[up]
        if up in inputs:
            if up_status.state == "missing":
                return result("stale", f"{up} was removed since the step ran")
            if up_status.run_id != inputs[up]:
                return result("stale", f"{up} was run again since the step ran")
        elif up_status.run_id is not None:
            return result("stale", f"{up} was run after the step")
        if up_status.state == "stale":
            return result("stale", f"{up} is stale")
    return result("current", "the outputs match the current sources")


def analysis_status(dot_discopop: str, project_root: Optional[str] = None) -> Dict[str, StepStatus]:
    ctx = _Context(dot_discopop, project_root)
    done: Dict[str, StepStatus] = {}
    for step in STEPS:
        done[step] = _compute(ctx, step, done)
    return done


def step_status(dot_discopop: str, step: str, project_root: Optional[str] = None) -> StepStatus:
    if step not in STEPS:
        raise ValueError(f"unknown step '{step}'")
    return analysis_status(dot_discopop, project_root)[step]


def covers(status: StepStatus, **required: Any) -> bool:
    """Whether a current step was produced with at least the required parameters.

    configs: set equality against the recorded config names; enabled_patterns: the recorded set is a
    superset; any other key: equality. A step that is not current covers nothing.
    """
    if status.state != "current":
        return False
    for key, value in required.items():
        have = status.params.get(key)
        if key == "configs":
            if set(have or ()) != set(value):
                return False
        elif key == "enabled_patterns":
            if not set(value) <= set(have or ()):
                return False
        elif have != value:
            return False
    return True

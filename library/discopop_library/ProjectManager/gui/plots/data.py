# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Pure data-reduction helpers for the results plots.

Everything here is free of Tk and matplotlib so it can be unit-tested directly.
Two data sources are handled:

* ``execution_results.json`` (Report tab) -- nested ``config -> script -> setting
  -> [executions]``; flattened into :class:`ExecutionRecord`s with derived speedup
  and efficiency (relative to the ``seq`` baseline of the same config+script).
* the autotuner progress stream (Autotuning tab) -- ``@@AT_PROGRESS`` stdout lines
  and ``progress.jsonl``; parsed into plain event dicts, plus a ``best_so_far``
  convergence series.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from discopop_library.EmpiricalAutotuning.output.progress import PROGRESS_PREFIX
from discopop_library.ProjectManager.gui.plots import mode_style

_SETTINGS_SUFFIX = "_settings.json"


@dataclass
class ExecutionRecord:
    """One measured execution, flattened from ``execution_results.json``."""

    config: str
    script: str
    mode: str  # execution mode / setting stem: seq, par, dp, hd, or a custom name
    label: str
    thread_count: int
    applied_suggestions: List[int]
    time: float
    code: int
    timeout: bool
    valid: bool  # ran successfully (return code 0 and not timed out)
    speedup: Optional[float]  # seq-baseline time / this time (same config+script)
    efficiency: Optional[float]  # speedup / thread_count
    # Suggestion application bookkeeping. ``application_failed`` marks a record that is
    # *not* a measurement: the requested patches never reached the code, so the run was
    # skipped rather than executed on the unmodified sources. Such a record carries no
    # runtime, speedup or efficiency and must be kept out of every metric aggregation.
    requested_suggestions: List[int] = field(default_factory=list)
    failed_suggestions: List[int] = field(default_factory=list)
    application_failed: bool = False
    executed: bool = True

    @property
    def status(self) -> str:
        """Status key for :mod:`mode_style` (valid / failed / not_applied)."""
        return mode_style.execution_status(self.valid, self.timeout, self.application_failed)

    @property
    def has_measurement(self) -> bool:
        """False for records that were never run (e.g. unapplied suggestions)."""
        return self.executed and not self.application_failed


def mode_of_setting(setting: str) -> str:
    """``"par_settings.json"`` -> ``"par"``; leaves other names unchanged."""
    if setting.endswith(_SETTINGS_SUFFIX):
        return setting[: -len(_SETTINGS_SUFFIX)]
    return setting


def _was_executed(execution: Dict[str, Any]) -> bool:
    """False for a placeholder entry recorded instead of an actual run."""
    if execution.get("suggestion_application_failed", False):
        return False
    return bool(execution.get("executed", True))


def _best_valid_runtime(executions: Sequence[Dict[str, Any]]) -> Optional[float]:
    """Best (smallest) runtime among valid (code 0, no timeout) executions, or None."""
    best: Optional[float] = None
    for execution in executions:
        if not _was_executed(execution):
            continue
        if execution.get("code") == 0 and not execution.get("timeout_expired", False):
            time = execution.get("time")
            if time is not None and (best is None or time < best):
                best = time
    return best


def _seq_runtime(settings: Dict[str, Any]) -> Optional[float]:
    """Best (smallest) valid sequential runtime for a config+script, or None."""
    seq_executions = settings.get("seq" + _SETTINGS_SUFFIX)
    if not seq_executions:
        return None
    return _best_valid_runtime(seq_executions)


def _unsuggested_runtime(executions: Sequence[Dict[str, Any]]) -> Optional[float]:
    """Best valid runtime among executions with *no* suggestions applied, or None.

    This is the autotuner's own reference: it measures ``par_settings.json`` with
    an empty suggestion set and reports every combination's speedup relative to it.
    Used as the baseline when no ``seq_settings.json`` group exists (autotuner runs
    write only the explored ``par`` combinations, never a sequential baseline).
    """
    # A run whose suggestions failed to apply also has an empty applied set, but it is
    # not a baseline measurement -- it is not a measurement at all. Including it would
    # let an unapplied configuration define the reference every speedup is divided by.
    unsuggested = [e for e in executions if not e.get("applied_suggestions") and _was_executed(e)]
    if not unsuggested:
        return None
    return _best_valid_runtime(unsuggested)


def parse_execution_results(data: Dict[str, Any]) -> List[ExecutionRecord]:
    """Flatten the nested ``execution_results.json`` structure into records."""
    records: List[ExecutionRecord] = []
    for config in data:
        for script in data[config]:
            settings = data[config][script]
            seq_runtime = _seq_runtime(settings)
            for setting in settings:
                mode = mode_of_setting(setting)
                # Prefer the sequential baseline (normal Execute runs); fall back to
                # the no-suggestions run within this setting group (autotuner runs,
                # which have no seq baseline) so their speedups still render.
                baseline_runtime = seq_runtime
                if baseline_runtime is None:
                    baseline_runtime = _unsuggested_runtime(settings[setting])
                for execution in settings[setting]:
                    code = int(execution.get("code", -1))
                    timeout = bool(execution.get("timeout_expired", False))
                    time = float(execution.get("time", 0.0))
                    thread_count = int(execution.get("thread_count", 1))
                    executed = _was_executed(execution)
                    failed_suggestions = [int(s) for s in execution.get("failed_suggestions", [])]
                    application_failed = bool(execution.get("suggestion_application_failed", False)) or bool(
                        failed_suggestions
                    )
                    valid = code == 0 and not timeout and executed
                    # a skipped run has no runtime, hence no speedup to report
                    if executed and baseline_runtime is not None and time > 0:
                        speedup: Optional[float] = baseline_runtime / time
                    else:
                        speedup = None
                    efficiency = speedup / thread_count if (speedup is not None and thread_count > 0) else None
                    records.append(
                        ExecutionRecord(
                            config=config,
                            script=script,
                            mode=mode,
                            label=str(execution.get("label", "")),
                            thread_count=thread_count,
                            applied_suggestions=[int(s) for s in execution.get("applied_suggestions", [])],
                            time=time,
                            code=code,
                            timeout=timeout,
                            valid=valid,
                            speedup=speedup,
                            efficiency=efficiency,
                            requested_suggestions=[int(s) for s in execution.get("requested_suggestions", [])],
                            failed_suggestions=failed_suggestions,
                            application_failed=application_failed,
                            executed=executed,
                        )
                    )
    return records


def pareto_frontier(points: Sequence[Tuple[float, float]]) -> List[int]:
    """Indices of the non-dominated points when *maximizing both* coordinates.

    A point is dominated if another point is >= in both coordinates and strictly
    greater in at least one. Returned indices are sorted by ascending x.
    """
    frontier: List[int] = []
    for i, (xi, yi) in enumerate(points):
        dominated = False
        for j, (xj, yj) in enumerate(points):
            if j == i:
                continue
            if xj >= xi and yj >= yi and (xj > xi or yj > yi):
                dominated = True
                break
        if not dominated:
            frontier.append(i)
    frontier.sort(key=lambda idx: points[idx][0])
    return frontier


def best_so_far(measurements: Sequence[Tuple[int, Optional[float], bool]]) -> List[Tuple[int, float]]:
    """Running best (maximum) speedup over valid measurements, in search order.

    ``measurements`` is a sequence of ``(index, speedup, valid)``. The result is a
    monotonically non-decreasing step series ``[(index, best_so_far), ...]`` that
    starts at the first index for which a valid speedup exists.
    """
    out: List[Tuple[int, float]] = []
    best: Optional[float] = None
    for index, speedup, valid in measurements:
        if valid and speedup is not None and (best is None or speedup > best):
            best = speedup
        if best is not None:
            out.append((index, best))
    return out


_DECODER = json.JSONDecoder()


def _decode_leading_event(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Decode the JSON object at the start of ``text``; return it plus the rest.

    Returns ``(None, text)`` when ``text`` does not start with a JSON object, so the
    caller can treat the segment as ordinary output instead of an event.
    """
    stripped = text.lstrip()
    offset = len(text) - len(stripped)
    try:
        obj, end = _DECODER.raw_decode(stripped)
    except json.JSONDecodeError:
        return None, text
    if not isinstance(obj, dict):
        return None, text
    return obj, text[offset + end :]


def split_progress_events(line: str, prefix: str = PROGRESS_PREFIX) -> Tuple[List[Dict[str, Any]], str]:
    """Extract every progress event contained in one line of raw tool output.

    A ``@@AT_PROGRESS`` payload does not necessarily start at a line boundary: the GUI
    reads the tool's stdout and stderr merged into a single stream, and a progress
    bar redrawing itself with a carriage return leaves its bar text as an unterminated
    line, to which the next event is then appended (``"42%|##  |...@@AT_PROGRESS {...}"``).
    Events are therefore searched for anywhere in the line; the remaining text is
    returned separately so it can still be echoed to the console.

    ``prefix`` selects the channel: the autotuner's by default, and
    ``@@PR_PROGRESS`` for discopop_patch_repair, which emits the same shape of events
    over the same stream.
    """
    if prefix not in line:
        return [], line
    events: List[Dict[str, Any]] = []
    residual: List[str] = []
    segments = line.split(prefix)
    residual.append(segments[0])
    for segment in segments[1:]:
        event, rest = _decode_leading_event(segment)
        if event is None:
            # not an event after all (malformed or non-object payload): keep as output
            residual.append(prefix + segment)
        else:
            events.append(event)
            residual.append(rest)
    return events, "".join(residual)


def parse_progress_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse one ``@@AT_PROGRESS {json}`` output line into an event dict.

    Returns None for lines without the prefix or with malformed JSON, so a caller can
    filter progress events out of an interleaved stdout stream. Use
    :func:`split_progress_events` when a line may carry an event that is preceded by
    unrelated output.
    """
    events, _residual = split_progress_events(line)
    return events[0] if events else None


def parse_progress_jsonl(text: str) -> List[Dict[str, Any]]:
    """Parse the contents of a ``progress.jsonl`` file into event dicts."""
    events: List[Dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            events.append(obj)
    return events

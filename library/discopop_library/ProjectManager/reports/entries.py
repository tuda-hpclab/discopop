# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Shared reading of ``execution_results.json`` entries for the generated reports.

An entry is not necessarily a measurement: when the requested parallelization
suggestions could not be applied, the run is skipped and a placeholder entry is
recorded instead (return code -1, no runtime). The reports must render those rows as
"not applied" rather than as a parallel run without a speedup -- and must not divide
by their zero runtime.
"""

from typing import Any, Dict, Optional

NOT_APPLIED_TEXT = "not applied"


def was_executed(execution: Dict[str, Any]) -> bool:
    """False for a placeholder entry recorded in place of an actual run."""
    if execution.get("suggestion_application_failed", False):
        return False
    return bool(execution.get("executed", True))


def failed_suggestions(execution: Dict[str, Any]) -> Any:
    """The requested suggestions that never reached the code (possibly empty)."""
    return execution.get("failed_suggestions") or execution.get("requested_suggestions") or []


def applied_suggestions_text(execution: Dict[str, Any]) -> str:
    """Suggestion cell content: what is in the code, plus what failed to apply."""
    text = str(execution.get("applied_suggestions", []))
    if not was_executed(execution):
        failed = failed_suggestions(execution)
        text += " (!" + NOT_APPLIED_TEXT + ": " + str(failed) + ")"
    return text


def runtime_text(execution: Dict[str, Any]) -> str:
    """Runtime cell content; a skipped run has no runtime to report."""
    if not was_executed(execution):
        return "-"
    return str(execution.get("time", "-"))


def speedup_of(seq_runtime: float, execution: Dict[str, Any]) -> Optional[float]:
    """Speedup of one entry over ``seq_runtime``, or None when it has no measurement.

    Returns None for a skipped run and whenever no usable runtime is available, so
    callers render a placeholder instead of dividing by zero.
    """
    if not was_executed(execution):
        return None
    runtime = execution.get("time", 0.0)
    if not runtime or runtime <= 0 or seq_runtime <= 0:
        return None
    return float(seq_runtime) / float(runtime)


def efficiency_of(seq_runtime: float, execution: Dict[str, Any]) -> Optional[float]:
    """Parallel efficiency of one entry, or None when it has no measurement."""
    speedup = speedup_of(seq_runtime, execution)
    if speedup is None:
        return None
    thread_count = execution.get("thread_count", 1) or 1
    return speedup / float(thread_count)


def format_metric(value: Optional[float]) -> str:
    return "-" if value is None else str(round(value, 3))

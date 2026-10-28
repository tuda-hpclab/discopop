# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Task parallelism as get_parallelization_suggestions reports it: a parallel region and the tasks in it.

The explorer's task positions are not always applicable one to one, so a group is described (region,
task bodies, dependences, and flags where the group looks implausible), not turned into pragmas.
"""

import gzip
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("discopop-mcp")

# the explorer's value for a line it does not know
UNKNOWN_LINE = 262143
_MAX_BODY_WIDTH = 70


@dataclass
class Task:
    pattern_id: int
    start_line: int
    end_line: int
    in_dep: list[str] = field(default_factory=list)
    out_dep: list[str] = field(default_factory=list)
    in_out_dep: list[str] = field(default_factory=list)
    shared: list[str] = field(default_factory=list)
    private: list[str] = field(default_factory=list)
    first_private: list[str] = field(default_factory=list)


@dataclass
class TaskGroup:
    """A parallel region (patterns.json: PARALLELREGION) and the tasks it contains."""

    file_id: Optional[int]
    start_line: int
    end_line: int
    tasks: list[Task]
    # set if the tasks are created per iteration of a loop: the line of the loop
    loop_line: Optional[int] = None
    # what the explorer found out about the data flow of the group; None if it recorded nothing (older results)
    # {"from_task", "to_task", "variable", "kind": RAW | WAR}: the later task depends on the earlier one
    task_dependences: Optional[list[dict[str, Any]]] = None
    # {"task", "variable", "kind": RAW | WAR, "line": file id:line}: the code after the region depends on a task
    after_dependences: Optional[list[dict[str, Any]]] = None


@dataclass
class FunctionSpan:
    file_id: int
    name: str
    start_line: int
    end_line: int


def _int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _names(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def _records(value: Any) -> Optional[list[dict[str, Any]]]:
    return [r for r in value if isinstance(r, dict)] if isinstance(value, list) else None


def task_groups(patterns: dict[str, Any]) -> dict[str, TaskGroup]:
    """The task groups of patterns.json by the pattern id of their region, which is the one with a patch."""
    entries = patterns.get("task") or []
    tasks: dict[int, Task] = {}
    for entry in entries:
        if entry.get("type") != "TASK":
            continue
        pid, start, end = (
            _int(entry.get("pattern_id")),
            _int(entry.get("region_start_line")),
            _int(entry.get("region_end_line")),
        )
        if pid is None or start is None or end is None:
            continue
        tasks[pid] = Task(
            pid,
            start,
            end,
            _names(entry.get("in_dep")),
            _names(entry.get("out_dep")),
            _names(entry.get("in_out_dep")),
            _names(entry.get("shared")),
            _names(entry.get("private")),
            _names(entry.get("first_private")),
        )
    groups: dict[str, TaskGroup] = {}
    for entry in entries:
        if entry.get("type") != "PARALLELREGION":
            continue
        start, end = _int(entry.get("region_start_line")), _int(entry.get("region_end_line"))
        if start is None or end is None:
            continue
        contained = [tasks[t] for t in (entry.get("contains_patterns") or []) if t in tasks]
        # the id of the file is only part of the span of the enclosing code, "file id:line"
        groups[str(entry.get("pattern_id"))] = TaskGroup(
            _int(str(entry.get("start_line", "")).split(":")[0]),
            start,
            end,
            contained,
            _int(str(entry.get("loop_start_line") or "").split(":")[-1]),
            _records(entry.get("task_dependences")),
            _records(entry.get("after_dependences")),
        )
    return groups


def functions(dot_discopop: Path) -> list[FunctionSpan]:
    """The functions of the side-effect export; empty if there is none."""
    path = dot_discopop / "explorer" / "side_effects.json.gz"
    try:
        with gzip.open(path, "rt") as f:
            table = json.load(f).get("functions", [])
        return [
            FunctionSpan(int(fn["file_id"]), str(fn["name"]), int(fn["start_line"]), int(fn["end_line"]))
            for fn in table
        ]
    except (OSError, ValueError, KeyError, TypeError) as e:
        logger.debug(f"No function table in {path}: {e}")
        return []


def enclosing_function(group: TaskGroup, spans: list[FunctionSpan]) -> Optional[FunctionSpan]:
    """The innermost function containing the group's region."""
    containing = [
        s
        for s in spans
        if s.file_id == group.file_id and s.start_line <= group.start_line and group.end_line <= s.end_line
    ]
    return max(containing, key=lambda s: s.start_line, default=None)


def _line_text(source: list[str], line: int) -> str:
    return source[line - 1].strip() if 0 < line <= len(source) else ""


def _body(task: Task, source: list[str]) -> str:
    """The first line of the task's code, and how many more it has."""
    text = _line_text(source, task.start_line)
    if len(text) > _MAX_BODY_WIDTH:
        text = text[: _MAX_BODY_WIDTH - 3] + "..."
    more = task.end_line - task.start_line
    return f"{text} (+{more} lines)" if text and 0 < more and task.end_line != UNKNOWN_LINE else text


def flags(group: TaskGroup, source: list[str]) -> list[str]:
    """Why a group may be no parallelism that is worth to take: the explorer's groups are not filtered."""
    found: list[str] = []
    if group.end_line == UNKNOWN_LINE or any(t.end_line == UNKNOWN_LINE for t in group.tasks):
        found.append("an end line is unknown")
    spans = [(t.start_line, t.end_line) for t in group.tasks]
    for i, a in enumerate(group.tasks):
        for b in group.tasks[i + 1 :]:
            if (a.start_line, a.end_line) == (b.start_line, b.end_line):
                found.append(f"tasks {a.pattern_id} and {b.pattern_id} have the same lines")
            elif a.start_line <= b.end_line and b.start_line <= a.end_line:
                found.append(f"the lines of tasks {a.pattern_id} and {b.pattern_id} overlap")
    if len(spans) < 2 and group.loop_line is None:
        found.append("fewer than two tasks")
    for task in group.tasks:
        if task.end_line == UNKNOWN_LINE:
            continue
        lines = [_line_text(source, n) for n in range(task.start_line, task.end_line + 1)]
        lines = [line for line in lines if line]
        if lines and all(line in ("{", "}") for line in lines):
            found.append(f"task {task.pattern_id} is only a brace, not a statement")
        elif lines and lines[-1].startswith("return"):
            found.append(f"task {task.pattern_id} ends in a return, which cannot leave a task")
    return found


def dependences(group: TaskGroup) -> str:
    """The dependences between the tasks: a later task needs what an earlier one wrote (RAW), or overwrites what it
    read (WAR, marked as anti dependence)."""
    if group.task_dependences is None:
        return _recorded_clauses(group)
    if not group.task_dependences:
        return "none"
    return "; ".join(
        f"task {d.get('from_task')} -> task {d.get('to_task')}: {d.get('variable')}"
        + (" (anti)" if d.get("kind") == "WAR" else "")
        for d in group.task_dependences
    )


def _recorded_clauses(group: TaskGroup) -> str:
    """What results of an older explorer hold: the clauses of the tasks, without the kind of dependence."""
    parts = []
    for task in group.tasks:
        recorded = [
            f"{label} {', '.join(names)}"
            for label, names in (("in", task.in_dep), ("out", task.out_dep), ("in/out", task.in_out_dep))
            if names
        ]
        if recorded:
            parts.append(f"task {task.pattern_id}: " + "; ".join(recorded))
    return "; ".join(parts) if parts else "none recorded"


def join_points(group: TaskGroup, display_file: str) -> list[str]:
    """Where the code after the region depends on the tasks: the line, the variables and the tasks to wait for."""
    if group.after_dependences is None:
        return []
    by_line: dict[str, list[str]] = {}
    for d in sorted(group.after_dependences, key=lambda d: (_int(str(d.get("line")).split(":")[-1]) or 0, str(d))):
        line = str(d.get("line") or "").split(":")[-1] or "?"
        verb = "overwrites" if d.get("kind") == "WAR" else "reads"
        by_line.setdefault(line, []).append(f"{verb} {d.get('variable')} (task {d.get('task')})")
    if not by_line:
        return ["  join: no later code depends on the tasks (not tracked: what recursive calls write)"]
    return [
        f"  join: the tasks have to be complete before {display_file}:{line}, which " + ", ".join(entries)
        for line, entries in by_line.items()
    ]


def data_sharing(group: TaskGroup) -> list[str]:
    """The variables of each task by the way they are shared with it."""
    lines = []
    for task in group.tasks:
        parts = [
            f"{label} {', '.join(names)}"
            for label, names in (
                ("shared", task.shared),
                ("firstprivate", task.first_private),
                ("private", task.private),
            )
            if names
        ]
        if parts:
            lines.append(f"  data sharing of task {task.pattern_id}: " + "; ".join(parts))
    return lines


def describe(group: TaskGroup, display_file: str, source: list[str]) -> list[str]:
    """The lines under a task group's headline."""
    if group.loop_line is not None:
        return _describe_loop(group, display_file, source)
    lines = [f"  parallel region: {display_file}:{group.start_line}-{group.end_line}"]
    for task in group.tasks:
        place = f"{display_file}:{task.start_line}-{task.end_line}"
        lines.append(f"  task {task.pattern_id}: {place}   {_body(task, source)}".rstrip())
    lines.append(f"  dependences between the tasks: {dependences(group)}")
    lines += join_points(group, display_file)
    lines += data_sharing(group)
    for flag in flags(group, source):
        lines.append(f"  flag: {flag}")
    return lines


def _describe_loop(group: TaskGroup, display_file: str, source: list[str]) -> list[str]:
    """A task group that creates one task per iteration of a loop (the iterations are independent)."""
    lines = [
        f"  one task per iteration of the loop at {display_file}:{group.loop_line}"
        f" (loop lines {group.start_line}-{group.end_line})"
    ]
    for task in group.tasks:
        place = f"{display_file}:{task.start_line}-{task.end_line}"
        lines.append(f"  task body {task.pattern_id}: {place}   {_body(task, source)}".rstrip())
    joins = join_points(group, display_file) if group.after_dependences else []
    # nothing found does not mean that nothing is needed: writes through pointers are not tracked
    lines += joins or ["  join: wait for the tasks after the loop, before the results are used"]
    lines += data_sharing(group)
    for flag in flags(group, source):
        lines.append(f"  flag: {flag}")
    return lines


def covering(groups: dict[str, TaskGroup], file_id: int, start_line: int, end_line: int) -> dict[str, TaskGroup]:
    """The groups whose parallel region shares a line with the given lines."""
    return {
        pid: g
        for pid, g in groups.items()
        if g.file_id == file_id and g.start_line <= end_line and start_line <= g.end_line
    }

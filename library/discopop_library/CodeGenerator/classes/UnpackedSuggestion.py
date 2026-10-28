# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import re
from typing import Callable, Dict, List, Any, Optional, Tuple

from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Enums import (
    EntryPointType,
    EntryPointPositioning,
    UpdateType,
    ExitPointType,
    ExitPointPositioning,
)
from discopop_library.CodeGenerator.classes.Enums import (
    OmpConstructPositioning,
    PragmaPosition,
)
from discopop_library.CodeGenerator.classes.Pragma import Pragma
from discopop_library.discopop_optimizer.classes.system.devices.DeviceTypeEnum import DeviceTypeEnum
from discopop_library.discopop_optimizer.classes.types.Aliases import DeviceID

# the line the explorer reports for a line it does not know (a decoded unset line id of the profiler)
UNKNOWN_LINE = 262143

# appended to the task pragmas of a recursive group: the place of the missing cutoff, for the reader to fill in
RECURSIVE_TASK_CUTOFF_MARKER = " /* DiscoPoP TODO: add the cutoff final(<condition>) */"

# a statement that starts with a type: two or more identifiers (and ``*``, ``&``, ``::``, template arguments)
# followed by an initializer; ``res = fib(n);`` and ``a[i] = f();`` have a single identifier before the ``=``
_DECLARATION = re.compile(
    r"^\s*(?:[A-Za-z_]\w*(?:::\w+)*(?:<[^;=()]*>)?[\s*&]+)+[*&\s]*[A-Za-z_]\w*\s*(?:\[[^\]]*\]\s*)*(?:=|\(|\{)"
)
_NOT_A_TYPE = {"return", "else", "case", "goto", "delete", "throw", "co_return", "co_yield", "new", "do", "sizeof"}


def _is_declaration(text: Optional[str]) -> bool:
    """Whether the source line starts with a declaration that has an initializer (``long long r = fib(n);``): a
    pragma cannot apply to it. Unknown text (None) is no declaration."""
    if text is None:
        return False
    first = re.match(r"\s*(\w+)", text)
    return _DECLARATION.match(text) is not None and first is not None and first.group(1) not in _NOT_A_TYPE


class UnpackedSuggestion(object):
    type: str
    values: Dict[str, Any]
    file_id: int
    start_line: int
    end_line: int
    device_id: Optional[DeviceID]
    device_type: Optional[DeviceTypeEnum]
    host_device_id: int
    # the text of a line of the original source (file id, line), if the caller can give it
    line_text: Optional[Callable[[int, int], Optional[str]]] = None

    def __init__(
        self,
        type_str: str,
        values: Dict[str, Any],
        device_id: Optional[DeviceID] = None,
        device_type: Optional[DeviceTypeEnum] = None,
        host_device_id: int = 0,
    ):
        self.type = type_str
        self.values = values
        self.device_id = device_id
        self.device_type = device_type
        self.host_device_id = host_device_id

        # get start and end line of target section
        self.file_id = int(self.values["start_line"].split(":")[0])
        self.start_line = int(self.values["start_line"].split(":")[1])
        self.end_line = int(self.values["end_line"].split(":")[1])

        # read device id and type if present
        if self.device_id is None and "device_id" in self.values:
            if self.values["device_id"] is not None:
                self.device_id = int(self.values["device_id"])
        if self.device_type is None and "device_type" in self.values:
            if self.values["device_type"] is not None:
                self.device_type = self.values["device_type"]

    def __get_device_update_pragmas(self) -> List[Pragma]:
        pragmas = []
        pragma = Pragma()

        source_device_id = int(self.values["source_device_id"])
        target_device_id = int(self.values["target_device_id"])
        var_name = self.values["var_name"]
        is_first_data_occurrence: bool = self.values["is_first_data_occurrence"]
        openmp_source_device_id = self.values["openmp_source_device_id"]
        openmp_target_device_id = self.values["openmp_target_device_id"]
        range: Optional[Tuple[int, int]] = self.values["range"]
        delete_data: bool = self.values["delete_data"]
        copy_delete_data: bool = self.values["copy_delete_data"]

        def get_range_str(r: Optional[Tuple[int, int]]) -> str:
            return "" if r is None else "[" + str(r[0]) + ":" + str(r[1]) + "]"

        if source_device_id == self.host_device_id and target_device_id == self.host_device_id:
            # no update required
            pass
        elif source_device_id == self.host_device_id and target_device_id != self.host_device_id:
            # update type to
            if is_first_data_occurrence:
                pragma.pragma_str = "#pragma omp target enter data map(to:"
            else:
                pragma.pragma_str = "#pragma omp target update to("
            pragma.pragma_str += (
                var_name
                + get_range_str(range)
                + ") device("
                # + str(openmp_source_device_id)
                # + " -> "
                + str(openmp_target_device_id)
                + ")"
            )

        elif source_device_id != self.host_device_id and target_device_id == self.host_device_id:
            # update type from
            if delete_data:
                pragma.pragma_str = "#pragma omp target exit data map(delete:"
            elif copy_delete_data:
                pragma.pragma_str = "#pragma omp target exit data map(from:"
            else:
                pragma.pragma_str = "#pragma omp target update from("

            pragma.pragma_str += (
                var_name
                + get_range_str(range)
                + ") device("
                + str(openmp_source_device_id)
                # + " -> "
                # + str(openmp_target_device_id)
                + ")"
            )

        else:
            # todo Implement updates between devices
            #  Suggest two update instructions instead of one, or make sure that openMP supports device-device updates

            # raise NotImplementedError("Updates between devices are not yet implemented!")
            # update between two devices
            pragma.pragma_str = (
                "#pragma omp target update Device("
                + str(source_device_id)
                + ") --> Device("
                + str(openmp_source_device_id)
                + " -> "
                + str(openmp_target_device_id)
                + ") Var("
                + var_name
                + get_range_str(range)
                + ")"
            )

        #            #  map to host
        #            pragma.pragma_str = (
        #                # "#pragma omp target map(from:"
        #                    "#pragma omp target enter data map(to:"
        #                    + var_name
        #                    + ") device("
        #                    + str(source_device_id)
        #                    + ")"
        #            )
        #            #  map from host to second device
        #            pragma.pragma_str = (
        #                    "#pragma omp target data map(from:"
        #                    + var_name
        #                    + ") device("
        #                    + str(target_device_id)
        #                    + ")"
        #            )

        pragma.file_id = self.file_id
        pragma.start_line = self.start_line
        pragma.end_line = self.end_line
        pragma.pragma_position = PragmaPosition.BEFORE_END

        if len(pragma.pragma_str) != 0:
            pragmas.append(pragma)
        return pragmas

    def __get_do_all_and_reduction_pragmas(self, is_gpu_pragma: bool) -> List[Pragma]:
        pragmas = []
        pragma = Pragma()
        if is_gpu_pragma:
            # get device id for execution (else branch for compatibility with "legacy" gpu suggestions)
            if self.device_id is not None:
                device_id = self.device_id
            else:
                device_id = self.values["dp_optimizer_device_id"]

            pragma.pragma_str = "#pragma omp target teams distribute parallel for "
            pragma.pragma_str += "device(" + str(device_id) + ") "
        else:
            pragma.pragma_str = self.values["pragma"] + " "
        if "collapse_level" in self.values:
            if self.values["collapse_level"] > 1:
                pragma.pragma_str += "collapse(" + str(self.values["collapse_level"]) + ") "
        if len(self.values["first_private"]) > 0:
            pragma.pragma_str += "firstprivate(" + ",".join([str(s) for s in self.values["first_private"]]) + ") "
        if len(self.values["private"]) > 0:
            pragma.pragma_str += "private(" + ",".join([str(s) for s in self.values["private"]]) + ") "
        if len(self.values["last_private"]) > 0:
            pragma.pragma_str += "lastprivate(" + ",".join([str(s) for s in self.values["last_private"]]) + ") "
        if len(self.values["shared"]) > 0:
            pragma.pragma_str += "shared(" + ",".join([str(s) for s in self.values["shared"]]) + ") "
        if len(self.values["reduction"]) > 0:
            reductions_dict: Dict[str, List[str]] = dict()
            for entry in self.values["reduction"]:
                red_type: str = entry.split(":")[0]
                var: str = entry.split(":")[1]
                if red_type not in reductions_dict:
                    reductions_dict[red_type] = []
                reductions_dict[red_type].append(var)
            for red_type in reductions_dict:
                pragma.pragma_str += "reduction(" + red_type + ":" + ",".join(reductions_dict[red_type]) + ") "

        pragma.file_id = self.file_id
        pragma.start_line = self.start_line
        pragma.end_line = self.end_line

        pragmas.append(pragma)
        return pragmas

    def __task_data_sharing_clauses(self) -> str:
        """The data sharing clauses of a task, each variable once (shared before firstprivate before private)."""
        seen: set[str] = {name for _, name in self.__task_reductions()}  # a reduced variable has its own clause
        clauses = ""
        for clause, key in (("shared", "shared"), ("firstprivate", "first_private"), ("private", "private")):
            names: List[str] = []
            for name in self.values.get(key) or []:
                if str(name) not in seen:
                    seen.add(str(name))
                    names.append(str(name))
            if len(names) > 0:
                clauses += " " + clause + "(" + ",".join(names) + ")"
        return clauses

    def __task_reductions(self) -> List[Tuple[str, str]]:
        """(operation, variable) of the reductions of a task, from its entries "<operation>:<variable>"."""
        reductions: List[Tuple[str, str]] = []
        for entry in self.values.get("reduction") or []:
            operation, _, name = str(entry).partition(":")
            reductions.append((operation, name))
        return reductions

    def __task_reduction_clauses(self) -> str:
        """The in_reduction clauses of a task (the variables it reduces, grouped by operation)."""
        by_operation: Dict[str, List[str]] = {}
        for operation, name in self.__task_reductions():
            if name not in by_operation.setdefault(operation, []):
                by_operation[operation].append(name)
        return "".join(" in_reduction(" + op + ":" + ",".join(names) + ")" for op, names in by_operation.items())

    def __task_depend_clauses(self) -> str:
        """The depend clauses of a task for its dependences on the other tasks of the group (in_dep, out_dep and
        in_out_dep of the pattern), each variable once: a task that waits for the result of another one does so by its
        clauses, the tasks that do not depend on each other stay independent."""
        seen: set[str] = set()
        clauses = ""
        for clause, key in (("inout", "in_out_dep"), ("out", "out_dep"), ("in", "in_dep")):
            names: List[str] = []
            for name in self.values.get(key) or []:
                if str(name) and str(name) not in seen:
                    seen.add(str(name))
                    names.append(str(name))
            if len(names) > 0:
                clauses += " depend(" + clause + ": " + ", ".join(names) + ")"
        return clauses

    @staticmethod
    def __reason_not_applicable_by_data_sharing(tasks: List[Dict[str, Any]]) -> Optional[str]:
        """Why the data sharing of the tasks has no pragma form, None if it has one: OpenMP tasks have no lastprivate
        (every task writes the shared variable, the last one to finish decides the value), and the operation of a
        reduction has to be known to write it."""
        for task in tasks:
            if task.get("last_private"):
                names = ", ".join(str(n) for n in task["last_private"])
                return "the last iteration's value of " + names + " is needed after the loop"
        operations: Dict[str, set[str]] = {}
        for task in tasks:
            for entry in task.get("reduction") or []:
                operation, _, name = str(entry).partition(":")
                operations.setdefault(name, set()).add(operation)
        for name, ops in sorted(operations.items()):
            if ops & {"?", ""}:
                return "the operation of the reduction of " + name + " is unknown"
            if len(ops) > 1:
                return "the reduction of " + name + " has different operations"
        return None

    def __get_parallel_region_of_tasks_pragmas(
        self, contained_patterns: Optional[Dict[str, List[str]]]
    ) -> List[Pragma]:
        """The pragmas of a task group (PARALLELREGION entry of the pattern type "task") and of its tasks.

        Form (the smallest one that is correct; omp-tasks puts the region around the first call of the recursion
        instead, which the explorer does not know):

            #pragma omp parallel
            #pragma omp single
            {
            #pragma omp task <data sharing clauses> [depend clauses]
            <task>                      depend: the dependences of the task on the other tasks of the group
            ...
            [#pragma omp taskwait]      only if the code after the group needs the results of the tasks
            }                           the end of the region is the join: the tasks are complete after it

        Dependences between the tasks of the group are depend clauses (the tasks that do not depend on each other
        stay independent); a taskwait is for the case that a following statement needs the results of all tasks.

        A group of tasks per loop iteration starts at the loop header and ends after the last line of the loop.

        A group of recursive tasks (``entry_call_lines`` of the pattern: the calls that enter the recursion) has no
        parallel region inside of the function: a region on every level of the recursion is a nested region each.
        The region is placed around the entry calls instead, as in omp-tasks, in the file of each call:

            #pragma omp parallel
            #pragma omp single
            res = fib(n);               the entry call (the pragmas apply to the statement)

        and the function only holds the tasks and, always, the join (a taskwait after the group, or the end of the
        taskgroup of a reduction): without the region, nothing else ends the tasks, which may use the locals of the
        function. An entry call that is a declaration (``long r = fib(n);``) cannot take the pragmas: the group is
        left to the reader then.
        A group that cannot be placed (an unknown line, tasks that share lines) is left to the reader: the patch
        only holds a comment, so that the suggestion still has a patch.
        """
        region_start = int(self.values["region_start_line"])
        region_end = int(self.values["region_end_line"])
        loop_end_unknown = False
        if self.values.get("loop_start_line"):
            # tasks per loop iteration: the region (which covers the task statement) starts at the loop header and ends
            # with the loop, not with the last task in its body
            region_start = int(str(self.values["loop_start_line"]).split(":")[1])
            if self.values.get("loop_end_line"):
                region_end = int(str(self.values["loop_end_line"]).split(":")[1])
            else:
                loop_end_unknown = True

        tasks: List[Dict[str, Any]] = []
        if contained_patterns is not None:
            wanted = set(self.values.get("contains_patterns") or [])
            for pattern_strs in contained_patterns.values():
                for pattern_str in pattern_strs:
                    pattern_dict = json.loads(pattern_str)
                    if pattern_dict["pattern_id"] in wanted and pattern_dict.get("type") == "TASK":
                        tasks.append(pattern_dict)
        tasks.sort(key=lambda t: (int(t["region_start_line"]), int(t["region_end_line"])))

        reason: Optional[str] = None
        if loop_end_unknown:
            reason = "the end of the loop is unknown"
        elif not self.values.get("loop_start_line") and region_start <= self.start_line:
            # the span of a task includes the header of the function (or loop) it is in: no pragma can go there
            reason = "a task starts at the header of its scope"
        elif UNKNOWN_LINE in [region_start, region_end] + [int(t["region_end_line"]) for t in tasks]:
            reason = "the end of a task is unknown"
        elif any(
            int(later["region_start_line"]) <= int(earlier["region_end_line"])
            for earlier, later in zip(tasks, tasks[1:])
        ):
            reason = "tasks share lines"
        if reason is None:
            reason = self.__reason_not_applicable_by_data_sharing(tasks)
        entry_lines = [(int(e.split(":")[0]), int(e.split(":")[1])) for e in self.values.get("entry_call_lines") or []]
        if reason is None and self.line_text is not None:
            for entry_file, entry_line in entry_lines:
                if _is_declaration(self.line_text(entry_file, entry_line)):
                    reason = (
                        "the call that enters the recursion declares a variable (line "
                        + str(entry_line)
                        + "), the parallel region cannot be placed around it"
                    )
                    break
        if reason is not None:
            if region_start == UNKNOWN_LINE:
                return []
            hint = Pragma()
            hint.file_id = self.file_id
            hint.start_line = region_start
            hint.end_line = region_start
            hint.pragma_str = "// DiscoPoP: task group not applicable as it is, " + reason + ", see the suggestion"
            return [hint]

        def line_pragma(text: str, line: int, position: PragmaPosition) -> Pragma:
            pragma = Pragma()
            pragma.file_id = self.file_id
            pragma.start_line = line
            pragma.end_line = line
            pragma.pragma_position = position
            pragma.pragma_str = text
            return pragma

        if entry_lines:
            return self.__get_recursive_tasks_pragmas(tasks, region_start, region_end, entry_lines, line_pragma)

        parallel_pragma = line_pragma(self.values["pragma"][0], region_start, PragmaPosition.BEFORE_START)
        single_pragma = line_pragma(self.values["pragma"][1], region_start, PragmaPosition.BEFORE_START)
        parallel_pragma.children.append(single_pragma)
        single_pragma.children.append(line_pragma("{", region_start, PragmaPosition.BEFORE_START))

        # the tasks reduce into a variable: a taskgroup around all of them combines the contributions, the tasks
        # take part by in_reduction (OpenMP 5)
        reductions: Dict[str, List[str]] = {}
        for task in tasks:
            for entry in task.get("reduction") or []:
                operation, _, name = str(entry).partition(":")
                if name not in reductions.setdefault(operation, []):
                    reductions[operation].append(name)
        if reductions:
            clauses = " ".join("task_reduction(" + op + ":" + ",".join(names) + ")" for op, names in reductions.items())
            single_pragma.children.append(
                line_pragma("#pragma omp taskgroup " + clauses, region_start, PragmaPosition.BEFORE_START)
            )
            single_pragma.children.append(line_pragma("{", region_start, PragmaPosition.BEFORE_START))

        # a dependence the explorer could not name a variable for orders the tasks by a taskwait before the later one
        # (depend clauses need the name)
        unnamed = {int(d["to_task"]) for d in (self.values.get("task_dependences") or []) if not d.get("variable")}
        for task in tasks:
            if task["pattern_id"] in unnamed:
                single_pragma.children.append(
                    line_pragma("#pragma omp taskwait", int(task["region_start_line"]), PragmaPosition.BEFORE_START)
                )
            single_pragma.children += UnpackedSuggestion("task", task).get_pragmas(contained_patterns)

        # Pragmas after the same line are inserted directly after it, so the later one comes first: the closing brace
        # is added before the taskwait, which the code after the group needs if it uses the results of the tasks.
        # The end of the taskgroup waits for the tasks itself and comes first of all.
        single_pragma.children.append(line_pragma("}", region_end, PragmaPosition.AFTER_END))
        if self.values.get("after_dependences") and not reductions:
            single_pragma.children.append(line_pragma("#pragma omp taskwait", region_end, PragmaPosition.AFTER_END))
        if reductions:
            single_pragma.children.append(line_pragma("}", region_end, PragmaPosition.AFTER_END))
        return [parallel_pragma]

    def __get_recursive_tasks_pragmas(
        self,
        tasks: List[Dict[str, Any]],
        region_start: int,
        region_end: int,
        entry_lines: List[Tuple[int, int]],
        line_pragma: Callable[[str, int, PragmaPosition], Pragma],
    ) -> List[Pragma]:
        """The pragmas of a group of recursive tasks: the tasks and their join in the function, the parallel region
        around each call that enters the recursion (see ``__get_parallel_region_of_tasks_pragmas``).

        The tasks lack a cutoff: without one, every level of the recursion creates tasks, down to the smallest calls,
        and the overhead outweighs the work. The condition depends on the meaning of the function's arguments, which the
        profile does not show, so the task pragmas carry a comment instead (it compiles) for the reader to replace by a
        ``final(<condition>)`` clause."""
        reductions: Dict[str, List[str]] = {}
        for task in tasks:
            for entry in task.get("reduction") or []:
                operation, _, name = str(entry).partition(":")
                if name not in reductions.setdefault(operation, []):
                    reductions[operation].append(name)
        top: List[Pragma] = []
        inner = top
        if reductions:
            # the taskgroup waits for the tasks: it is the join
            clauses = " ".join("task_reduction(" + op + ":" + ",".join(names) + ")" for op, names in reductions.items())
            group = line_pragma("#pragma omp taskgroup " + clauses, region_start, PragmaPosition.BEFORE_START)
            top.append(group)
            inner = group.children
            inner.append(line_pragma("{", region_start, PragmaPosition.BEFORE_START))
        unnamed = {int(d["to_task"]) for d in (self.values.get("task_dependences") or []) if not d.get("variable")}
        for task in tasks:
            if task["pattern_id"] in unnamed:
                inner.append(
                    line_pragma("#pragma omp taskwait", int(task["region_start_line"]), PragmaPosition.BEFORE_START)
                )
            task_pragmas = UnpackedSuggestion("task", task).get_pragmas(None)
            for pragma in task_pragmas:
                if pragma.pragma_str.startswith("#pragma omp task"):
                    pragma.pragma_str += RECURSIVE_TASK_CUTOFF_MARKER
            inner += task_pragmas
        if reductions:
            inner.append(line_pragma("}", region_end, PragmaPosition.AFTER_END))
        else:
            top.append(line_pragma("#pragma omp taskwait", region_end, PragmaPosition.AFTER_END))
        for entry_file, entry_line in entry_lines:
            parallel = line_pragma(self.values["pragma"][0], entry_line, PragmaPosition.BEFORE_START)
            parallel.file_id = entry_file
            single = line_pragma(self.values["pragma"][1], entry_line, PragmaPosition.BEFORE_START)
            single.file_id = entry_file
            parallel.children.append(single)
            top.append(parallel)
        return top

    def __get_task_pragmas(self, contained_patterns: Optional[Dict[str, List[str]]]) -> List[Pragma]:
        pragmas: List[Pragma] = []
        if self.values["type"] == "TASKLOOP":
            pragma = Pragma()
            pragma.file_id = self.file_id
            pragma.start_line = self.start_line
            pragma.end_line = self.end_line
            pragma.pragma_str = " ".join(self.values["pragma"])
            pragmas.append(pragma)
        elif self.values["type"] == "TASK":
            pragma = Pragma()
            pragma.file_id = self.file_id
            pragma.start_line = int(self.values["region_start_line"])  # self.start_line
            pragma.end_line = int(self.values["region_end_line"])  # self.end_line
            pragma.pragma_str += (
                " ".join(self.values["pragma"])
                + self.__task_data_sharing_clauses()
                + self.__task_reduction_clauses()
                + self.__task_depend_clauses()
            )
            pragmas.append(pragma)
        elif self.values["type"] == "PARALLELREGION":
            pragmas += self.__get_parallel_region_of_tasks_pragmas(contained_patterns)
        elif self.values["type"] == "TASKWAIT":
            pragma = Pragma()
            pragma.file_id = self.file_id
            pragma.start_line = self.start_line
            pragma.end_line = self.end_line
            pragma.pragma_str = " ".join(self.values["pragma"])
            pragma.pragma_position = PragmaPosition.AFTER_START
            pragmas.append(pragma)
        else:
            raise ValueError("Unknown task type: " + self.values["type"])

        return pragmas

    def __get_pipeline_pragmas(self) -> List[Pragma]:
        pragmas = []

        for stage in self.values["stages"]:
            pragma = Pragma()
            pragma.file_id = self.file_id
            pragma.start_line = int(stage["startsAtLine"].split(":")[1])
            pragma.end_line = int(stage["endsAtLine"].split(":")[1])
            pragma.pragma_str = "#pragma omp task "
            if len(stage["first_private"]) > 0:
                pragma.pragma_str += "firstprivate(" + ",".join(stage["first_private"]) + ") "
            if len(stage["private"]) > 0:
                pragma.pragma_str += "private(" + ",".join(stage["private"]) + ") "
            if len(stage["shared"]) > 0:
                pragma.pragma_str += "shared(" + ",".join(stage["shared"]) + ") "
            if len(stage["reduction"]) > 0:
                reductions_dict: Dict[str, List[str]] = dict()
                for entry in stage["reduction"]:
                    red_type: str = entry.split(":")[0]
                    var: str = entry.split(":")[1]
                    if red_type not in reductions_dict:
                        reductions_dict[red_type] = []
                    reductions_dict[red_type].append(var)
                for red_type in reductions_dict:
                    pragma.pragma_str += "reduction(" + red_type + ":" + ",".join(reductions_dict[red_type]) + ") "
            if len(stage["in_deps"]) > 0:
                pragma.pragma_str += "depends(in:" + ",".join(stage["in_deps"]) + ") "
            if len(stage["out_deps"]) > 0:
                pragma.pragma_str += "depends(out:" + ",".join(stage["out_deps"]) + ") "
            if len(stage["in_out_deps"]) > 0:
                pragma.pragma_str += "depends(inout:" + ",".join(stage["in_out_deps"]) + ") "
            pragmas.append(pragma)
        return pragmas

    def __get_simple_gpu_pragmas(
        self,
        region_start: Any,
        region_end: Any,
        contained_loops: Any,
        map_to_vars: Any,
        map_from_vars: Any,
        map_to_from_vars: Any,
        map_alloc_vars: Any,
        map_delete_vars: Any,
        consumed_vars: Any,
        produced_vars: Any,
        indentation: int = 0,
        ignore_mapping_clauses: bool = False,
    ) -> List[Pragma]:
        pragmas = []

        _region_start_line = int(region_start.split(":")[1])
        _region_end_line = int(region_end.split(":")[1])
        for loop in contained_loops:
            loop_start = loop["start_line"]
            loop_start_line = int(loop_start.split(":")[1])
            loop_end = loop["end_line"]
            loop_end_line = int(loop_end.split(":")[1])
            loop_pragma = Pragma()
            loop_pragma.start_line = loop_start_line
            loop_pragma.end_line = loop_end_line
            loop_pragma.file_id = int(loop_start.split(":")[0])
            for construct in loop["constructs"]:
                construct_start = construct["line"]
                mark_invalid = False
                if ":" not in construct_start:
                    # invalid construct, line has no position
                    mark_invalid = True
                    construct_start = loop_start
                construct_start_line = int(construct_start.split(":")[1])
                child_pragma = Pragma()
                if mark_invalid:
                    child_pragma.pragma_str = "// INVALID - MISSING POSITION:: " + construct["name"] + " "
                else:
                    child_pragma.pragma_str = construct["name"] + " "
                if loop["collapse"] > 1:
                    child_pragma.pragma_str += "collapse(" + str(loop["collapse"]) + ") "
                for clause in construct["clauses"]:
                    if ignore_mapping_clauses:
                        if clause.startswith("map("):
                            continue
                    child_pragma.pragma_str += clause + " "
                # determine start_line and end_line
                if construct_start_line == loop_start_line:
                    # if construct targets loop, use loop scope
                    start_line = loop_start_line
                    end_line = loop_end_line
                elif loop_start_line <= construct_start_line <= loop_end_line:
                    # if construct is inside loop scope, start at construct line and end at loop scope
                    # (should not be used currently)
                    start_line = construct_start_line
                    end_line = loop_end_line
                else:
                    # else, use construct line
                    start_line = construct_start_line
                    end_line = construct_start_line
                # determine positioning of the pragma
                if construct["positioning"] == OmpConstructPositioning.BEFORE_LINE:
                    child_pragma.pragma_position = PragmaPosition.BEFORE_START
                elif construct["positioning"] == OmpConstructPositioning.AFTER_LINE:
                    child_pragma.pragma_position = PragmaPosition.AFTER_START
                else:
                    raise ValueError("Unsupported positioning information: ", construct["positioning"])
                # create pragma for visualization
                child_pragma.start_line = start_line
                child_pragma.end_line = end_line
                child_pragma.file_id = self.file_id
                loop_pragma.children.append(child_pragma)
            pragmas.append(loop_pragma)
        return pragmas

    def __get_update_pragmas(self, update_instructions: List[Tuple[str, str, UpdateType, str, str]]) -> List[Pragma]:
        pragmas = []
        for source_cu_id, sink_cu_id, update_type, target_var, pragma_line in update_instructions:
            pragma = Pragma()
            pragma.pragma_str = "#pragma omp target update "

            if update_type == UpdateType.TO_DEVICE:
                # to device means host is writing, so update after the instruction
                pragma.pragma_position = PragmaPosition.BEFORE_START  # PragmaPosition.AFTER_END
                pragma.pragma_str += "to("
            elif update_type == UpdateType.FROM_DEVICE:
                # from device means host is reading, so update before the instruction
                pragma.pragma_position = PragmaPosition.BEFORE_START
                pragma.pragma_str += "from("
            elif update_type == UpdateType.ALLOCATE:
                # allocate memory, not written to before
                pragma.pragma_position = PragmaPosition.BEFORE_START
                pragma.pragma_str += "alloc("
            else:
                raise ValueError("Unsupported update type: ", update_type)
            pragma.pragma_str += target_var + ") "
            pragma.pragma_str += " // @CU " + source_cu_id + " -> " + sink_cu_id + " "
            pragma_line_num = int(pragma_line.split(":")[1])
            pragma.start_line = pragma_line_num
            pragma.end_line = pragma_line_num
            pragma.file_id = self.file_id
            pragmas.append(pragma)
        return pragmas

    def __get_data_region_dependencies(
        self, depend_in: List[Tuple[str, str, str]], depend_out: List[Tuple[str, str, str]]
    ) -> List[Pragma]:
        pragmas = []
        for var_name, cu_id, pragma_line in depend_in:
            pragma = Pragma()
            pragma.pragma_str = "#depend in(" + var_name + ") @ " + cu_id + " "
            pragma_line_num = int(pragma_line.split(":")[1])
            pragma.start_line = pragma_line_num
            pragma.end_line = pragma_line_num
            pragma.file_id = self.file_id
            pragma.pragma_position = PragmaPosition.BEFORE_START
            pragmas.append(pragma)

        for var_name, cu_id, pragma_line in depend_out:
            pragma = Pragma()
            pragma.pragma_str = "#depend out(" + var_name + ") @ " + cu_id + " "
            pragma_line_num = int(pragma_line.split(":")[1])
            pragma.start_line = pragma_line_num
            pragma.end_line = pragma_line_num
            pragma.file_id = self.file_id
            pragma.pragma_position = PragmaPosition.BEFORE_START
            pragmas.append(pragma)

        return pragmas

    def __get_data_region_pragmas(
        self,
        entry_points: List[Tuple[str, str, str, EntryPointType, str, EntryPointPositioning]],
        exit_points: List[Tuple[str, str, str, ExitPointType, str, ExitPointPositioning]],
    ) -> List[Pragma]:
        pragmas = []
        for (
            var_name,
            source_cu_id,
            sink_cu_id,
            entry_point_type,
            pragma_line,
            entry_point_positioning,
        ) in entry_points:
            pragma = Pragma()
            pragma.pragma_str = "#pragma omp target enter data "
            if entry_point_type == EntryPointType.TO_DEVICE:
                pragma.pragma_str += "map(to: "
            elif entry_point_type == EntryPointType.ALLOCATE:
                pragma.pragma_str += "map(alloc: "
            elif entry_point_type == EntryPointType.ASYNC_TO_DEVICE:
                pragma.pragma_str += "nowait map(to: "
            elif entry_point_type == EntryPointType.ASYNC_ALLOCATE:
                pragma.pragma_str += "nowait map(alloc:"
            else:
                raise ValueError("Usupported EntryPointType: ", entry_point_type)
            pragma.pragma_str += var_name + ") "
            pragma.pragma_str += " // @CU " + source_cu_id + " -> " + sink_cu_id + " "
            pragma_line_num = int(pragma_line.split(":")[1])
            pragma.start_line = pragma_line_num
            pragma.end_line = pragma_line_num
            pragma.file_id = self.file_id
            if entry_point_positioning == EntryPointPositioning.BEFORE_CU:
                pragma.pragma_position = PragmaPosition.BEFORE_START
            elif entry_point_positioning == EntryPointPositioning.AFTER_CU:
                pragma.pragma_position = PragmaPosition.AFTER_END
            else:
                raise ValueError("Usupported ExitPointPositioning: ", entry_point_positioning)
            pragmas.append(pragma)

        for (
            var_name,
            source_cu_id,
            sink_cu_id,
            exit_point_type,
            pragma_line,
            exit_point_positioning,
        ) in exit_points:
            pragma = Pragma()
            pragma.pragma_str = "#pragma omp target exit data "
            if exit_point_type == ExitPointType.FROM_DEVICE:
                pragma.pragma_str += "map(from: "
            elif exit_point_type == ExitPointType.DELETE:
                pragma.pragma_str += "map(delete: "
            elif exit_point_type == ExitPointType.ASYNC_FROM_DEVICE:
                pragma.pragma_str += "nowait map(from: "
            else:
                raise ValueError("Usupported ExitPointType: ", exit_point_type)
            pragma.pragma_str += var_name + ") "
            pragma.pragma_str += " // @CU " + source_cu_id + " -> " + sink_cu_id + " "
            pragma_line_num = int(pragma_line.split(":")[1])
            pragma.start_line = pragma_line_num
            pragma.end_line = pragma_line_num
            pragma.file_id = self.file_id
            if exit_point_positioning == ExitPointPositioning.BEFORE_CU:
                pragma.pragma_position = PragmaPosition.BEFORE_START
            elif exit_point_positioning == ExitPointPositioning.AFTER_CU:
                pragma.pragma_position = PragmaPosition.AFTER_END
            else:
                raise ValueError("Usupported ExitPointPositioning: ", exit_point_positioning)
            pragmas.append(pragma)
        return pragmas

    def __get_combined_gpu_pragmas(self) -> List[Pragma]:
        pragmas = []
        # add async data movement
        pragmas += self.__get_data_region_pragmas(
            self.values["data_region_entry_points"], self.values["data_region_exit_points"]
        )
        # add dependencies
        pragmas += self.__get_data_region_dependencies(
            self.values["data_region_depend_in"], self.values["data_region_depend_out"]
        )

        # add update instructions to pragmas
        pragmas += self.__get_update_pragmas(self.values["update_instructions"])

        # add gpu loops
        for region in self.values["contained_regions"]:
            pragmas += self.__get_simple_gpu_pragmas(
                region["start_line"],
                region["end_line"],
                region["contained_loops"],
                region["map_to_vars"],
                region["map_from_vars"],
                region["map_to_from_vars"],
                region["map_alloc_vars"],
                region["map_delete_vars"],
                region["consumed_vars"],
                region["produced_vars"],
                indentation=0,
                ignore_mapping_clauses=True,
            )

        return pragmas

    def __get_parallel_region_pragmas(self, contained_patterns: Optional[Dict[str, List[str]]]) -> List[Pragma]:
        pragmas: List[Pragma] = []

        # omp parallel pragma
        pragma = Pragma()
        pragma.file_id = self.file_id
        pragma.start_line = self.start_line
        pragma.end_line = self.end_line
        pragma.pragma_position = PragmaPosition.BEFORE_START
        pragma.pragma_str = self.values["pragma"]
        if len(self.values["shared_vars"]) > 0:
            pragma.pragma_str += " shared("
            pragma.pragma_str += ",".join(self.values["shared_vars"])
            pragma.pragma_str += ")"

        # open bracket
        pragma_open_bracket = Pragma()
        pragma_open_bracket.file_id = self.file_id
        pragma_open_bracket.start_line = self.start_line
        pragma_open_bracket.end_line = self.end_line
        pragma_open_bracket.pragma_position = PragmaPosition.BEFORE_START
        pragma_open_bracket.pragma_str = "{"

        # closed bracket
        pragma_closing_bracket = Pragma()
        pragma_closing_bracket.file_id = self.file_id
        pragma_closing_bracket.start_line = self.start_line
        pragma_closing_bracket.end_line = self.end_line
        pragma_closing_bracket.pragma_position = PragmaPosition.BEFORE_END
        pragma_closing_bracket.pragma_str = "}"

        # add contained pragmas as children
        child_pragmas: List[Pragma] = []
        if contained_patterns is not None:
            for contained_pattern_id in self.values["contains_patterns"]:
                for pattern_type in contained_patterns:
                    for pattern_str in contained_patterns[pattern_type]:
                        pattern_dict = json.loads(pattern_str)
                        if pattern_dict["pattern_id"] == contained_pattern_id:
                            ups = UnpackedSuggestion(pattern_type, pattern_dict)
                            child_pragmas += ups.get_pragmas(contained_patterns)

        pragmas.append(pragma)
        pragmas.append(pragma_open_bracket)
        # due to positioning, child pragmas are added individually instead of via the pragma.children interface
        for cp in child_pragmas:
            pragmas.append(cp)
        pragmas.append(pragma_closing_bracket)

        return pragmas

    def get_pragmas(self, contained_patterns: Optional[Dict[str, List[str]]]) -> List[Pragma]:
        """returns a list of source code lines and pragmas to be inserted into the code preview"""
        pragmas = []

        if self.type in ["do_all", "reduction", "gpu_do_all", "gpu_reduction"]:
            execute_on_gpu = "gpu_" in self.type or self.device_type == DeviceTypeEnum.GPU
            pragmas += self.__get_do_all_and_reduction_pragmas(execute_on_gpu)
            return pragmas
        elif self.type == "task":
            pragmas += self.__get_task_pragmas(contained_patterns=contained_patterns)
        elif self.type == "pipeline":
            pragmas += self.__get_pipeline_pragmas()
        elif self.type == "simple_gpu":
            pragmas += self.__get_simple_gpu_pragmas(
                self.values["start_line"],
                self.values["end_line"],
                self.values["contained_loops"],
                self.values["map_to_vars"],
                self.values["map_from_vars"],
                self.values["map_to_from_vars"],
                self.values["map_alloc_vars"],
                self.values["map_delete_vars"],
                self.values["consumed_vars"],
                self.values["produced_vars"],
            )
        elif self.type == "combined_gpu":
            pragmas += self.__get_combined_gpu_pragmas()
        elif self.type == "device_update":
            pragmas += self.__get_device_update_pragmas()
        elif self.type == "parallel_region":
            pragmas += self.__get_parallel_region_pragmas(contained_patterns=contained_patterns)
        else:
            pragma = Pragma()
            pragma.file_id = self.file_id
            pragma.start_line = self.start_line
            pragma.end_line = self.end_line
            pragma.pragma_str = "#CURRENTLY UNSUPPORTED PREVIEW FOR TYPE: " + self.type
            pragmas.append(pragma)
        return pragmas

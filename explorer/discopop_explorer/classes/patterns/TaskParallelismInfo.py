# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from enum import Enum
from typing import Any, Dict, List, Optional

from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo


class TPIType(Enum):
    DUMMY = "DUMMY"
    TASK = "TASK"
    TASKWAIT = "TASKWAIT"
    TASKLOOP = "TASKLOOP"
    PARALLELREGION = "PARALLELREGION"


class TaskParallelismInfo(PatternInfo):
    """Class, that contains task parallelism detection result"""

    def __init__(
        self,
        node: Node,
        type: TPIType,
        pragma: List[str],
        pragma_line: str,
        first_private: List[str],
        private: List[str],
        shared: List[str],
    ):
        """
        :param node: node, where task parallelism was detected
        :param type: type of the suggestion (task, taskwait, taskloop)
        :param pragma: pragma to be used (task / taskwait / taskloop)
        :param pragma_line: line prior to which the pragma shall be inserted
        :param first_private: list of varNames
        :param private: list of varNames
        :param shared: list of varNames
        """
        PatternInfo.__init__(self, node)
        self.type = type
        self.pragma = pragma
        self.pragma_line = pragma_line
        if ":" in self.pragma_line:
            self.region_start_line = self.pragma_line[self.pragma_line.index(":") + 1 :]
        else:
            self.region_start_line = self.pragma_line
        self.region_end_line: Optional[str] = None
        self.first_private = first_private
        self.private = private
        self.shared = shared
        self.in_dep: List[str] = []
        self.out_dep: List[str] = []
        self.in_out_dep: List[str] = []
        self.critical_sections: List[str] = []
        self.atomic_sections: List[str] = []
        self.task_group: List[int] = []
        # the instructions of the task (instruction ids of this build), see design/instruction_focus.md
        self.instruction_ids: List[int] = []
        # set if one task is created per iteration of a loop: the line of the loop (file id:line)
        self.loop_start_line: Optional[str] = None

    def __str__(self) -> str:
        return (
            f"Task parallelism at CU: {self.node_id}\n"
            f"CU Start line: {self.start_line}\n"
            f"CU End line: {self.end_line}\n"
            f"pragma at line: {self.pragma_line}\n"
            f"pragma region start line: {self.region_start_line}\n"
            f"pragma region end line: {self.region_end_line}\n"
            f'pragma: "#pragma omp {" ".join(self.pragma)}"\n'
            f'first_private: {" ".join(self.first_private)}\n'
            f'private: {" ".join(self.private)}\n'
            f'shared: {" ".join(self.shared)}\n'
            f'in_dep: {" ".join(self.in_dep)}\n'
            f'out_dep: {" ".join(self.out_dep)}\n'
            f'in_out_dep: {" ".join(self.in_out_dep)}\n'
            f'critical_sections: {" ".join(self.critical_sections)}\n'
            f'atomic_sections: {" ".join(self.atomic_sections)}\n'
            f'task_group: {" ".join([str(e) for e in self.task_group])}\n'
        )


class ParallelRegionInfo(PatternInfo):
    """Class, that contains parallel region info."""

    def __init__(
        self,
        node: Node,
        type: TPIType,
        region_start_line: int,
        region_end_line: int,
        task_group: Optional[List[int]] = None,
        contained_tasks: Optional[List[TaskParallelismInfo]] = None,
    ):
        PatternInfo.__init__(self, node)
        self.region_start_line = str(region_start_line)
        self.region_end_line = str(region_end_line)
        self.pragma = ["#pragma omp parallel", "#pragma omp single"]
        self.type = type
        self.task_group: List[int] = [] if task_group is None else task_group
        self.contains_patterns: List[int] = [] if contained_tasks is None else [t.pattern_id for t in contained_tasks]
        # the instructions of the contained tasks (instruction ids of this build)
        self.instruction_ids: List[int] = list(
            dict.fromkeys(i for t in (contained_tasks or []) for i in t.instruction_ids)
        )
        # set if the tasks are created per iteration of a loop: the line of the loop (file id:line)
        self.loop_start_line: Optional[str] = None
        # a later task depends on an earlier one: {"from_task", "to_task" (pattern ids), "variable", "kind": RAW | WAR}
        self.task_dependences: List[Dict[str, Any]] = []
        # the code after the region depends on a task: {"task" (pattern id), "variable", "kind": RAW | WAR, "line"}
        self.after_dependences: List[Dict[str, Any]] = []

    def __str__(self) -> str:
        return (
            f"Task Parallel Region at CU: {self.node_id}\n"
            f"CU Start line: {self.start_line}\n"
            f"CU End line: {self.end_line}\n"
            f"pragma: \n\t{self.pragma}\n"
            f"Parallel Region Start line: {self.region_start_line}\n"
            f"Parallel Region End line {self.region_end_line}\n"
        )

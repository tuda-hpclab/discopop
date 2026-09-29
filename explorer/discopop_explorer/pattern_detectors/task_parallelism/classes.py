# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from enum import Enum
from typing import List, Optional

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.enums.MWType import MWType
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo

# We decided to omit the information that computes the workload and the relevant codes. For large programs (e.g., ffmpeg), the generated Data.xml file becomes very large. However, we keep the code here because we would like to integrate a hotspot detection algorithm (TODO: Bertin) with the parallelism discovery. Then, we need to retrieve the information to decide which code sections (loops or functions) are worth parallelizing.
# from discopop_explorer.utilities import total_instructions_count, calculate_workload


class Task(object):
    """This class represents task in task parallelism pattern"""

    nodes: List[Node]
    child_tasks: List["Task"]
    start_line: LineID
    end_line: LineID

    def __init__(self, pet: PEGraphX, node: Node):
        self.node_id = node.id
        self.nodes = [node]
        self.start_line = node.start_position()
        if ":" in self.start_line:
            self.region_start_line = self.start_line[self.start_line.index(":") + 1 :]
        else:
            self.region_start_line = self.start_line
        self.region_end_line = None
        self.end_line = node.end_position()
        self.mw_type = node.mw_type

        # We decided to omit the information that computes the workload and the relevant codes. For large programs (e.g., ffmpeg),
        # the generated Data.xml file becomes very large. However, we keep the code here because we would like to integrate a
        # hotspot detection algorithm (TODO: Bertin) with the parallelism discovery.
        # Then, we need to retrieve the information to decide which code sections (loops or functions) are worth parallelizing.
        #        self.instruction_count = total_instructions_count(pet, node)
        #        self.workload = calculate_workload(pet, node)
        self.instruction_count = 0
        self.workload = 0
        self.child_tasks = []

    def aggregate(self, other: "Task") -> None:
        """Aggregates given task into current task

        :param other: task to aggregate
        """
        self.nodes.extend(other.nodes)
        self.end_line = other.end_line
        self.workload += other.workload
        self.instruction_count += other.instruction_count
        self.mw_type = MWType.BARRIER_WORKER if other.mw_type == MWType.BARRIER_WORKER else MWType.WORKER


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

    def __str__(self) -> str:
        return (
            f"Task Parallel Region at CU: {self.node_id}\n"
            f"CU Start line: {self.start_line}\n"
            f"CU End line: {self.end_line}\n"
            f"pragma: \n\t{self.pragma}\n"
            f"Parallel Region Start line: {self.region_start_line}\n"
            f"Parallel Region End line {self.region_end_line}\n"
        )


class OmittableCuInfo(PatternInfo):
    """Class, that contains information on omittable CUs (such that can be
    combined with a suggested task).
    Objects of this type are only intermediate and will not show up in the
    final suggestions.
    """

    def __init__(self, node: Node, combine_with_node: Node):
        PatternInfo.__init__(self, node)
        self.combine_with_node = combine_with_node
        # only for printing
        self.cwn_id = combine_with_node.id
        self.in_dep: List[Optional[str]] = []
        self.out_dep: List[Optional[str]] = []
        self.in_out_dep: List[Optional[str]] = []

    def __str__(self) -> str:
        return (
            f"Omittable CU: {self.node_id}\n"
            f"CU Start line: {self.start_line}\n"
            f"CU End line: {self.end_line}\n"
            f"Combinable with: {self.cwn_id}\n"
            f'in_dep: {" ".join([str(s) for s in self.in_dep])}\n'
            f'out_dep: {" ".join([str(s) for s in self.out_dep])}\n'
            f'in_out_dep: {" ".join([str(s) for s in self.in_out_dep])}\n'
        )

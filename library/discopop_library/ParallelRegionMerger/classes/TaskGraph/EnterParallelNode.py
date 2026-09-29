# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import List
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TGNode import TGNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TaskNode import TaskNode
from discopop_explorer.classes.variable import Variable


class EnterParallelNode(TGNode):
    parallel_region_id: int
    shared_vars: List[Variable]

    def __init__(
        self,
        par_reg_id: int,
        shared_vars: List[Variable],
        first_contained_task: TaskNode,
        last_contained_task: TaskNode,
    ) -> None:
        super().__init__()
        self.parallel_region_id = par_reg_id
        self.shared_vars = shared_vars
        self.first_contained_task = first_contained_task
        self.last_contained_task = last_contained_task

    def get_label(self) -> str:
        clauses = self.get_clauses()
        res = "enter " + str(self.parallel_region_id)
        if len(clauses) > 0:
            res += " " + clauses
        return res

    def get_clauses(self) -> str:
        res = ""
        if len(self.shared_vars) > 0:
            res += "shared(" + ",".join([v.name + "{" + v.defLine + "}" for v in self.shared_vars]) + ")"
        return res

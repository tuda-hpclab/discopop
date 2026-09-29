# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.Contexts.TaskEndContext import TaskEndContext


class TaskParentContext(Context):
    task_end_context: Optional[TaskEndContext] = None
    registered_tasks: List[Context]
    pass

    def __init__(self) -> None:
        super().__init__()
        self.registered_tasks = []

    def get_plot_border_color(self) -> str:
        return "r"

    def get_plot_face_color(self) -> str:
        return "yellow"

    def get_label(self) -> str:
        return "TaskParent"

    def set_task_end(self, task_end_context: TaskEndContext) -> None:
        self.task_end_context = task_end_context

    def register_task(self, task: Context) -> None:
        self.registered_tasks.append(task)

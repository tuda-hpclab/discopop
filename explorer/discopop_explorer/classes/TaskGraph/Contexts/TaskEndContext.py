# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from discopop_explorer.classes.TaskGraph.Contexts.TaskParentContext import TaskParentContext


class TaskEndContext(Context):
    task_parent_context: Optional[TaskParentContext] = None
    pass

    def __init__(self) -> None:
        super().__init__()

    def get_plot_border_color(self) -> str:
        return "r"

    def get_plot_face_color(self) -> str:
        return "yellow"

    def get_label(self) -> str:
        return "TaskEnd"

    def set_task_parent(self, task_parent_context: TaskParentContext) -> None:
        self.task_parent = task_parent_context

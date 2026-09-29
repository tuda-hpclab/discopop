# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Optional
from discopop_library.ParallelRegionMerger.classes.TaskGraph.Edge import Edge


class DataflowEdge(Edge):
    var_name: Optional[str]

    def __init__(self, var_name: Optional[str] = None) -> None:
        super().__init__()
        self.var_name = var_name

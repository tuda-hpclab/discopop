# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TGNode import TGNode


class ExitParallelNode(TGNode):
    parallel_region_id: int

    def __init__(self, par_reg_id: int) -> None:
        super().__init__()
        self.parallel_region_id = par_reg_id

    def get_label(self) -> str:
        return "exit " + str(self.parallel_region_id)

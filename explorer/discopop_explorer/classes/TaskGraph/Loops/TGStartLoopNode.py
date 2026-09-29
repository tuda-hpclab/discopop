# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import Optional

from discopop_explorer.classes.TaskGraph.TGNode import TGNode


class TGStartLoopNode(TGNode):
    # loop state position corresponds to the position of the iteration count for the specific loop within the "_loopstate"-information in the callpaths reported by the profiler
    loopstate_position: Optional[int] = None

    def get_label(self) -> str:
        return "Start Loop " + str(self.pet_node_id)

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from discopop_explorer.classes.TaskGraph.TGNode import TGNode


class TGStartBranchParentNode(TGNode):
    pass

    def get_label(self) -> str:
        return "Start BranchParent"

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.pattern_detectors.simple_gpu_patterns.GPULoop import GPULoopPattern


def sort_by_nodeID(e: GPULoopPattern) -> NodeID:
    """used to sort a list of gpu patterns by their node ids

    :return:
    :param e:
    """
    return e.nodeID

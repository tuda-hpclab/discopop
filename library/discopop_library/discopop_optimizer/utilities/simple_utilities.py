# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_library.discopop_optimizer.classes.nodes.GenericNode import GenericNode


import networkx as nx  # type: ignore


from typing import cast


def data_at(graph: nx.DiGraph, node_id: int) -> GenericNode:
    """Return the data object stored at the networkx node with id node_id."""
    return cast(GenericNode, graph.nodes[node_id]["data"])

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.enums.EdgeType import EdgeType
import networkx as nx  # type: ignore


def dump_to_gephi_file(pet: PEGraphX, name: str) -> None:
    """Note: Destroys the PETGraph!"""
    # replace node data with label
    for node_id in pet.g.nodes:
        tmp_cu = pet.g.nodes[node_id]["data"]
        del pet.g.nodes[node_id]["data"]
        pet.g.nodes[node_id]["id"] = tmp_cu.id
        pet.g.nodes[node_id]["type"] = str(tmp_cu.type)
    for edge in pet.g.edges:
        dep: Dependency = pet.g.edges[edge]["data"]
        del pet.g.edges[edge]["data"]
        pet.g.edges[edge]["edge_type"] = str(dep.etype.name)
        if dep.etype == EdgeType.DATA:
            pet.g.edges[edge]["var"] = dep.var_name
            if dep.dtype is None:
                raise ValueError("dep.dtype has no type name!")
            pet.g.edges[edge]["dep_type"] = str(dep.dtype.name)
    nx.write_gexf(pet.g, name)

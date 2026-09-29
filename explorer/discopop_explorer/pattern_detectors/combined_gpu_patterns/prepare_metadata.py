# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Set, List, Tuple

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Dependency import Dependency


def get_dependencies_as_metadata(pet: PEGraphX, all_dependencies: Set[Dependency]) -> Tuple[
    List[Tuple[VarName, NodeID, str]],
    List[Tuple[VarName, NodeID, str]],
]:
    in_deps_metadata: Set[Tuple[VarName, NodeID, str]] = set()
    out_deps_metadata: Set[Tuple[VarName, NodeID, str]] = set()

    for dependency in all_dependencies:
        # create out dependency metadata
        for var_name in dependency.var_names:
            out_deps_metadata.add(
                (
                    var_name,
                    dependency.source,
                    pet.node_at(dependency.source).end_position(),
                )
            )

        # create in dependency metadata
        for var_name in dependency.var_names:
            in_deps_metadata.add(
                (
                    var_name,
                    dependency.sink,
                    pet.node_at(dependency.sink).start_position(),
                )
            )

    return list(in_deps_metadata), list(out_deps_metadata)

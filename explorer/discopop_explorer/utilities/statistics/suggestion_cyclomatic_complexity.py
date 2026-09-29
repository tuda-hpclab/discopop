# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

from typing import Dict, TYPE_CHECKING, Set

from discopop_explorer.utilities.statistics.cyclomatic_complexity.cc_dictionary import (
    get_cyclomatic_complexity_dictionary,
)
from discopop_explorer.utilities.statistics.cyclomatic_complexity.subtree import (
    get_subtree_cyclomatic_complexity_from_calls,
)

if TYPE_CHECKING:
    from discopop_explorer.discopop_explorer import ExplorerArguments
    from discopop_library.result_classes.DetectionResult import DetectionResult
    from discopop_explorer.aliases.NodeID import NodeID


def get_suggestion_summed_cyclomatic_complexity_from_calls(
    arguments: ExplorerArguments, res: DetectionResult
) -> Dict[int, int]:
    res_dict: Dict[int, int] = dict()
    cc_dict = get_cyclomatic_complexity_dictionary(arguments, res)

    # collect NodeIDs where suggestions are located
    for pattern_type in res.patterns.__dict__:
        for pattern in res.patterns.__dict__[pattern_type]:
            res_dict[pattern.pattern_id] = get_subtree_cyclomatic_complexity_from_calls(
                arguments, res, cc_dict, pattern.node_id
            )

    return res_dict

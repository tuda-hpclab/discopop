# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
from typing import TYPE_CHECKING
from discopop_explorer.aliases.LineID import LineID

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX


def is_reduction_var_by_name(self: PEGraphX, line: LineID, name: str) -> bool:
    """Determines, whether or not the given variable is reduction variable

    :param line: loop line number
    :param name: variable name
    :return: true if is reduction variable
    """
    return any(rv for rv in self.reduction_vars if rv["loop_line"] == line and rv["name"] == name)

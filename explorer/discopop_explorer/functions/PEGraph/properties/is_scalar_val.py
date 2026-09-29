# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.variable import Variable


def is_scalar_val(pet: PEGraphX, allVars: List[Variable], var: str) -> bool:
    """Checks if variable is a scalar value

    :param var: variable
    :return: true if scalar
    """
    for x in allVars:
        if x.name == var:
            return not (x.type.endswith("**") or x.type.startswith("ARRAY") or x.type.startswith("["))
        else:
            return False
    raise ValueError("allVars must not be empty.")

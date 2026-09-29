# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX


def get_reduction_sign(pet: PEGraphX, line: str, name: str) -> str:
    """Returns reduction operation for variable

    :param line: loop line number
    :param name: variable name
    :return: reduction operation
    """
    for rv in pet.reduction_vars:
        if rv["loop_line"] == line and rv["name"] == name:
            return rv["operation"]
    return ""

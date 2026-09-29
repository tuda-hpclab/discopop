# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import cast

import jsonpickle  # type: ignore

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX


def dump_to_pickled_json(self: PEGraphX) -> str:
    """Encodes and returns the entire Object into a pickled json string.
    The encoded string can be reconstructed into an object by using:
    jsonpickle.decode(json_str, keys=True)

    :return: encoded string
    """
    return cast(str, jsonpickle.encode(self, keys=True))

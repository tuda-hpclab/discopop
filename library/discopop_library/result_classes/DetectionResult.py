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
from discopop_library.global_data.version.utils import get_version
from discopop_library.result_classes.PatternStorage import PatternStorage


class DetectionResult(object):
    version: str
    pet: PEGraphX
    patterns: PatternStorage

    def __init__(self, pet: PEGraphX):
        self.version = get_version()  # discopop version
        self.pet = pet
        self.patterns = PatternStorage()
        pass

    def __str__(self) -> str:
        result_str = ""
        for v in self.__dict__.values():
            if type(v) == PEGraphX:
                continue
            value_str = "\n\n\n"
            for entry in v:
                try:
                    value_str += str(entry) + "\n\n"
                except NotImplementedError:
                    value_str += entry.to_string(self.pet) + "\n\n"
            result_str += value_str
        return result_str

    def dump_to_pickled_json(self) -> str:
        """Encodes and returns the entire Object into a pickled json string.
        The encoded string can be reconstructed into an object by using:
        jsonpickle.decode(json_str, keys=True)

        :return: encoded string
        """
        return cast(str, jsonpickle.encode(self, keys=True))

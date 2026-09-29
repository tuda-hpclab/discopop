# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from json import JSONEncoder
from typing import Dict, Any
from discopop_explorer.classes.patterns.PatternBase import PatternBase
from discopop_library.discopop_optimizer.classes.context.Update import Update
from discopop_library.discopop_optimizer.classes.types.DataAccessType import WriteDataAccess

from discopop_library.result_classes.DetectionResult import DetectionResult
from discopop_library.result_classes.PatternStorage import PatternStorage
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.pattern_detectors.pipeline_detector import PipelineStage
from discopop_explorer.pattern_detectors.task_parallelism.classes import TPIType
from discopop_explorer.classes.variable import Variable


def filter_members(d: Dict[Any, Any]) -> Dict[Any, Any]:
    """Removes private and protected members (which starts with '_')

    :param d: member dictionary
    :return: member dictionary
    """
    keys = [k for k in d.keys()]
    for key in keys:
        if key.startswith("_"):
            del d[key]
    return d


class PatternBaseSerializer(JSONEncoder):
    """Json Encoder for Pattern Info"""

    def default(self, o: Any) -> Any:
        try:
            iterable = iter(o)
        except TypeError:
            pass
        else:
            return list(iterable)

        if isinstance(o, Variable):
            if o.operation is not None and o.operation != "":
                return f"{o.operation}:{o.name}"
            return o.name
        if isinstance(o, PatternBase):
            return filter_members(o.__dict__)
        if isinstance(o, DetectionResult):
            return filter_members(o.__dict__)
        if isinstance(o, PatternStorage):
            return filter_members(o.__dict__)
        if isinstance(o, PipelineStage):
            return filter_members(o.__dict__)
        if isinstance(o, Update):
            return filter_members(o.__dict__)
        if isinstance(o, WriteDataAccess):
            return filter_members(o.__dict__)
        if isinstance(o, Node):
            return o.id
        if isinstance(o, TPIType):
            return o.value

        # Let the base class default method raise the TypeError
        return JSONEncoder.default(self, o)

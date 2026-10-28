# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class DependenceItem(object):
    sink: Any
    source: Any
    type: Any
    var_name: Any
    memory_region: Any
    is_gep_result_dependency: bool
    # the instruction ids and callpath states of the ends, None for ends recorded without them
    source_instruction_id: Optional[int] = None
    sink_instruction_id: Optional[int] = None
    source_state_id: Optional[str] = None
    sink_state_id: Optional[str] = None
    # TODO improve typing

    def is_equal(self, other: DependenceItem) -> bool:
        return bool(
            self.sink == other.sink
            and self.source == other.source
            and self.type == other.type
            and self.var_name == other.var_name
        )

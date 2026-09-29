# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Optional, List


class Line(object):
    line_num: Optional[int]
    content: str
    owns_region: Optional[int]
    belongs_to_regions: List[int]
    belongs_to_original_line: int

    def __init__(self, parent_line_num: int, line_num: Optional[int] = None, content: str = ""):
        self.line_num = line_num
        self.content = content
        self.owns_region = None
        self.belongs_to_regions = []
        self.belongs_to_original_line = parent_line_num

    def get_indentation(self) -> str:
        return self.content[: len(self.content) - len(self.content.lstrip())]

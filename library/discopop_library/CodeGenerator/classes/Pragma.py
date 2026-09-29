# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Optional, List, Any

from discopop_library.CodeGenerator.classes.Enums import PragmaPosition


class Pragma(object):
    pragma_str: str = ""
    file_id: Optional[int] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None
    pragma_position: PragmaPosition = PragmaPosition.BEFORE_START
    parent_cu_id: str = ""
    children: List[Any] = []

    def __init__(self) -> None:
        self.children = []  # create individual list for each Pragma object to prevent bugs due to mutability

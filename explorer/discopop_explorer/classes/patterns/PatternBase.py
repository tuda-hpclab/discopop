# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
from typing import List, Optional

from filelock import FileLock  # type: ignore
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID

PatternID = int


class PatternBase(object):
    """Base class for pattern info"""

    pattern_id: int
    pattern_tag: str
    _node: Node
    node_id: NodeID
    start_line: LineID
    end_line: LineID
    applicable_pattern: bool
    standalone_pattern: bool
    requires_pattern: List[PatternID]
    affected_cu_ids: List[NodeID]

    def __init__(self, node: Node):
        self.request_pattern_id()
        self._node = node
        self.node_id = node.id
        self.start_line = node.start_position()
        self.end_line = node.end_position()
        self.applicable_pattern = True
        self.standalone_pattern = True
        self.pattern_tag = ""
        self.affected_cu_ids = []

    def request_pattern_id(self) -> None:
        # create a file lock to synchronize processes
        with FileLock(os.path.join(os.getcwd(), "next_free_pattern_id.txt.lock")):
            with open(os.path.join(os.getcwd(), "next_free_pattern_id.txt"), "r+") as f:
                lines = f.readlines()
                f.truncate(0)
                f.seek(0)
                if len(lines) == 0:
                    self.pattern_id = 0
                    f.write(str(0))
                else:
                    for line in lines:
                        line = line.replace("\n", "").replace("\x00", "")
                        self.pattern_id = int(line)
                        f.write(str(self.pattern_id + 1))

    def to_json(self) -> str:
        dic = self.__dict__
        keys = [k for k in dic.keys()]
        for key in keys:
            if key.startswith("_"):
                del dic[key]

        return json.dumps(dic, indent=2, default=lambda o: o.toJSON())  # , default=lambda o: "<not serializable>")

    def get_tag(self) -> str:
        result = "" + self.__class__.__name__
        result += "@" + self.start_line + "-" + self.end_line
        return result

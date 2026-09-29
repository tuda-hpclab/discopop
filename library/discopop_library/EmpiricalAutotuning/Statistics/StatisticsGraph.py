# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from enum import Enum
import logging
import os
import subprocess
from typing import Any
import networkx as nx  # type: ignore

logger = logging.getLogger("StatisticsGraph")


class NodeShape(Enum):
    SQUARE = "square"
    CIRCLE = "circle"
    NONE = "none"
    BOX = "box"


class NodeColor(Enum):
    RED = "red"
    WHITE = "white"
    GREEN = "green"
    ORANGE = "orange"


class StatisticsGraph(object):
    G: nx.DiGraph
    current_node: str = ""

    def __init__(self) -> None:
        self.G = nx.DiGraph()

    def dump_to_dot(self) -> None:
        filename = "dp_autotuner_statistics.dot"
        if os.path.exists(filename):
            os.remove(filename)
        nx.drawing.nx_pydot.write_dot(self.G, filename)

    def output(self) -> None:
        self.dump_to_dot()
        self.create_svg_from_dot()

    def set_root(self, label: str, color: NodeColor = NodeColor.WHITE, shape: NodeShape = NodeShape.NONE) -> None:
        if shape == NodeShape.NONE:
            self.G.add_node(label, color="black", fillcolor=color.value, style="filled")
        else:
            self.G.add_node(label, color="black", fillcolor=color.value, style="filled", shape=shape.value)
        self.current_node = label

    def update_current_node(self, label: str) -> None:
        self.current_node = label

    def add_child(self, child: str, color: NodeColor = NodeColor.WHITE, shape: NodeShape = NodeShape.NONE) -> None:
        if shape == NodeShape.NONE:
            self.G.add_node(child, color="black", fillcolor=color.value, style="filled")
        else:
            self.G.add_node(child, color="black", fillcolor=color.value, shape=shape.value, style="filled")
        self.G.add_edge(self.current_node, child)

    def create_svg_from_dot(self) -> None:

        cmd = "dot -Tsvg dp_autotuner_statistics.dot -o dp_autotuner_statistics.svg"
        res = subprocess.run(
            cmd,
            cwd=os.getcwd(),
            executable="/bin/bash",
            shell=True,
        )
        if res.returncode != 0:
            logger.warning("Failed: dot -Tsvg dp_autotuner_statistics.dot -o dp_autotuner_statistics.svg")
        else:
            logger.info("Updated dp_autotuner_statistics.svg")

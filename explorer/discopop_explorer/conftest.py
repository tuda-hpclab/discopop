# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Shared pytest fixtures for building small in-memory PEGraphX graphs.

These bypass PEGraphX.from_parsed_input (which requires Data.xml/dependency
parsing) so that pattern-detection and PEGraph helper functions can be unit
tested against a hand-built graph.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, Union, cast

import networkx as nx
import pytest

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.DummyNode import DummyNode
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.TaskGraph.TGNode import TGNode
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.enums.NodeType import NodeType

_NODE_CLASSES = {
    NodeType.CU: CUNode,
    NodeType.FUNC: FunctionNode,
    NodeType.LOOP: LoopNode,
    NodeType.DUMMY: DummyNode,
}

# (source_id, target_id, EdgeType) or (source_id, target_id, Dependency)
EdgeSpec = Tuple[str, str, Union[EdgeType, Dependency]]


def _make_node(node_id: str, node_type: NodeType = NodeType.CU, name: str = "cu", **attrs: Any) -> Node:
    """Builds a Node subclass instance matching node_type, e.g. "1:2" -> CUNode(file_id=1, node_id=2)."""
    node = _NODE_CLASSES[node_type](NodeID(node_id))
    node.name = name
    node.start_line = attrs.pop("start_line", 1)
    node.end_line = attrs.pop("end_line", node.start_line)
    if node_type == NodeType.LOOP:
        # normally set by PEGraphX.from_parsed_input's loop-data postprocessing step
        cast(LoopNode, node).loop_data = attrs.pop("loop_data", None)
    for key, value in attrs.items():
        setattr(node, key, value)
    return node


def _build_pet_graph(
    nodes: Sequence[Node],
    edges: Sequence[EdgeSpec] = (),
    reduction_vars: Optional[List[Dict[str, str]]] = None,
) -> PEGraphX:
    """Builds a PEGraphX directly from Node instances and edges, skipping XML parsing."""
    g = nx.MultiDiGraph()
    for node in nodes:
        g.add_node(node.id, data=node)
    for source, target, etype_or_dep in edges:
        dep = etype_or_dep if isinstance(etype_or_dep, Dependency) else Dependency(etype_or_dep)
        g.add_edge(NodeID(source), NodeID(target), data=dep)
    return PEGraphX(g, reduction_vars if reduction_vars is not None else [], pos={})


@pytest.fixture  # type: ignore[misc]
def make_node() -> Any:
    """Factory fixture: make_node(node_id, node_type=NodeType.CU, name="cu", start_line=1, end_line=1, **attrs)."""
    return _make_node


@pytest.fixture  # type: ignore[misc]
def build_pet_graph() -> Any:
    """Factory fixture: build_pet_graph(nodes, edges=(), reduction_vars=None) -> PEGraphX."""
    return _build_pet_graph


def _build_task_graph(pet: PEGraphX, nodes: Sequence[TGNode] = ()) -> TaskGraph:
    """Builds a TaskGraph, bypassing TaskGraph.__init__ (which requires real
    dependency files and profiler output on disk) by constructing it directly
    and only setting the fields that pattern-detection code actually reads:
    .pet, .graph (a plain nx.MultiDiGraph of TGNode instances), and the
    Plottable-required ._visualizer.

    The pet-node-id -> TGNode maps and level/position counters are reset per
    instance just like TaskGraph.__init__ does, so that tests driving the
    construction passes (__visit_pet, __break_cycles, ...) directly do not leak
    nodes into each other via TaskGraph's class-level defaults."""
    tg = object.__new__(TaskGraph)
    tg._visualizer = None
    tg.pet = pet
    tg.graph = nx.MultiDiGraph()
    tg.function_id_map = dict()
    tg.TGNode_pet_node_id_to_tg_node = dict()
    tg.TGFunctionNode_pet_node_id_to_tg_node = dict()
    tg.TGStartFunctionNode_pet_node_id_to_tg_node = dict()
    tg.TGEndFunctionNode_pet_node_id_to_tg_node = dict()
    tg.contexts = []
    tg.current_level = 0
    tg.current_position = {0: 0}
    for node in nodes:
        tg.graph.add_node(node)
    return tg


@pytest.fixture  # type: ignore[misc]
def build_task_graph() -> Any:
    """Factory fixture: build_task_graph(pet, nodes=()) -> TaskGraph."""
    return _build_task_graph


@pytest.fixture  # type: ignore[misc]
def make_tg_node() -> Any:
    """Factory fixture: make_tg_node(pet_node_id, level=0, position=0) -> TGNode."""

    def _make_tg_node(pet_node_id: NodeID, level: int = 0, position: int = 0) -> TGNode:
        return TGNode(pet_node_id, level, position)

    return _make_tg_node


@pytest.fixture  # type: ignore[misc]
def isolated_pattern_id_cwd(tmp_path: Any, monkeypatch: Any) -> Any:
    """Some PatternInfo subclasses (DoAllInfo, ReductionInfo, ...) allocate a pattern id from
    next_free_pattern_id.txt in the current working directory (see PatternBase.request_pattern_id).
    This isolates that file to a temp directory so tests don't create/lock files in the repo root."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "next_free_pattern_id.txt").write_text("0")
    return tmp_path

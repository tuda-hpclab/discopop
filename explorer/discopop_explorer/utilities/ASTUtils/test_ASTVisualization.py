# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for ASTVisualization.

Fixtures use real Clang AST JSON format (file as string, "col" key).
"""

from __future__ import annotations

from typing import Any

import pytest
import networkx as nx

from discopop_explorer.utilities.ASTUtils.ASTGraph import ClangASTGraph
from discopop_explorer.utilities.ASTUtils.ASTVisualization import ASTVisualization


@pytest.fixture  # type: ignore[misc]
def sample_graph() -> nx.DiGraph[str]:
    """AST for a single function 'add' with two VarDecl children."""
    ast = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "id": "fn_add",
                "kind": "FunctionDecl",
                "name": "add",
                "type": "int ()",
                "loc": {"file": "math.cpp", "line": 1, "col": 1},
                "range": {"begin": {"col": 1}, "end": {"line": 5, "col": 1}},
                "inner": [
                    {
                        "id": "var_a",
                        "kind": "VarDecl",
                        "name": "a",
                        "type": "int",
                        "loc": {"line": 2, "col": 5},
                        "range": {"begin": {"col": 5}, "end": {"col": 10}},
                        "inner": [],
                    },
                    {
                        "id": "var_b",
                        "kind": "VarDecl",
                        "name": "b",
                        "type": "int",
                        "loc": {"line": 3, "col": 5},
                        "range": {"begin": {"col": 5}, "end": {"col": 10}},
                        "inner": [],
                    },
                ],
            }
        ],
    }
    return ClangASTGraph().build_from_ast(ast)


class TestASTVisualization:
    def test_get_layout_spring(self, sample_graph: nx.DiGraph[str]) -> None:
        layout = ASTVisualization.get_layout(sample_graph, "spring")
        assert len(layout) == len(sample_graph.nodes)
        assert all(hasattr(pos, "__len__") and len(pos) == 2 for pos in layout.values())

    def test_get_layout_circular(self, sample_graph: nx.DiGraph[str]) -> None:
        layout = ASTVisualization.get_layout(sample_graph, "circular")
        assert len(layout) == len(sample_graph.nodes)

    def test_get_layout_kamada_kawai(self, sample_graph: nx.DiGraph[str]) -> None:
        layout = ASTVisualization.get_layout(sample_graph, "kamada_kawai")
        assert len(layout) == len(sample_graph.nodes)

    def test_get_layout_tree(self, sample_graph: nx.DiGraph[str]) -> None:
        layout = ASTVisualization.get_layout(sample_graph, "tree")
        assert len(layout) == len(sample_graph.nodes)

    def test_get_layout_invalid(self, sample_graph: nx.DiGraph[str]) -> None:
        with pytest.raises(ValueError, match="Unknown layout type"):
            ASTVisualization.get_layout(sample_graph, "invalid")

    def test_get_node_labels(self, sample_graph: nx.DiGraph[str]) -> None:
        labels = ASTVisualization.get_node_labels(sample_graph)
        assert len(labels) == len(sample_graph.nodes)
        assert all(isinstance(label, str) for label in labels.values())
        assert any("add" in label for label in labels.values())

    def test_get_node_colors(self, sample_graph: nx.DiGraph[str]) -> None:
        colors = ASTVisualization.get_node_colors(sample_graph)
        assert len(colors) == len(sample_graph.nodes)
        assert all(c.startswith("#") for c in colors)

    def test_get_node_sizes(self, sample_graph: nx.DiGraph[str]) -> None:
        sizes = ASTVisualization.get_node_sizes(sample_graph)
        assert len(sizes) == len(sample_graph.nodes)
        assert all(s > 0 for s in sizes)

    def test_filter_graph_by_kind(self, sample_graph: nx.DiGraph[str]) -> None:
        filtered = ASTVisualization.filter_graph_by_kind(sample_graph, ["VarDecl"])
        assert len(filtered.nodes) == 2
        assert all(filtered.nodes[n]["kind"] == "VarDecl" for n in filtered.nodes())

    def test_filter_graph_by_file(self, sample_graph: nx.DiGraph[str]) -> None:
        """file stored as string; inherited nodes also resolve to math.cpp."""
        filtered = ASTVisualization.filter_graph_by_file(sample_graph, "math.cpp")
        assert len(filtered.nodes) > 0
        # All matched nodes must have math.cpp as their resolved file
        for n in filtered.nodes():
            assert filtered.nodes[n].get("loc", {}).get("file") == "math.cpp"

    def test_filter_graph_by_file_basename(self, sample_graph: nx.DiGraph[str]) -> None:
        """filter_graph_by_file must match when only the basename is given."""
        # Manually set a full path to test basename matching
        g: nx.DiGraph[str] = nx.DiGraph()
        g.add_node("n", kind="VarDecl", loc={"file": "/project/src/main.cpp"}, range={})
        filtered = ASTVisualization.filter_graph_by_file(g, "main.cpp")
        assert "n" in filtered.nodes

    def test_filter_graph_by_depth(self, sample_graph: nx.DiGraph[str]) -> None:
        root = next(n for n in sample_graph.nodes() if sample_graph.in_degree(n) == 0)
        filtered_0 = ASTVisualization.filter_graph_by_depth(sample_graph, root, 0)
        assert len(filtered_0.nodes) == 1  # root only

        filtered_1 = ASTVisualization.filter_graph_by_depth(sample_graph, root, 1)
        assert len(filtered_1.nodes) == 2  # root + FunctionDecl

        filtered_2 = ASTVisualization.filter_graph_by_depth(sample_graph, root, 2)
        assert len(filtered_2.nodes) == 4  # root + FunctionDecl + 2 VarDecl

    def test_get_graphviz_format(self, sample_graph: nx.DiGraph[str]) -> None:
        dot = ASTVisualization.get_graphviz_format(sample_graph)
        assert "digraph" in dot
        assert "add" in dot or "FunctionDecl" in dot
        assert "->" in dot

    def test_get_statistics(self, sample_graph: nx.DiGraph[str]) -> None:
        stats = ASTVisualization.get_statistics(sample_graph)
        assert stats["num_nodes"] == len(sample_graph.nodes)
        assert stats["num_edges"] == len(sample_graph.edges)
        assert "is_tree" in stats
        assert "num_connected_components" in stats
        assert "node_kinds" in stats
        assert "avg_degree" in stats
        assert "FunctionDecl" in stats["node_kinds"]
        assert "VarDecl" in stats["node_kinds"]

    def test_print_tree_structure(self, sample_graph: nx.DiGraph[str], capsys: Any) -> None:
        ASTVisualization.print_tree_structure(sample_graph)
        out = capsys.readouterr().out
        assert len(out) > 0
        assert "FunctionDecl" in out or "add" in out

    def test_print_tree_structure_with_root(self, sample_graph: nx.DiGraph[str], capsys: Any) -> None:
        ASTVisualization.print_tree_structure(sample_graph, "fn_add")
        out = capsys.readouterr().out
        assert len(out) > 0
        assert "add" in out

    def test_print_tree_structure_with_depth_limit(self, sample_graph: nx.DiGraph[str], capsys: Any) -> None:
        """With max_depth=0 only the root is printed; with =1 also its child."""
        root = next(n for n in sample_graph.nodes() if sample_graph.in_degree(n) == 0)

        ASTVisualization.print_tree_structure(sample_graph, root, max_depth=0)
        out_0 = capsys.readouterr().out
        lines_0 = [l for l in out_0.splitlines() if l.strip()]

        ASTVisualization.print_tree_structure(sample_graph, root, max_depth=1)
        out_1 = capsys.readouterr().out
        lines_1 = [l for l in out_1.splitlines() if l.strip()]

        assert len(lines_1) > len(lines_0), "max_depth=1 should print more than max_depth=0"

    def test_filter_graph_preserves_edges(self, sample_graph: nx.DiGraph[str]) -> None:
        filtered = ASTVisualization.filter_graph_by_kind(sample_graph, ["FunctionDecl", "VarDecl"])
        for u, v in filtered.edges():
            assert u in filtered.nodes
            assert v in filtered.nodes

    def test_statistics_completeness(self, sample_graph: nx.DiGraph[str]) -> None:
        stats = ASTVisualization.get_statistics(sample_graph)
        all_kinds = {sample_graph.nodes[n].get("kind") for n in sample_graph.nodes}
        assert all_kinds == set(stats["node_kinds"].keys())

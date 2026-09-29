# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

from typing import Any, Optional, cast

import networkx as nx


class ASTVisualization:
    """Utilities for visualizing and analysing AST graphs."""

    @staticmethod
    def get_layout(graph: nx.DiGraph[str], layout_type: str = "spring") -> dict[str, Any]:
        """Compute a 2-D layout for the graph.

        Args:
            graph: AST graph
            layout_type: ``"spring"`` | ``"circular"`` | ``"tree"`` | ``"kamada_kawai"``

        Returns:
            Dict mapping node IDs to (x, y) positions

        Raises:
            ValueError: For unknown layout_type values
        """
        if layout_type == "spring":
            return cast(dict[str, Any], nx.spring_layout(graph, k=2, iterations=50, seed=42))
        elif layout_type == "tree":
            return cast(dict[str, Any], nx.spring_layout(graph, k=0.5, iterations=30, seed=42))
        elif layout_type == "circular":
            return cast(dict[str, Any], nx.circular_layout(graph))
        elif layout_type == "kamada_kawai":
            return cast(dict[str, Any], nx.kamada_kawai_layout(graph))
        else:
            raise ValueError(f"Unknown layout type: {layout_type}")

    @staticmethod
    def get_node_labels(graph: nx.DiGraph[str]) -> dict[str, str]:
        """Build a label string for every node.

        Uses ``name (kind)`` when a name is present, otherwise just ``kind``.

        Args:
            graph: AST graph

        Returns:
            Dict mapping node IDs to label strings
        """
        labels: dict[str, str] = {}
        for node_id, attrs in graph.nodes(data=True):
            name = attrs.get("name")
            kind = attrs.get("kind", "Unknown")
            labels[node_id] = f"{name}\n({kind})" if name else kind
        return labels

    @staticmethod
    def get_node_colors(graph: nx.DiGraph[str]) -> list[str]:
        """Return a per-node color list based on node kind.

        Args:
            graph: AST graph

        Returns:
            List of hex color strings, one per node in graph iteration order
        """
        color_map = {
            "FunctionDecl": "#FF6B6B",
            "VarDecl": "#4ECDC4",
            "ForStmt": "#95E1D3",
            "WhileStmt": "#95E1D3",
            "DoStmt": "#95E1D3",
            "IfStmt": "#F7DC6F",
            "CompoundStmt": "#BB8FCE",
            "ReturnStmt": "#85C1E2",
            "DeclRefExpr": "#F8B88B",
            "BinaryOperator": "#ABEBC6",
            "CallExpr": "#FAD7A0",
        }
        return [color_map.get(graph.nodes[node_id].get("kind", ""), "#D3D3D3") for node_id in graph.nodes()]

    @staticmethod
    def get_node_sizes(graph: nx.DiGraph[str]) -> list[float]:
        """Return a per-node size list.

        Named nodes (functions, variables) are rendered larger.

        Args:
            graph: AST graph

        Returns:
            List of float sizes, one per node in graph iteration order
        """
        return [500.0 if graph.nodes[node_id].get("name") is not None else 300.0 for node_id in graph.nodes()]

    @staticmethod
    def filter_graph_by_kind(graph: nx.DiGraph[str], kinds: list[str]) -> nx.DiGraph[str]:
        """Return a subgraph containing only nodes of the given kinds.

        Args:
            graph: AST graph
            kinds: Node kinds to keep

        Returns:
            Copy of the induced subgraph
        """
        keep = [n for n, a in graph.nodes(data=True) if a.get("kind") in kinds]
        return graph.subgraph(keep).copy()

    @staticmethod
    def filter_graph_by_file(graph: nx.DiGraph[str], filename: str) -> nx.DiGraph[str]:
        """Return a subgraph containing only nodes from a specific source file.

        Accepts both full paths and basenames (e.g. ``"main.cpp"``).

        Args:
            graph: AST graph
            filename: Source filename or path

        Returns:
            Copy of the induced subgraph
        """
        from discopop_explorer.utilities.ASTUtils.ASTQueries import _file_matches

        keep = [n for n, a in graph.nodes(data=True) if _file_matches(a.get("loc", {}).get("file"), filename)]
        return graph.subgraph(keep).copy()

    @staticmethod
    def filter_graph_by_depth(graph: nx.DiGraph[str], root_node_id: str, max_depth: int) -> nx.DiGraph[str]:
        """Return a subgraph limited to *max_depth* levels below *root_node_id*.

        Args:
            graph: AST graph
            root_node_id: Starting node
            max_depth: Maximum depth to include (0 = root only)

        Returns:
            Copy of the induced subgraph
        """
        keep: set[str] = set()

        def _collect(node_id: str, depth: int) -> None:
            if depth > max_depth:
                return
            keep.add(node_id)
            for child in graph.successors(node_id):
                _collect(child, depth + 1)

        _collect(root_node_id, 0)
        return graph.subgraph(keep).copy()

    @staticmethod
    def get_graphviz_format(graph: nx.DiGraph[str]) -> str:
        """Generate a Graphviz DOT representation of the graph.

        Args:
            graph: AST graph

        Returns:
            DOT format string, ready for ``dot`` / ``xdot`` / online viewers
        """
        lines = ["digraph AST {", '  rankdir="TB";']

        for node_id, attrs in graph.nodes(data=True):
            kind = attrs.get("kind", "Unknown")
            name = attrs.get("name")
            label = f"{name}\\n({kind})" if name else kind
            lines.append(f'  "{node_id}" [label="{label}"];')

        for u, v in graph.edges():
            lines.append(f'  "{u}" -> "{v}";')

        lines.append("}")
        return "\n".join(lines)

    @staticmethod
    def get_statistics(graph: nx.DiGraph[str]) -> dict[str, Any]:
        """Compute basic statistics about the graph.

        Args:
            graph: AST graph

        Returns:
            Dict with keys: ``num_nodes``, ``num_edges``, ``is_tree``,
            ``num_connected_components``, ``node_kinds``, ``avg_degree``
        """
        kind_counts: dict[str, int] = {}
        for _, attrs in graph.nodes(data=True):
            kind = attrs.get("kind", "Unknown")
            kind_counts[kind] = kind_counts.get(kind, 0) + 1

        undirected = graph.to_undirected()
        is_tree = nx.is_tree(graph) if nx.is_connected(undirected) else False

        return {
            "num_nodes": len(graph.nodes),
            "num_edges": len(graph.edges),
            "is_tree": is_tree,
            "num_connected_components": nx.number_connected_components(undirected),
            "node_kinds": kind_counts,
            "avg_degree": sum(dict(graph.degree()).values()) / max(len(graph.nodes), 1),
        }

    @staticmethod
    def print_tree_structure(
        graph: nx.DiGraph[str],
        root_node_id: Optional[str] = None,
        _current_depth: int = 0,
        max_depth: Optional[int] = None,
    ) -> None:
        """Print a readable tree structure to stdout.

        Args:
            graph: AST graph
            root_node_id: Node to start from (``None`` = all root nodes)
            _current_depth: Internal recursion depth counter (do not pass)
            max_depth: Maximum depth to print (``None`` = unlimited)
        """
        if root_node_id is None:
            roots = [n for n in graph.nodes() if graph.in_degree(n) == 0]
            for root in roots:
                ASTVisualization.print_tree_structure(graph, root, 0, max_depth)
            return

        if max_depth is not None and _current_depth > max_depth:
            return

        attrs = graph.nodes[root_node_id]
        kind = attrs.get("kind", "Unknown")
        name = attrs.get("name")
        node_str = f"{name} ({kind})" if name else kind

        print("  " * _current_depth + f"├─ {node_str}")

        for child in graph.successors(root_node_id):
            ASTVisualization.print_tree_structure(graph, child, _current_depth + 1, max_depth)

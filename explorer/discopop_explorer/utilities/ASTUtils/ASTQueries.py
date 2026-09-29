# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from __future__ import annotations

import weakref
from typing import Any, Optional

import networkx as nx


class ASTQueries:
    """Query interface for AST graph operations."""

    @staticmethod
    def find_nodes_by_kind(graph: nx.DiGraph[str], kind: str) -> list[str]:
        """Find all nodes of a specific kind.

        Args:
            graph: AST graph
            kind: AST node kind (e.g., 'FunctionDecl', 'VarDecl')

        Returns:
            List of node IDs matching the kind
        """
        return [node_id for node_id, attrs in graph.nodes(data=True) if attrs.get("kind") == kind]

    @staticmethod
    def find_functions(graph: nx.DiGraph[str]) -> list[str]:
        """Find all function declaration nodes.

        Args:
            graph: AST graph

        Returns:
            List of FunctionDecl node IDs
        """
        return ASTQueries.find_nodes_by_kind(graph, "FunctionDecl")

    @staticmethod
    def find_loops(graph: nx.DiGraph[str]) -> list[str]:
        """Find all loop nodes (ForStmt, WhileStmt, DoStmt).

        Args:
            graph: AST graph

        Returns:
            List of loop node IDs
        """
        loop_kinds = {"ForStmt", "WhileStmt", "DoStmt"}
        return [node_id for node_id, attrs in graph.nodes(data=True) if attrs.get("kind") in loop_kinds]

    @staticmethod
    def find_declarations(graph: nx.DiGraph[str]) -> list[str]:
        """Find all variable declaration nodes (VarDecl).

        Args:
            graph: AST graph

        Returns:
            List of VarDecl node IDs
        """
        return ASTQueries.find_nodes_by_kind(graph, "VarDecl")

    @staticmethod
    def get_parent(graph: nx.DiGraph[str], node_id: str) -> Optional[str]:
        """Get parent node of a given node.

        Args:
            graph: AST graph
            node_id: Node ID

        Returns:
            Parent node ID or None if node is root
        """
        parents = list(graph.predecessors(node_id))
        return parents[0] if parents else None

    @staticmethod
    def get_children(graph: nx.DiGraph[str], node_id: str) -> list[str]:
        """Get all child nodes.

        Args:
            graph: AST graph
            node_id: Node ID

        Returns:
            List of child node IDs
        """
        return list(graph.successors(node_id))

    @staticmethod
    def find_enclosing_scope(graph: nx.DiGraph[str], node_id: str) -> Optional[str]:
        """Find the nearest enclosing scope node (function or compound statement).

        Walks up the tree until a scope-defining node is found.  A visited set
        guards against cycles in malformed graphs.

        Args:
            graph: AST graph
            node_id: Node ID to start from

        Returns:
            ID of enclosing scope node or None if none found
        """
        scope_kinds = {"FunctionDecl", "CompoundStmt", "ForStmt", "WhileStmt"}
        visited: set[str] = set()

        current: Optional[str] = node_id
        while current is not None and current not in visited:
            visited.add(current)
            if graph.nodes[current].get("kind") in scope_kinds:
                return current
            current = ASTQueries.get_parent(graph, current)

        return None

    @staticmethod
    def find_loop_at_location(graph: nx.DiGraph[str], filename: str, line: int) -> Optional[str]:
        """Find the loop statement whose header starts on a given line.

        Args:
            graph: AST graph
            filename: Source filename
            line: Line the loop header starts on

        Returns:
            ID of the outermost loop node beginning on *line*, or None if there is none
        """
        for node_id in ASTQueries.find_nodes_at_location(graph, filename, line):
            attrs = graph.nodes[node_id]
            if attrs.get("kind") in _LOOP_KINDS and attrs.get("range", {}).get("begin_line") == line:
                # find_nodes_at_location descends the tree, so parents precede their children
                # and the first hit is the outermost loop starting here
                return node_id
        return None

    @staticmethod
    def get_node_info(graph: nx.DiGraph[str], node_id: str) -> dict[str, Any]:
        """Get all attributes of a node.

        Args:
            graph: AST graph
            node_id: Node ID

        Returns:
            Dictionary with node attributes
        """
        return dict(graph.nodes[node_id])

    @staticmethod
    def find_nodes_in_file(graph: nx.DiGraph[str], filename: str) -> list[str]:
        """Find all nodes whose resolved location is in a specific file.

        Args:
            graph: AST graph
            filename: Source filename (basename or full path)

        Returns:
            List of matching node IDs
        """
        return [
            node_id
            for node_id, attrs in graph.nodes(data=True)
            if _file_matches(attrs.get("loc", {}).get("file"), filename)
        ]

    @staticmethod
    def find_nodes_at_location(
        graph: nx.DiGraph[str], filename: str, line: int, column: Optional[int] = None
    ) -> list[str]:
        """Find nodes whose source range contains a specific location.

        Descends the AST from its root node(s) instead of scanning every node:
        a child's range is always nested within its parent's, so any subtree
        whose range excludes *line* is skipped along with all its descendants.
        This visits roughly O(depth-to-matches) nodes per query rather than
        O(graph size), which matters once the AST is large enough that a full
        scan (repeated for every query against the same static graph) would
        dominate runtime.

        Args:
            graph: AST graph
            filename: Source filename
            line: Line number
            column: Column number, or ``None`` to match any column on *line*

        Returns:
            List of matching node IDs
        """
        matching: list[str] = []
        visited: set[str] = set()
        stack: list[str] = list(_get_root_node_ids(graph))
        while stack:
            node_id = stack.pop()
            if node_id in visited:
                continue
            visited.add(node_id)

            attrs = graph.nodes[node_id]
            range_info = attrs.get("range", {})
            if not ASTQueries._range_could_contain_line(line, range_info):
                continue  # prune: this subtree's range excludes *line*

            if _file_matches(attrs.get("loc", {}).get("file"), filename) and ASTQueries._is_in_range(
                line, column, range_info
            ):
                matching.append(node_id)

            stack.extend(graph.successors(node_id))
        return matching

    @staticmethod
    def _range_could_contain_line(line: int, range_info: dict[str, Any]) -> bool:
        """Check whether a node's subtree could possibly contain *line*.

        Used to prune AST subtrees during descent in :meth:`find_nodes_at_location`.
        Nodes with incomplete range info (e.g. the TranslationUnitDecl root, which
        Clang gives no range at all) can't be ruled out and must always be explored.

        Args:
            line: Line number to test
            range_info: Range dict with begin_line/end_line

        Returns:
            False only when the range is fully known and definitely excludes *line*
        """
        begin_line = range_info.get("begin_line")
        end_line = range_info.get("end_line")
        if begin_line is None or end_line is None:
            return True
        return bool(begin_line <= line <= end_line)

    @staticmethod
    def _is_in_range(line: int, column: Optional[int], range_info: dict[str, Any]) -> bool:
        """Check whether a (line, column) position falls within a source range.

        When *column* is ``None`` the check degenerates to a pure line-range
        test: any node whose range spans *line* is considered a match.

        Args:
            line: Line number to test
            column: Column number to test, or ``None`` to ignore column bounds
            range_info: Range dict with begin_line/begin_column/end_line/end_column

        Returns:
            True if the position is within the range
        """
        begin_line = range_info.get("begin_line")
        end_line = range_info.get("end_line")

        if begin_line is None or end_line is None:
            return False

        if line < begin_line or line > end_line:
            return False

        if column is None:
            return True

        begin_col = range_info.get("begin_column")
        end_col = range_info.get("end_column")

        # Use explicit None checks — column 0 is a valid (falsy) value
        if line == begin_line and begin_col is not None and column < begin_col:
            return False

        if line == end_line and end_col is not None and column > end_col:
            return False

        return True


class ASTVariableAndTypeQueries:
    """Query variables and types from AST nodes."""

    @staticmethod
    def find_declarations_at_location(
        graph: nx.DiGraph[str], filename: str, line: int, column: int
    ) -> list[tuple[str, Optional[str], str]]:
        """Find VarDecl nodes at or enclosing a source location.

        Args:
            graph: AST graph
            filename: Source filename
            line: Line number
            column: Column number

        Returns:
            List of (var_name, var_type, node_kind) tuples
        """
        nodes_at_loc = ASTQueries.find_nodes_at_location(graph, filename, line, column)
        return [
            (
                attrs.get("name", ""),
                attrs.get("type"),
                attrs.get("kind", ""),
            )
            for node_id in nodes_at_loc
            if (attrs := graph.nodes[node_id]).get("kind") == "VarDecl"
        ]

    @staticmethod
    def find_references_at_location(
        graph: nx.DiGraph[str], filename: str, line: int, column: int
    ) -> list[tuple[str, Optional[str], str]]:
        """Find DeclRefExpr nodes at a source location.

        Args:
            graph: AST graph
            filename: Source filename
            line: Line number
            column: Column number

        Returns:
            List of (var_name, var_type, node_kind) tuples
        """
        nodes_at_loc = ASTQueries.find_nodes_at_location(graph, filename, line, column)
        return [
            (
                attrs.get("name", ""),
                attrs.get("type"),
                attrs.get("kind", ""),
            )
            for node_id in nodes_at_loc
            if (attrs := graph.nodes[node_id]).get("kind") == "DeclRefExpr"
        ]

    @staticmethod
    def find_all_variables_in_scope(
        graph: nx.DiGraph[str], filename: str, line: int, column: Optional[int] = None
    ) -> list[tuple[str, Optional[str]]]:
        """Find all variables visible at a source location.

        Locates the enclosing scope of the given position and collects all
        VarDecl nodes reachable from it.

        Args:
            graph: AST graph
            filename: Source filename
            line: Line number
            column: Column number, or ``None`` to consider all columns on *line*

        Returns:
            Sorted list of (var_name, var_type) tuples
        """
        nodes_at_loc = ASTQueries.find_nodes_at_location(graph, filename, line, column)
        if not nodes_at_loc:
            return []

        scope_node_id: Optional[str] = None
        for node_id in nodes_at_loc:
            scope = ASTQueries.find_enclosing_scope(graph, node_id)
            if scope:
                scope_node_id = scope
                break

        if not scope_node_id:
            return []

        variables: set[tuple[str, Optional[str]]] = set()
        ASTVariableAndTypeQueries._collect_var_decls_in_scope(graph, scope_node_id, variables, before_line=line)
        return sorted(variables)

    @staticmethod
    def find_variables_assigned_in_loop_at(graph: nx.DiGraph[str], filename: str, line: int) -> set[str]:
        """Find variables whose own storage is assigned inside the loop whose header is at *line*.

        Only assignments to the variable itself count -- ``p = &a[i]`` yields ``p``, whereas
        ``p[i] = x`` or ``p[i].f += x`` yields nothing, because those write the memory *reached
        through* ``p`` and leave ``p`` untouched.  The distinction is invisible in the profiler's
        dependency data, which names an indirect access after the pointer it went through, so the
        AST is the only place it can be recovered.

        The loop's extent is taken from the AST node's own range, so a variable assigned in an
        enclosing loop but not in this one is correctly left out.

        Args:
            graph: AST graph
            filename: Source filename
            line: Line the loop header starts on

        Returns:
            Set of variable names directly assigned somewhere inside the loop body or header
        """
        loop_node_id = ASTQueries.find_loop_at_location(graph, filename, line)
        if loop_node_id is None:
            return set()

        assigned: set[str] = set()
        visited: set[str] = set()
        stack: list[str] = [loop_node_id]
        while stack:
            node_id = stack.pop()
            if node_id in visited:
                continue
            visited.add(node_id)

            attrs = graph.nodes[node_id]
            if attrs.get("kind") in _ASSIGNING_OPERATOR_KINDS and attrs.get("opcode") in _ASSIGNING_OPCODES:
                target = ASTVariableAndTypeQueries._assignment_target_name(graph, node_id)
                if target is not None:
                    assigned.add(target)

            stack.extend(graph.successors(node_id))
        return assigned

    @staticmethod
    def _assignment_target_name(graph: nx.DiGraph[str], operator_node_id: str) -> Optional[str]:
        """Return the name of the variable an assignment operator writes, if it writes one directly.

        The operand written is the operator's first child.  Casts and parentheses around it are
        transparent; an ``ArraySubscriptExpr``, ``MemberExpr`` or dereference in between means the
        write goes to memory reached through the variable rather than to the variable, so no name
        is returned.

        Args:
            graph: AST graph
            operator_node_id: ID of the assignment / increment operator node

        Returns:
            Variable name, or None when the operator does not write a variable directly
        """
        children = list(graph.successors(operator_node_id))
        if not children:
            return None
        # The DFS in build_from_ast adds children in source order, so the first successor is the
        # assignment's left-hand side (its sole operand for ++ / --).
        current = children[0]
        seen: set[str] = set()
        while current not in seen:
            seen.add(current)
            attrs = graph.nodes[current]
            kind = attrs.get("kind")
            if kind == "DeclRefExpr":
                name = attrs.get("referenced_name")
                return str(name) if name else None
            if kind not in _TRANSPARENT_LVALUE_KINDS:
                return None
            next_children = list(graph.successors(current))
            if not next_children:
                return None
            current = next_children[0]
        return None

    @staticmethod
    def get_variables_in_scope(graph: nx.DiGraph[str], scope_node_id: str) -> list[tuple[str, Optional[str]]]:
        """Find all variables declared within a scope node.

        Args:
            graph: AST graph
            scope_node_id: ID of the scope node (function, loop, etc.)

        Returns:
            Sorted list of (var_name, var_type) tuples
        """
        variables: set[tuple[str, Optional[str]]] = set()
        ASTVariableAndTypeQueries._collect_var_decls_in_scope(graph, scope_node_id, variables)
        return sorted(variables)

    @staticmethod
    def _collect_var_decls_in_scope(
        graph: nx.DiGraph[str],
        scope_node_id: str,
        variables: set[tuple[str, Optional[str]]],
        before_line: Optional[int] = None,
    ) -> None:
        """Recursively collect all VarDecl and ParmVarDecl nodes reachable from a scope.

        Args:
            graph: AST graph
            scope_node_id: Root node to search from
            variables: Accumulator set (modified in place)
            before_line: When set, only include declarations at or before this line number.
        """
        attrs = graph.nodes[scope_node_id]
        if attrs.get("kind") in {"VarDecl", "ParmVarDecl"}:
            var_name = attrs.get("name")
            if var_name:
                if before_line is not None:
                    decl_line = (attrs.get("loc") or {}).get("line")
                    if decl_line is not None and decl_line > before_line:
                        return
                variables.add((var_name, attrs.get("type")))

        for child_id in graph.successors(scope_node_id):
            ASTVariableAndTypeQueries._collect_var_decls_in_scope(graph, child_id, variables, before_line)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_LOOP_KINDS = {"ForStmt", "WhileStmt", "DoStmt", "CXXForRangeStmt"}

# Clang node kinds that write their first operand
_ASSIGNING_OPERATOR_KINDS = {"BinaryOperator", "CompoundAssignOperator", "UnaryOperator"}

# Operator spellings that write their first operand.  "=" is the only assigning opcode a plain
# BinaryOperator can carry; the compound forms belong to CompoundAssignOperator and "++" / "--"
# to UnaryOperator, so one shared set covers all three kinds.
_ASSIGNING_OPCODES = {
    "=",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "<<=",
    ">>=",
    "++",
    "--",
}

# Node kinds that wrap an lvalue without redirecting the write to different storage
_TRANSPARENT_LVALUE_KINDS = {"ImplicitCastExpr", "CStyleCastExpr", "ParenExpr", "ConstantExpr"}

# Keyed by the graph object itself (weakly) rather than id(graph): a plain
# id()-keyed cache would risk a stale hit if a graph is garbage-collected and
# a new, unrelated graph happens to be allocated at the same address.
_root_node_cache: "weakref.WeakKeyDictionary[nx.DiGraph[str], list[str]]" = weakref.WeakKeyDictionary()


def _get_root_node_ids(graph: nx.DiGraph[str]) -> list[str]:
    """Return the graph's root node IDs (no incoming edges), cached per graph.

    AST graphs are built once and then queried many times via
    :meth:`ASTQueries.find_nodes_at_location`; computing in-degree for every
    node is itself an O(graph size) scan, so the result is cached against the
    graph instance to keep that cost one-time rather than per-query.

    Args:
        graph: AST graph

    Returns:
        List of node IDs with no incoming edges
    """
    cached = _root_node_cache.get(graph)
    if cached is not None:
        return cached
    roots = [node_id for node_id in graph.nodes() if graph.in_degree(node_id) == 0]
    _root_node_cache[graph] = roots
    return roots


def _file_matches(stored: Optional[str], query: str) -> bool:
    """Return True if *stored* file path matches the *query* filename.

    Accepts both full paths and basenames so that
    ``_file_matches("/path/to/main.cpp", "main.cpp")`` is True.

    Args:
        stored: File path stored in a node's loc dict (may be None)
        query: Filename or path to look for

    Returns:
        True on match
    """
    if stored is None:
        return False
    return stored == query or stored.endswith("/" + query) or stored.endswith("\\" + query)

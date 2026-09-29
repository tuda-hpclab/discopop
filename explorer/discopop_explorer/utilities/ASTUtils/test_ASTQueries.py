# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for ASTQueries and ASTVariableAndTypeQueries.

Fixtures use real Clang AST JSON format:
  * ``"col"`` (not ``"column"``) for column info
  * ``file`` is a plain string, absent on child nodes that inherit it
"""

from __future__ import annotations

from typing import Any

import pytest
import networkx as nx

from discopop_explorer.utilities.ASTUtils.ASTGraph import ClangASTGraph
from discopop_explorer.utilities.ASTUtils.ASTQueries import (
    ASTQueries,
    ASTVariableAndTypeQueries,
    _file_matches,
)


@pytest.fixture  # type: ignore[misc]
def sample_graph() -> nx.DiGraph[str]:
    """AST graph for a single function 'main' with variables x, y and a loop."""
    ast = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "id": "fn_main",
                "kind": "FunctionDecl",
                "name": "main",
                "type": "int ()",
                # file present here (first occurrence)
                "loc": {"file": "test.cpp", "line": 1, "col": 1},
                "range": {"begin": {"col": 1}, "end": {"line": 10, "col": 1}},
                "inner": [
                    {
                        "id": "var_x",
                        "kind": "VarDecl",
                        "name": "x",
                        "type": "int",
                        # file inherited from FunctionDecl
                        "loc": {"line": 2, "col": 5},
                        "range": {"begin": {"col": 5}, "end": {"col": 10}},
                        "inner": [],
                    },
                    {
                        "id": "var_y",
                        "kind": "VarDecl",
                        "name": "y",
                        "type": "double",
                        "loc": {"line": 3, "col": 5},
                        "range": {"begin": {"col": 5}, "end": {"col": 12}},
                        "inner": [],
                    },
                    {
                        "id": "for_stmt",
                        "kind": "ForStmt",
                        "loc": {"line": 5, "col": 5},
                        "range": {"begin": {"col": 5}, "end": {"line": 8, "col": 5}},
                        "inner": [
                            {
                                "id": "var_i",
                                "kind": "VarDecl",
                                "name": "i",
                                "type": "int",
                                "loc": {"line": 5, "col": 10},
                                "range": {"begin": {"col": 10}, "end": {"col": 15}},
                                "inner": [],
                            }
                        ],
                    },
                    {
                        "id": "ret_stmt",
                        "kind": "ReturnStmt",
                        "loc": {"line": 9, "col": 5},
                        "range": {"begin": {"col": 5}, "end": {"col": 15}},
                        "inner": [],
                    },
                ],
            }
        ],
    }
    return ClangASTGraph().build_from_ast(ast)


# ---------------------------------------------------------------------------
# ASTQueries tests
# ---------------------------------------------------------------------------


class TestASTQueries:
    def test_find_nodes_by_kind(self, sample_graph: nx.DiGraph[str]) -> None:
        var_decls = ASTQueries.find_nodes_by_kind(sample_graph, "VarDecl")
        assert len(var_decls) == 3
        assert all(sample_graph.nodes[n]["kind"] == "VarDecl" for n in var_decls)

    def test_find_functions(self, sample_graph: nx.DiGraph[str]) -> None:
        functions = ASTQueries.find_functions(sample_graph)
        assert len(functions) == 1
        assert sample_graph.nodes[functions[0]]["name"] == "main"

    def test_find_loops(self, sample_graph: nx.DiGraph[str]) -> None:
        loops = ASTQueries.find_loops(sample_graph)
        assert len(loops) == 1
        assert sample_graph.nodes[loops[0]]["kind"] == "ForStmt"

    def test_find_declarations(self, sample_graph: nx.DiGraph[str]) -> None:
        decls = ASTQueries.find_declarations(sample_graph)
        assert len(decls) == 3
        names = {sample_graph.nodes[d]["name"] for d in decls}
        assert names == {"x", "y", "i"}

    def test_get_parent(self, sample_graph: nx.DiGraph[str]) -> None:
        parent = ASTQueries.get_parent(sample_graph, "var_x")
        assert parent == "fn_main"

    def test_get_parent_of_root_is_none(self, sample_graph: nx.DiGraph[str]) -> None:
        roots = [n for n in sample_graph.nodes() if sample_graph.in_degree(n) == 0]
        assert ASTQueries.get_parent(sample_graph, roots[0]) is None

    def test_get_children(self, sample_graph: nx.DiGraph[str]) -> None:
        children = ASTQueries.get_children(sample_graph, "fn_main")
        assert len(children) == 4  # var_x, var_y, for_stmt, ret_stmt

    def test_find_enclosing_scope_function(self, sample_graph: nx.DiGraph[str]) -> None:
        """Variable x is directly inside main → scope is FunctionDecl."""
        scope = ASTQueries.find_enclosing_scope(sample_graph, "var_x")
        assert scope == "fn_main"

    def test_find_enclosing_scope_loop(self, sample_graph: nx.DiGraph[str]) -> None:
        """Variable i is inside ForStmt → nearest scope is ForStmt."""
        scope = ASTQueries.find_enclosing_scope(sample_graph, "var_i")
        assert scope == "for_stmt"

    def test_find_enclosing_scope_cycle_safe(self) -> None:
        """find_enclosing_scope must not loop forever on a cyclic graph."""
        g: nx.DiGraph[str] = nx.DiGraph()
        g.add_node("a", kind="VarDecl")
        g.add_node("b", kind="VarDecl")
        g.add_edge("a", "b")
        g.add_edge("b", "a")  # cycle
        # Should return None or one of the nodes, but not hang
        result = ASTQueries.find_enclosing_scope(g, "a")
        assert result is None  # neither is a scope kind

    def test_get_node_info(self, sample_graph: nx.DiGraph[str]) -> None:
        info = ASTQueries.get_node_info(sample_graph, "var_x")
        assert info["kind"] == "VarDecl"
        assert info["name"] == "x"
        assert info["type"] == "int"

    def test_find_nodes_in_file(self, sample_graph: nx.DiGraph[str]) -> None:
        """All user-code nodes should resolve to test.cpp via inheritance."""
        nodes = ASTQueries.find_nodes_in_file(sample_graph, "test.cpp")
        # fn_main, var_x, var_y, for_stmt, var_i, ret_stmt  (not TranslationUnitDecl)
        assert len(nodes) >= 5

    def test_find_nodes_in_file_basename(self, sample_graph: nx.DiGraph[str]) -> None:
        """_file_matches accepts basename even when full path is stored."""
        assert _file_matches("/home/user/project/main.cpp", "main.cpp")
        assert not _file_matches("/home/user/project/main.cpp", "other.cpp")
        assert not _file_matches(None, "main.cpp")

    def test_find_nodes_at_location(self, sample_graph: nx.DiGraph[str]) -> None:
        # Line 2, col 5 is where var_x is declared — range is line 2 col 5..10
        nodes = ASTQueries.find_nodes_at_location(sample_graph, "test.cpp", 2, 7)
        assert len(nodes) > 0
        kinds = {sample_graph.nodes[n]["kind"] for n in nodes}
        assert "VarDecl" in kinds

    def test_is_in_range_zero_column(self) -> None:
        """begin_column == 0 must not be treated as falsy."""
        r = {"begin_line": 1, "begin_column": 0, "end_line": 1, "end_column": 10}
        assert ASTQueries._is_in_range(1, 0, r)  # exactly at column 0
        assert ASTQueries._is_in_range(1, 5, r)
        assert not ASTQueries._is_in_range(1, 11, r)  # past end

    def test_is_in_range_missing_lines(self) -> None:
        assert not ASTQueries._is_in_range(1, 1, {})
        assert not ASTQueries._is_in_range(1, 1, {"begin_line": None, "end_line": 5})

    def test_is_in_range_none_column_ignores_column_bounds(self) -> None:
        """column=None matches any column on a line within the line range."""
        r = {"begin_line": 3, "begin_column": 10, "end_line": 7, "end_column": 5}
        assert ASTQueries._is_in_range(3, None, r)  # first line, before begin_col — still matches
        assert ASTQueries._is_in_range(5, None, r)  # middle line
        assert ASTQueries._is_in_range(7, None, r)  # last line, after end_col — still matches
        assert not ASTQueries._is_in_range(2, None, r)  # before range
        assert not ASTQueries._is_in_range(8, None, r)  # after range

    def test_find_nodes_at_location_none_column(self, sample_graph: nx.DiGraph[str]) -> None:
        """column=None returns nodes spanning the line regardless of column."""
        nodes_with_col = ASTQueries.find_nodes_at_location(sample_graph, "test.cpp", 2, 7)
        nodes_no_col = ASTQueries.find_nodes_at_location(sample_graph, "test.cpp", 2)
        # Without a column filter we get at least as many nodes
        assert set(nodes_with_col).issubset(set(nodes_no_col))


# ---------------------------------------------------------------------------
# ASTVariableAndTypeQueries tests
# ---------------------------------------------------------------------------


class TestASTVariableAndTypeQueries:
    def test_find_declarations_at_location(self, sample_graph: nx.DiGraph[str]) -> None:
        decls = ASTVariableAndTypeQueries.find_declarations_at_location(sample_graph, "test.cpp", 2, 7)
        assert any(d[0] == "x" for d in decls)

    def test_find_all_variables_in_scope(self, sample_graph: nx.DiGraph[str]) -> None:
        # Position inside the function body (line 6 is inside the for loop range)
        variables = ASTVariableAndTypeQueries.find_all_variables_in_scope(sample_graph, "test.cpp", 6, 5)
        var_names = [v[0] for v in variables]
        assert len(var_names) > 0
        assert any(name in var_names for name in ["x", "y", "i"])

    def test_find_all_variables_in_scope_none_column(self, sample_graph: nx.DiGraph[str]) -> None:
        """Omitting column returns the same or more variables than a specific column."""
        with_col = ASTVariableAndTypeQueries.find_all_variables_in_scope(sample_graph, "test.cpp", 6, 5)
        no_col = ASTVariableAndTypeQueries.find_all_variables_in_scope(sample_graph, "test.cpp", 6)
        assert set(with_col).issubset(set(no_col))

    def test_function_parameters_included(self) -> None:
        """ParmVarDecl nodes (function parameters) must be returned alongside VarDecl locals."""
        ast = {
            "kind": "TranslationUnitDecl",
            "inner": [
                {
                    "id": "fn_dist",
                    "kind": "FunctionDecl",
                    "name": "dist",
                    "loc": {"file": "test.cpp", "line": 1, "col": 1},
                    "range": {"begin": {"col": 1}, "end": {"line": 20, "col": 1}},
                    "inner": [
                        {
                            "id": "parm_nd",
                            "kind": "ParmVarDecl",
                            "name": "nd",
                            "type": "int",
                            "loc": {"line": 1, "col": 10},
                            "range": {"begin": {"col": 10}, "end": {"col": 12}},
                            "inner": [],
                        },
                        {
                            "id": "parm_r1",
                            "kind": "ParmVarDecl",
                            "name": "r1",
                            "type": "double *",
                            "loc": {"line": 1, "col": 14},
                            "range": {"begin": {"col": 14}, "end": {"col": 16}},
                            "inner": [],
                        },
                        {
                            "id": "var_d",
                            "kind": "VarDecl",
                            "name": "d",
                            "type": "double",
                            "loc": {"line": 3, "col": 5},
                            "range": {"begin": {"col": 5}, "end": {"col": 6}},
                            "inner": [],
                        },
                    ],
                }
            ],
        }
        graph = ClangASTGraph().build_from_ast(ast)
        variables = ASTVariableAndTypeQueries.find_all_variables_in_scope(graph, "test.cpp", 10, 1)
        var_names = [v[0] for v in variables]
        assert "nd" in var_names
        assert "r1" in var_names
        assert "d" in var_names

    def test_get_variables_in_scope(self, sample_graph: nx.DiGraph[str]) -> None:
        variables = ASTVariableAndTypeQueries.get_variables_in_scope(sample_graph, "fn_main")
        var_names = [v[0] for v in variables]
        assert "x" in var_names
        assert "y" in var_names
        assert "i" in var_names

    def test_variable_types_preserved(self, sample_graph: nx.DiGraph[str]) -> None:
        variables = ASTVariableAndTypeQueries.get_variables_in_scope(sample_graph, "fn_main")
        var_dict = {name: typ for name, typ in variables}
        assert var_dict["x"] == "int"
        assert var_dict["y"] == "double"
        assert var_dict["i"] == "int"

    def test_variables_declared_after_query_line_excluded(self) -> None:
        """Variables declared after the queried line must not appear in results.

        Reproduces the bug where querying line 5 (a ForStmt header) incorrectly
        returned a variable declared on line 6 inside the loop body.
        """
        ast = {
            "kind": "TranslationUnitDecl",
            "inner": [
                {
                    "id": "fn_main",
                    "kind": "FunctionDecl",
                    "name": "main",
                    "loc": {"file": "test.cpp", "line": 1, "col": 1},
                    "range": {"begin": {"col": 1}, "end": {"line": 10, "col": 1}},
                    "inner": [
                        {
                            "id": "var_n",
                            "kind": "VarDecl",
                            "name": "n",
                            "type": "int",
                            "loc": {"line": 2, "col": 5},
                            "range": {"begin": {"col": 5}, "end": {"col": 6}},
                            "inner": [],
                        },
                        {
                            "id": "for_stmt",
                            "kind": "ForStmt",
                            "loc": {"line": 5, "col": 3},
                            "range": {"begin": {"col": 3}, "end": {"line": 8, "col": 3}},
                            "inner": [
                                {
                                    "id": "var_i",
                                    "kind": "VarDecl",
                                    "name": "i",
                                    "type": "int",
                                    "loc": {"line": 5, "col": 8},
                                    "range": {"begin": {"col": 8}, "end": {"col": 9}},
                                    "inner": [],
                                },
                                {
                                    "id": "var_ielem",
                                    "kind": "VarDecl",
                                    "name": "ielem",
                                    "type": "int",
                                    "loc": {"line": 6, "col": 5},
                                    "range": {"begin": {"col": 5}, "end": {"col": 10}},
                                    "inner": [],
                                },
                            ],
                        },
                    ],
                }
            ],
        }
        graph = ClangASTGraph().build_from_ast(ast)
        # Query at line 5 (the for-loop header): ielem (line 6) must not appear
        variables = ASTVariableAndTypeQueries.find_all_variables_in_scope(graph, "test.cpp", 5)
        var_names = [v[0] for v in variables]
        assert "ielem" not in var_names, "ielem is declared after the queried line and must be excluded"
        # Variables declared at or before line 5 should be present
        assert "i" in var_names
        assert "n" in var_names


def _assign(node_id: str, opcode: str, line: int, lhs: dict[str, Any], kind: str = "BinaryOperator") -> dict[str, Any]:
    """Build an assignment operator node writing *lhs* (whose RHS is an irrelevant literal)."""
    return {
        "id": node_id,
        "kind": kind,
        "opcode": opcode,
        "loc": {"line": line, "col": 5},
        "range": {"begin": {"line": line, "col": 5}, "end": {"line": line, "col": 20}},
        "inner": [
            lhs,
            {
                "id": node_id + "_rhs",
                "kind": "IntegerLiteral",
                "loc": {"line": line, "col": 18},
                "range": {"begin": {"line": line, "col": 18}, "end": {"line": line, "col": 18}},
                "inner": [],
            },
        ],
    }


def _declref(node_id: str, name: str, line: int, type_str: str = "int") -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "DeclRefExpr",
        "type": type_str,
        "loc": {"line": line, "col": 5},
        "range": {"begin": {"line": line, "col": 5}, "end": {"line": line, "col": 5}},
        "referencedDecl": {"kind": "VarDecl", "name": name, "id": "decl_" + name, "type": type_str},
        "inner": [],
    }


def _wrap(node_id: str, kind: str, line: int, inner: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "name": name,
        "loc": {"line": line, "col": 5},
        "range": {"begin": {"line": line, "col": 5}, "end": {"line": line, "col": 12}},
        "inner": [inner],
    }


@pytest.fixture  # type: ignore[misc]
def assignment_graph() -> nx.DiGraph[str]:
    """AST for a loop nest mixing direct writes to a pointer with writes through it.

    10  for (l = 0; ...) {          // outer
    11      p = &a[i];              // writes p itself
    12      for (k = 0; ...) {      // inner
    13          q = &b[j];          // writes q itself
    14          p[k].f += 1;        // writes memory reached through p, not p
    15          ++n;
    16      }
    17  }
    """
    inner_for = {
        "id": "for_inner",
        "kind": "ForStmt",
        "loc": {"file": "kernel.c", "line": 12, "col": 5},
        "range": {"begin": {"line": 12, "col": 5}, "end": {"line": 16, "col": 5}},
        "inner": [
            _assign("assign_q", "=", 13, _declref("ref_q", "q", 13, "double *")),
            # p[k].f += 1  ->  MemberExpr( ArraySubscriptExpr( ImplicitCast( DeclRefExpr p ) ) )
            _assign(
                "assign_through_p",
                "+=",
                14,
                _wrap(
                    "member_f",
                    "MemberExpr",
                    14,
                    _wrap(
                        "subscript_p",
                        "ArraySubscriptExpr",
                        14,
                        _wrap("cast_p", "ImplicitCastExpr", 14, _declref("ref_p_read", "p", 14, "S *")),
                    ),
                    name="f",
                ),
                kind="CompoundAssignOperator",
            ),
            {
                "id": "incr_n",
                "kind": "UnaryOperator",
                "opcode": "++",
                "loc": {"line": 15, "col": 5},
                "range": {"begin": {"line": 15, "col": 5}, "end": {"line": 15, "col": 8}},
                "inner": [_declref("ref_n", "n", 15)],
            },
        ],
    }
    ast = {
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "id": "for_outer",
                "kind": "ForStmt",
                "loc": {"file": "kernel.c", "line": 10, "col": 5},
                "range": {"begin": {"line": 10, "col": 5}, "end": {"line": 17, "col": 5}},
                "inner": [
                    # a cast around the LHS must stay transparent
                    _assign(
                        "assign_p",
                        "=",
                        11,
                        _wrap("cast_p_write", "ImplicitCastExpr", 11, _declref("ref_p", "p", 11, "S *")),
                    ),
                    inner_for,
                ],
            }
        ],
    }
    return ClangASTGraph().build_from_ast(ast)


class TestFindVariablesAssignedInLoopAt:
    def test_direct_assignment_is_reported(self, assignment_graph: nx.DiGraph[str]) -> None:
        assigned = ASTVariableAndTypeQueries.find_variables_assigned_in_loop_at(assignment_graph, "kernel.c", 10)
        assert "p" in assigned
        assert "q" in assigned

    def test_write_through_pointer_is_not_reported(self, assignment_graph: nx.DiGraph[str]) -> None:
        """``p[k].f += 1`` writes the memory p points at, so it must not mark p as assigned.

        This is the distinction the profiler's dependency data cannot express: it labels that
        access "p" just like the ``p = &a[i]`` above it.
        """
        assigned = ASTVariableAndTypeQueries.find_variables_assigned_in_loop_at(assignment_graph, "kernel.c", 14)
        # no loop starts on line 14
        assert assigned == set()

        inner = ASTVariableAndTypeQueries.find_variables_assigned_in_loop_at(assignment_graph, "kernel.c", 12)
        # q and n are assigned inside the inner loop; p only receives a write *through* it
        assert inner == {"q", "n"}

    def test_increment_operator_counts_as_assignment(self, assignment_graph: nx.DiGraph[str]) -> None:
        assigned = ASTVariableAndTypeQueries.find_variables_assigned_in_loop_at(assignment_graph, "kernel.c", 10)
        assert "n" in assigned

    def test_enclosing_loop_assignment_excluded_from_inner_loop(self, assignment_graph: nx.DiGraph[str]) -> None:
        """The loop's own AST range bounds the answer, so p (assigned in the outer loop only)
        is not reported for the inner loop."""
        outer = ASTVariableAndTypeQueries.find_variables_assigned_in_loop_at(assignment_graph, "kernel.c", 10)
        inner = ASTVariableAndTypeQueries.find_variables_assigned_in_loop_at(assignment_graph, "kernel.c", 12)
        assert "p" in outer
        assert "p" not in inner

    def test_no_loop_at_line_returns_empty(self, assignment_graph: nx.DiGraph[str]) -> None:
        assert ASTVariableAndTypeQueries.find_variables_assigned_in_loop_at(assignment_graph, "kernel.c", 99) == set()

    def test_unknown_file_returns_empty(self, assignment_graph: nx.DiGraph[str]) -> None:
        assert ASTVariableAndTypeQueries.find_variables_assigned_in_loop_at(assignment_graph, "other.c", 10) == set()


class TestFindLoopAtLocation:
    def test_finds_loop_beginning_on_line(self, assignment_graph: nx.DiGraph[str]) -> None:
        assert ASTQueries.find_loop_at_location(assignment_graph, "kernel.c", 12) == "for_inner"

    def test_line_inside_loop_body_is_not_a_loop_header(self, assignment_graph: nx.DiGraph[str]) -> None:
        """Line 14 lies within both loops' ranges but starts neither of them."""
        assert ASTQueries.find_loop_at_location(assignment_graph, "kernel.c", 14) is None

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for ClangASTGraph.

All fixtures use real Clang AST JSON field names:
  * ``file`` is a plain string (only present when it changes from context)
  * column key is ``"col"`` (not ``"column"``)
  * ``line`` / ``file`` may be absent from child nodes (location inheritance)
  * ``spellingLoc`` / ``expansionLoc`` used for macro positions
"""

from __future__ import annotations

import pytest

from discopop_explorer.utilities.ASTUtils.ASTGraph import ClangASTGraph


def _make_builder() -> ClangASTGraph:
    return ClangASTGraph()


class TestClangASTGraph:
    def test_build_empty_ast(self) -> None:
        graph = _make_builder().build_from_ast({})
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_build_single_node_ast(self) -> None:
        ast = {"kind": "TranslationUnitDecl", "inner": []}
        graph = _make_builder().build_from_ast(ast)
        assert len(graph.nodes) == 1
        assert len(graph.edges) == 0

    def test_build_tree_structure(self) -> None:
        ast = {
            "kind": "TranslationUnitDecl",
            "inner": [
                {
                    "kind": "FunctionDecl",
                    "name": "foo",
                    "inner": [
                        {"kind": "VarDecl", "name": "x", "inner": []},
                        {"kind": "VarDecl", "name": "y", "inner": []},
                    ],
                }
            ],
        }
        graph = _make_builder().build_from_ast(ast)
        assert len(graph.nodes) == 4
        assert len(graph.edges) == 3

    def test_node_attributes_preserved(self) -> None:
        """Node kind / name / type are stored correctly."""
        ast = {
            "id": "0x1",
            "kind": "FunctionDecl",
            "name": "foo",
            "type": "int ()",
            # Real Clang format: file is a string, column key is "col"
            "loc": {"file": "test.cpp", "line": 1, "col": 1},
            "range": {
                "begin": {"col": 1},
                "end": {"line": 5, "col": 1},
            },
            "inner": [],
        }
        graph = _make_builder().build_from_ast(ast)
        node_id = "0x1"
        assert graph.nodes[node_id]["kind"] == "FunctionDecl"
        assert graph.nodes[node_id]["name"] == "foo"
        assert graph.nodes[node_id]["type"] == "int ()"

    def test_inner_array_preserved(self) -> None:
        ast = {
            "kind": "FunctionDecl",
            "name": "foo",
            "inner": [{"kind": "VarDecl", "name": "x", "inner": []}],
        }
        graph = _make_builder().build_from_ast(ast)
        fn_node = next(n for n, a in graph.nodes(data=True) if a["kind"] == "FunctionDecl")
        assert isinstance(graph.nodes[fn_node]["inner"], list)
        assert len(graph.nodes[fn_node]["inner"]) == 1

    # --- real format: file as string, "col" key ---

    def test_loc_file_stored_as_string(self) -> None:
        """file is stored as plain string, not as a nested dict."""
        ast = {
            "id": "0x1",
            "kind": "FunctionDecl",
            "name": "foo",
            "loc": {"file": "test.cpp", "line": 1, "col": 5},
            "inner": [],
        }
        graph = _make_builder().build_from_ast(ast)
        loc = graph.nodes["0x1"]["loc"]
        assert loc["file"] == "test.cpp"

    def test_loc_col_mapped_to_column_key(self) -> None:
        """Clang 'col' is stored under the 'column' key for API consistency."""
        ast = {
            "id": "0x1",
            "kind": "FunctionDecl",
            "name": "foo",
            "loc": {"file": "test.cpp", "line": 3, "col": 7},
            "inner": [],
        }
        graph = _make_builder().build_from_ast(ast)
        loc = graph.nodes["0x1"]["loc"]
        assert loc["column"] == 7
        assert loc["line"] == 3

    def test_file_inheritance_from_parent(self) -> None:
        """Child node without explicit file inherits it from the parent."""
        ast = {
            "id": "0x1",
            "kind": "FunctionDecl",
            "name": "foo",
            "loc": {"file": "test.cpp", "line": 1, "col": 1},
            "inner": [
                {
                    "id": "0x2",
                    "kind": "VarDecl",
                    "name": "x",
                    "loc": {"line": 2, "col": 5},  # no "file" — inherited
                    "inner": [],
                }
            ],
        }
        graph = _make_builder().build_from_ast(ast)
        var_loc = graph.nodes["0x2"]["loc"]
        assert var_loc["file"] == "test.cpp", "file must be inherited from FunctionDecl"
        assert var_loc["line"] == 2
        assert var_loc["column"] == 5

    def test_range_col_mapped_to_begin_end_column(self) -> None:
        """Range endpoints use begin_column / end_column (mapped from 'col')."""
        ast = {
            "id": "0x1",
            "kind": "FunctionDecl",
            "name": "foo",
            "loc": {"file": "test.cpp", "line": 1, "col": 1},
            "range": {
                "begin": {"col": 1},
                "end": {"line": 5, "col": 2},
            },
            "inner": [],
        }
        graph = _make_builder().build_from_ast(ast)
        r = graph.nodes["0x1"]["range"]
        assert r["begin_column"] == 1
        assert r["end_column"] == 2
        assert r["end_line"] == 5

    def test_range_line_fallback_to_loc_line(self) -> None:
        """Range begin without explicit line falls back to the node's loc line."""
        ast = {
            "id": "0x1",
            "kind": "FunctionDecl",
            "name": "foo",
            "loc": {"file": "test.cpp", "line": 4, "col": 1},
            "range": {
                "begin": {"col": 1},  # no line → should use loc line (4)
                "end": {"line": 10, "col": 1},
            },
            "inner": [],
        }
        graph = _make_builder().build_from_ast(ast)
        r = graph.nodes["0x1"]["range"]
        assert r["begin_line"] == 4

    def test_spellingloc_unwrapped(self) -> None:
        """spellingLoc wrapper is unwrapped; its fields are used directly."""
        ast = {
            "id": "0x1",
            "kind": "FunctionDecl",
            "name": "macro_fn",
            "loc": {
                "spellingLoc": {
                    "file": "real.cpp",
                    "line": 10,
                    "col": 3,
                }
            },
            "inner": [],
        }
        graph = _make_builder().build_from_ast(ast)
        loc = graph.nodes["0x1"]["loc"]
        assert loc["file"] == "real.cpp"
        assert loc["line"] == 10
        assert loc["column"] == 3

    def test_expansionloc_used_when_no_spellingloc(self) -> None:
        """expansionLoc is used when spellingLoc is absent."""
        ast = {
            "id": "0x1",
            "kind": "CallExpr",
            "loc": {
                "expansionLoc": {
                    "file": "macro.cpp",
                    "line": 20,
                    "col": 5,
                }
            },
            "inner": [],
        }
        graph = _make_builder().build_from_ast(ast)
        loc = graph.nodes["0x1"]["loc"]
        assert loc["file"] == "macro.cpp"
        assert loc["line"] == 20

    def test_node_id_from_clang_field(self) -> None:
        """Explicit 'id' from Clang JSON is used as the node ID."""
        ast = {"id": "0xABCD", "kind": "TranslationUnitDecl", "inner": []}
        graph = _make_builder().build_from_ast(ast)
        assert "0xABCD" in graph.nodes

    def test_node_id_autogenerated_when_absent(self) -> None:
        """Nodes without 'id' receive auto-generated IDs."""
        ast = {
            "kind": "TranslationUnitDecl",
            "inner": [
                {"kind": "FunctionDecl", "name": "f", "inner": []},
                {"kind": "FunctionDecl", "name": "g", "inner": []},
            ],
        }
        graph = _make_builder().build_from_ast(ast)
        assert len(graph.nodes) == 3
        assert len(set(graph.nodes())) == 3  # all IDs distinct

    def test_multiple_builds_reset_state(self) -> None:
        """A second build on the same builder produces a clean graph."""
        builder = _make_builder()
        ast1 = {"kind": "TranslationUnitDecl", "inner": [{"kind": "FunctionDecl", "inner": []}]}
        ast2 = {
            "kind": "TranslationUnitDecl",
            "inner": [
                {"kind": "FunctionDecl", "inner": []},
                {"kind": "FunctionDecl", "inner": []},
            ],
        }
        graph1 = builder.build_from_ast(ast1)
        assert len(graph1.nodes) == 2
        graph2 = builder.build_from_ast(ast2)
        assert len(graph2.nodes) == 3

    def test_parent_child_relationships(self) -> None:
        """Edges point from parent to child with relation='child'."""
        ast = {
            "kind": "FunctionDecl",
            "name": "foo",
            "inner": [
                {"kind": "VarDecl", "name": "x", "inner": []},
                {"kind": "VarDecl", "name": "y", "inner": []},
            ],
        }
        graph = _make_builder().build_from_ast(ast)
        assert len(graph.nodes) == 3
        for _, _, eattrs in graph.edges(data=True):
            assert eattrs.get("relation") == "child"

    def test_complex_nested_structure(self) -> None:
        ast = {
            "kind": "TranslationUnitDecl",
            "inner": [
                {
                    "kind": "FunctionDecl",
                    "name": "main",
                    "inner": [
                        {
                            "kind": "CompoundStmt",
                            "inner": [
                                {"kind": "VarDecl", "name": "x", "inner": []},
                                {
                                    "kind": "ForStmt",
                                    "inner": [{"kind": "VarDecl", "name": "i", "inner": []}],
                                },
                            ],
                        }
                    ],
                }
            ],
        }
        graph = _make_builder().build_from_ast(ast)
        assert len(graph.nodes) == 6
        assert len(graph.edges) == 5

    def test_file_inherited_across_siblings(self) -> None:
        """Clang omits 'file' from siblings after the first occurrence.

        The second FunctionDecl has no 'file' in its loc — it must inherit
        the file set by the first FunctionDecl sibling, not the parent's
        (None) context.
        """
        ast = {
            "kind": "TranslationUnitDecl",
            "loc": {},
            "inner": [
                {
                    "id": "0x1",
                    "kind": "FunctionDecl",
                    "name": "foo",
                    "loc": {"file": "test.cpp", "line": 1, "col": 1},
                    "inner": [],
                },
                {
                    "id": "0x2",
                    "kind": "FunctionDecl",
                    "name": "bar",
                    # No 'file' key — should inherit "test.cpp" from sibling 0x1
                    "loc": {"line": 10, "col": 1},
                    "inner": [],
                },
            ],
        }
        graph = _make_builder().build_from_ast(ast)
        assert graph.nodes["0x2"]["loc"]["file"] == "test.cpp"

    def test_file_updated_when_sibling_changes_it(self) -> None:
        """A sibling that introduces a new file must not affect previous siblings."""
        ast = {
            "kind": "TranslationUnitDecl",
            "loc": {},
            "inner": [
                {
                    "id": "0x1",
                    "kind": "FunctionDecl",
                    "name": "foo",
                    "loc": {"file": "a.cpp", "line": 1, "col": 1},
                    "inner": [],
                },
                {
                    "id": "0x2",
                    "kind": "FunctionDecl",
                    "name": "bar",
                    "loc": {"file": "b.cpp", "line": 5, "col": 1},
                    "inner": [],
                },
                {
                    "id": "0x3",
                    "kind": "FunctionDecl",
                    "name": "baz",
                    # No file — should inherit "b.cpp" from sibling 0x2
                    "loc": {"line": 10, "col": 1},
                    "inner": [],
                },
            ],
        }
        graph = _make_builder().build_from_ast(ast)
        assert graph.nodes["0x1"]["loc"]["file"] == "a.cpp"
        assert graph.nodes["0x2"]["loc"]["file"] == "b.cpp"
        assert graph.nodes["0x3"]["loc"]["file"] == "b.cpp"


class TestNormalizeFilePaths:
    def test_relative_path_replaced(self) -> None:
        """Bare filenames in loc are replaced with the canonical absolute path."""
        ast = {
            "id": "0x1",
            "kind": "FunctionDecl",
            "name": "foo",
            "loc": {"file": "test.cpp", "line": 1, "col": 1},
            "inner": [],
        }
        graph = _make_builder().build_from_ast(ast)
        ClangASTGraph.normalize_file_paths(graph, {"test.cpp": "/home/user/project/test.cpp"})
        assert graph.nodes["0x1"]["loc"]["file"] == "/home/user/project/test.cpp"

    def test_unmapped_path_left_unchanged(self) -> None:
        """Paths not in the mapping are not modified."""
        ast = {
            "id": "0x1",
            "kind": "FunctionDecl",
            "name": "foo",
            "loc": {"file": "/usr/include/stdio.h", "line": 1, "col": 1},
            "inner": [],
        }
        graph = _make_builder().build_from_ast(ast)
        ClangASTGraph.normalize_file_paths(graph, {"test.cpp": "/home/user/project/test.cpp"})
        assert graph.nodes["0x1"]["loc"]["file"] == "/usr/include/stdio.h"

    def test_empty_mapping_is_noop(self) -> None:
        """An empty mapping leaves the graph completely untouched."""
        ast = {
            "id": "0x1",
            "kind": "FunctionDecl",
            "name": "foo",
            "loc": {"file": "test.cpp", "line": 1, "col": 1},
            "inner": [],
        }
        graph = _make_builder().build_from_ast(ast)
        ClangASTGraph.normalize_file_paths(graph, {})
        assert graph.nodes["0x1"]["loc"]["file"] == "test.cpp"


class TestRangeBeginLineFallback:
    """Tests for the range.begin.line fallback when loc omits line.

    Clang wrapper nodes (e.g. DeclStmt) often carry no ``loc`` field at all
    while their ``range.begin`` correctly records the actual source line.
    Without the fallback, every descendant inside such a wrapper would
    inherit the wrong line from the previous sibling context.
    """

    def test_declstmt_wrapper_propagates_correct_line_to_child(self) -> None:
        """VarDecl inside a no-loc DeclStmt must get the DeclStmt's range.begin.line."""
        ast = {
            "kind": "TranslationUnitDecl",
            "inner": [
                {
                    "id": "fn",
                    "kind": "FunctionDecl",
                    "name": "main",
                    "loc": {"file": "test.cpp", "line": 1, "col": 1},
                    "range": {"begin": {"line": 1, "col": 1}, "end": {"line": 10, "col": 1}},
                    "inner": [
                        {
                            "id": "for_stmt",
                            "kind": "ForStmt",
                            "loc": {"line": 3, "col": 3},
                            "range": {"begin": {"col": 3}, "end": {"line": 7, "col": 3}},
                            "inner": [
                                {
                                    "id": "var_i",
                                    "kind": "VarDecl",
                                    "name": "i",
                                    "loc": {"line": 3, "col": 8},
                                    "range": {"begin": {"col": 8}, "end": {"col": 9}},
                                    "inner": [],
                                },
                                # DeclStmt has no loc, only range.begin with line 4
                                {
                                    "id": "decl_stmt",
                                    "kind": "DeclStmt",
                                    "range": {
                                        "begin": {"line": 4, "col": 5},
                                        "end": {"col": 20},
                                    },
                                    "inner": [
                                        # VarDecl inside DeclStmt also has no line in loc
                                        {
                                            "id": "var_ielem",
                                            "kind": "VarDecl",
                                            "name": "ielem",
                                            "loc": {"col": 10},
                                            "range": {"begin": {"col": 5}, "end": {"col": 20}},
                                            "inner": [],
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            ],
        }
        graph = _make_builder().build_from_ast(ast)
        # DeclStmt should get line 4 from range.begin (not inherit line 3 from ForStmt)
        assert graph.nodes["decl_stmt"]["loc"]["line"] == 4
        # VarDecl ielem should also get line 4 (inheriting from DeclStmt's resolved line)
        assert graph.nodes["var_ielem"]["loc"]["line"] == 4

    def test_sibling_after_declstmt_inherits_correct_line(self) -> None:
        """A sibling following a no-loc DeclStmt must see the DeclStmt's line, not the previous one."""
        ast = {
            "kind": "TranslationUnitDecl",
            "inner": [
                {
                    "id": "fn",
                    "kind": "FunctionDecl",
                    "loc": {"file": "test.cpp", "line": 1, "col": 1},
                    "range": {"begin": {"col": 1}, "end": {"line": 20, "col": 1}},
                    "inner": [
                        {
                            "id": "var_x",
                            "kind": "VarDecl",
                            "name": "x",
                            "loc": {"line": 2, "col": 5},
                            "range": {"begin": {"col": 5}, "end": {"col": 6}},
                            "inner": [],
                        },
                        # DeclStmt with no loc, range.begin line 5
                        {
                            "id": "ds",
                            "kind": "DeclStmt",
                            "range": {"begin": {"line": 5, "col": 3}, "end": {"col": 10}},
                            "inner": [],
                        },
                        # The next sibling should inherit line 5, not line 2
                        {
                            "id": "ret",
                            "kind": "ReturnStmt",
                            "loc": {"col": 3},
                            "range": {"begin": {"line": 8, "col": 3}, "end": {"col": 10}},
                            "inner": [],
                        },
                    ],
                }
            ],
        }
        graph = _make_builder().build_from_ast(ast)
        # DeclStmt gets line 5 from its range.begin
        assert graph.nodes["ds"]["loc"]["line"] == 5
        # ReturnStmt has explicit range.begin.line=8, so it wins regardless
        assert graph.nodes["ret"]["loc"]["line"] == 8

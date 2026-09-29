# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Test AST integration with pattern detection.

Fixtures use real Clang AST JSON format (file as string, "col" key,
location inheritance).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from discopop_explorer.pattern_detection import PatternDetectorX


@pytest.fixture  # type: ignore[misc]
def sample_ast_project() -> Any:
    """Create a temporary project with an ast_dump.json in real Clang format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ast_dir = Path(tmpdir) / "profiler"
        ast_dir.mkdir(parents=True)

        # Real Clang JSON format:
        #   * file is a plain string, only present when it changes
        #   * column key is "col"
        #   * child nodes inherit file/line when absent
        ast_dump = {
            "kind": "TranslationUnitDecl",
            "inner": [
                {
                    "id": "fn_compute",
                    "kind": "FunctionDecl",
                    "name": "compute",
                    "type": "int ()",
                    "loc": {"file": "compute.cpp", "line": 1, "col": 5},
                    "range": {"begin": {"col": 1}, "end": {"line": 20, "col": 1}},
                    "inner": [
                        {
                            "id": "var_sum",
                            "kind": "VarDecl",
                            "name": "sum",
                            "type": "int",
                            # file inherited from FunctionDecl
                            "loc": {"line": 2, "col": 5},
                            "range": {"begin": {"col": 5}, "end": {"col": 12}},
                            "inner": [],
                        },
                        {
                            "id": "var_product",
                            "kind": "VarDecl",
                            "name": "product",
                            "type": "double",
                            "loc": {"line": 3, "col": 5},
                            "range": {"begin": {"col": 5}, "end": {"col": 15}},
                            "inner": [],
                        },
                        {
                            "id": "for_loop",
                            "kind": "ForStmt",
                            "loc": {"line": 5, "col": 5},
                            "range": {"begin": {"col": 5}, "end": {"line": 10, "col": 5}},
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
                    ],
                }
            ],
        }

        ast_file = ast_dir / "ast_dump.json"
        with open(ast_file, "w") as f:
            json.dump(ast_dump, f)

        yield tmpdir


class TestPatternDetectorASTIntegration:
    def test_ast_graph_loaded_on_detect_patterns(self, sample_ast_project: str) -> None:
        pet = MagicMock()
        detector = PatternDetectorX(pet)

        assert not detector.ast_helper.is_ast_loaded()

        detector.ast_helper.load_ast_from_project(sample_ast_project)

        assert detector.ast_helper.is_ast_loaded()
        graph = detector.ast_helper.get_ast_graph()
        assert graph is not None
        assert len(graph.nodes) > 0

    def test_get_variables_at_location(self, sample_ast_project: str) -> None:
        pet = MagicMock()
        detector = PatternDetectorX(pet)
        detector.ast_helper.load_ast_from_project(sample_ast_project)

        # Line 6 is inside the ForStmt range (lines 5-10)
        variables = detector.ast_helper.get_variables_at_location("compute.cpp", 6, 5)

        assert len(variables) > 0
        var_names = [name for name, _ in variables]
        assert any(name in var_names for name in ["sum", "product", "i"])

    def test_get_variable_declarations_in_scope(self, sample_ast_project: str) -> None:
        pet = MagicMock()
        detector = PatternDetectorX(pet)
        detector.ast_helper.load_ast_from_project(sample_ast_project)

        variables = detector.ast_helper.get_variable_declarations_in_scope("compute")

        assert len(variables) > 0
        var_names = [name for name, _ in variables]
        assert "sum" in var_names or "product" in var_names

    def test_get_ast_statistics(self, sample_ast_project: str) -> None:
        pet = MagicMock()
        detector = PatternDetectorX(pet)
        detector.ast_helper.load_ast_from_project(sample_ast_project)

        stats = detector.ast_helper.get_ast_statistics()

        assert stats is not None
        assert stats["num_nodes"] > 0
        assert "num_edges" in stats
        assert "node_kinds" in stats
        assert "num_connected_components" in stats

    def test_get_ast_visualization(self, sample_ast_project: str) -> None:
        pet = MagicMock()
        detector = PatternDetectorX(pet)
        detector.ast_helper.load_ast_from_project(sample_ast_project)

        dot = detector.ast_helper.get_ast_visualization()

        assert dot is not None
        assert "digraph" in dot
        assert "compute" in dot or "FunctionDecl" in dot
        assert "->" in dot

    def test_print_ast_structure(self, sample_ast_project: str, capsys: Any) -> None:
        pet = MagicMock()
        detector = PatternDetectorX(pet)
        detector.ast_helper.load_ast_from_project(sample_ast_project)

        detector.ast_helper.print_ast_structure(max_depth=2)

        assert len(capsys.readouterr().out) > 0

    def test_no_ast_graceful_handling(self) -> None:
        pet = MagicMock()
        detector = PatternDetectorX(pet)

        assert detector.ast_helper.get_variables_at_location("test.cpp", 1, 1) == []
        assert detector.ast_helper.get_variable_declarations_in_scope("test_func") == []
        assert detector.ast_helper.get_ast_statistics() is None
        assert detector.ast_helper.get_ast_visualization() is None

    def test_invalid_project_path_handled(self) -> None:
        pet = MagicMock()
        detector = PatternDetectorX(pet)

        detector.ast_helper.load_ast_from_project("/nonexistent/project")

        assert not detector.ast_helper.is_ast_loaded()

    def test_file_inheritance_in_loaded_graph(self, sample_ast_project: str) -> None:
        """Child nodes without explicit file must still resolve to the correct file."""
        pet = MagicMock()
        detector = PatternDetectorX(pet)
        detector.ast_helper.load_ast_from_project(sample_ast_project)

        graph = detector.ast_helper.get_ast_graph()
        assert graph is not None

        # var_sum has no explicit file in its loc → must inherit "compute.cpp"
        var_sum = graph.nodes.get("var_sum")
        assert var_sum is not None
        assert var_sum["loc"]["file"] == "compute.cpp"

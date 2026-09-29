# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for ASTPatternDetectionHelper.get_variables_at_location (file-ID variant)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import pytest

from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper


def _write_project(
    tmpdir: str,
    ast: dict[str, object],
    file_mapping_lines: list[str],
) -> str:
    """Write a minimal DiscoPoP project layout and return the project path."""
    project = Path(tmpdir)
    profiler = project / "profiler"
    profiler.mkdir(parents=True)

    (profiler / "ast_dump.json").write_text(json.dumps(ast))
    (project / "FileMapping.txt").write_text("\n".join(file_mapping_lines) + "\n")
    return str(project)


def _make_ast(filename: str) -> dict[str, object]:
    """Minimal AST with one function containing one variable at line 2."""
    return {
        "id": "0x1",
        "kind": "TranslationUnitDecl",
        "inner": [
            {
                "id": "0x2",
                "kind": "FunctionDecl",
                "name": "foo",
                "loc": {"file": filename, "line": 1, "col": 1},
                "range": {"begin": {"line": 1, "col": 1}, "end": {"line": 10, "col": 1}},
                "inner": [
                    {
                        "id": "0x3",
                        "kind": "VarDecl",
                        "name": "x",
                        "type": {"qualType": "int"},
                        "loc": {"line": 2, "col": 5},
                        "range": {"begin": {"col": 5}, "end": {"col": 9}},
                        "inner": [],
                    }
                ],
            }
        ],
    }


class TestGetVariablesAtLocationByFileID:
    def test_returns_variable_for_valid_file_id(self) -> None:
        """Variable declared in a function is returned when queried by file ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # AST uses an absolute path that matches the FileMapping entry directly
            abs_path = str(Path(tmpdir) / "test.cpp")
            Path(abs_path).write_text("int foo() { int x = 0; return x; }")
            project = _write_project(tmpdir, _make_ast(abs_path), [f"1\t{abs_path}"])

            h = ASTPatternDetectionHelper()
            h.load_ast_from_project(project)

            result = h.get_variables_at_location(file_id=1, line=5, column=1)
            var_names = [name for name, _ in result]
            assert "x" in var_names

    def test_unknown_file_id_returns_empty(self) -> None:
        """Unknown file ID produces an empty list without raising."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abs_path = str(Path(tmpdir) / "test.cpp")
            Path(abs_path).write_text("")
            project = _write_project(tmpdir, _make_ast(abs_path), [f"1\t{abs_path}"])

            h = ASTPatternDetectionHelper()
            h.load_ast_from_project(project)

            assert h.get_variables_at_location(file_id=99, line=5, column=1) == []

    def test_no_ast_returns_empty(self) -> None:
        """Calling get_variables_at_location before loading returns empty list."""
        h = ASTPatternDetectionHelper()
        assert h.get_variables_at_location(file_id=1, line=1, column=1) == []

    def test_path_normalisation_via_basename(self) -> None:
        """Bare filename in AST is resolved through FileMapping so the file-ID lookup works."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abs_path = str(Path(tmpdir) / "test.cpp")
            Path(abs_path).write_text("")
            # AST stores only the basename; FileMapping has the absolute path
            project = _write_project(tmpdir, _make_ast("test.cpp"), [f"1\t{abs_path}"])

            h = ASTPatternDetectionHelper()
            h.load_ast_from_project(project)

            result = h.get_variables_at_location(file_id=1, line=5, column=1)
            var_names = [name for name, _ in result]
            assert "x" in var_names

    def test_missing_file_mapping_returns_empty(self) -> None:
        """Missing FileMapping.txt does not crash; file-ID lookup returns empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abs_path = str(Path(tmpdir) / "test.cpp")
            Path(abs_path).write_text("")
            project = Path(tmpdir) / "project"
            project.mkdir()
            profiler = project / "profiler"
            profiler.mkdir()
            (profiler / "ast_dump.json").write_text(json.dumps(_make_ast(abs_path)))
            # No FileMapping.txt written

            h = ASTPatternDetectionHelper()
            h.load_ast_from_project(str(project))

            assert h.get_variables_at_location(file_id=1, line=5, column=1) == []

    def test_file_mapping_loaded_as_attribute(self) -> None:
        """file_mapping attribute is populated after load_ast_from_project."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abs_path = str(Path(tmpdir) / "test.cpp")
            Path(abs_path).write_text("")
            project = _write_project(tmpdir, _make_ast(abs_path), [f"1\t{abs_path}", f"2\t{abs_path}"])

            h = ASTPatternDetectionHelper()
            h.load_ast_from_project(project)

            assert 1 in h.file_mapping
            assert 2 in h.file_mapping

    def test_no_column_returns_variables_on_line(self) -> None:
        """Omitting column returns variables for any column on the given line."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abs_path = str(Path(tmpdir) / "test.cpp")
            Path(abs_path).write_text("")
            project = _write_project(tmpdir, _make_ast(abs_path), [f"1\t{abs_path}"])

            h = ASTPatternDetectionHelper()
            h.load_ast_from_project(project)

            result = h.get_variables_at_location(file_id=1, line=5)
            var_names = [name for name, _ in result]
            assert "x" in var_names

    def test_no_column_superset_of_with_column(self) -> None:
        """Results without column are a superset of results with an explicit column."""
        with tempfile.TemporaryDirectory() as tmpdir:
            abs_path = str(Path(tmpdir) / "test.cpp")
            Path(abs_path).write_text("")
            project = _write_project(tmpdir, _make_ast(abs_path), [f"1\t{abs_path}"])

            h = ASTPatternDetectionHelper()
            h.load_ast_from_project(project)

            with_col = set(h.get_variables_at_location(file_id=1, line=5, column=1))
            no_col = set(h.get_variables_at_location(file_id=1, line=5))
            assert with_col.issubset(no_col)

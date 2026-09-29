# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import tempfile
from pathlib import Path

import pytest

from discopop_explorer.utilities.ASTUtils.ASTLoader import ClangASTLoader


class TestClangASTLoader:
    """Tests for ClangASTLoader"""

    def test_load_ast_from_valid_file(self) -> None:
        """Test loading AST from a valid JSON file"""
        test_ast = {
            "kind": "TranslationUnitDecl",
            "name": "test.cpp",
            "inner": [],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            ast_file = Path(tmpdir) / "ast_dump.json"
            with open(ast_file, "w") as f:
                json.dump(test_ast, f)

            result = ClangASTLoader.load_ast(str(ast_file))
            assert result["kind"] == "TranslationUnitDecl"
            assert result["name"] == "test.cpp"

    def test_load_ast_file_not_found(self) -> None:
        """Test loading AST from nonexistent file raises FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            ClangASTLoader.load_ast("/nonexistent/path/ast_dump.json")

    def test_load_ast_invalid_json(self) -> None:
        """Test loading invalid JSON raises JSONDecodeError"""
        with tempfile.TemporaryDirectory() as tmpdir:
            ast_file = Path(tmpdir) / "ast_dump.json"
            with open(ast_file, "w") as f:
                f.write("invalid json {")

            with pytest.raises(json.JSONDecodeError):
                ClangASTLoader.load_ast(str(ast_file))

    def test_load_ast_is_directory(self) -> None:
        """Test loading AST from directory raises ValueError"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(ValueError, match="is not a file"):
                ClangASTLoader.load_ast(tmpdir)

    def test_load_ast_from_project_existing(self) -> None:
        """Test loading AST from project with existing ast_dump.json"""
        test_ast = {"kind": "TranslationUnitDecl", "inner": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            project_path = Path(tmpdir)
            ast_dir = project_path / "profiler"
            ast_dir.mkdir(parents=True)

            ast_file = ast_dir / "ast_dump.json"
            with open(ast_file, "w") as f:
                json.dump(test_ast, f)

            result = ClangASTLoader.load_ast_from_project(str(project_path))
            assert result is not None
            assert result["kind"] == "TranslationUnitDecl"

    def test_load_ast_from_project_nonexistent(self) -> None:
        """Test loading AST from project without ast_dump.json returns None"""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ClangASTLoader.load_ast_from_project(tmpdir)
            assert result is None

    def test_load_ast_with_nested_structure(self) -> None:
        """Test loading complex AST with nested nodes"""
        test_ast = {
            "kind": "TranslationUnitDecl",
            "inner": [
                {
                    "kind": "FunctionDecl",
                    "name": "foo",
                    "type": "int ()",
                    "inner": [
                        {
                            "kind": "VarDecl",
                            "name": "x",
                            "type": "int",
                            "inner": [],
                        }
                    ],
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            ast_file = Path(tmpdir) / "ast_dump.json"
            with open(ast_file, "w") as f:
                json.dump(test_ast, f)

            result = ClangASTLoader.load_ast(str(ast_file))
            assert len(result["inner"]) == 1
            assert result["inner"][0]["kind"] == "FunctionDecl"
            assert len(result["inner"][0]["inner"]) == 1

    def test_load_ast_multiple_translation_units(self) -> None:
        """Multiple concatenated JSON objects are wrapped in a synthetic root."""
        tu1 = {
            "kind": "TranslationUnitDecl",
            "id": "0x1",
            "inner": [{"kind": "FunctionDecl", "name": "foo", "inner": []}],
        }
        tu2 = {
            "kind": "TranslationUnitDecl",
            "id": "0x2",
            "inner": [{"kind": "FunctionDecl", "name": "bar", "inner": []}],
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            ast_file = Path(tmpdir) / "ast_dump.json"
            with open(ast_file, "w") as f:
                f.write(json.dumps(tu1))
                f.write("\n")
                f.write(json.dumps(tu2))

            result = ClangASTLoader.load_ast(str(ast_file))
            assert result["kind"] == "TranslationUnitDecl"
            assert len(result["inner"]) == 2
            assert result["inner"][0]["id"] == "0x1"
            assert result["inner"][1]["id"] == "0x2"

    def test_load_ast_single_tu_not_wrapped(self) -> None:
        """A single-TU file returns the object directly (no extra wrapper)."""
        tu = {"kind": "TranslationUnitDecl", "id": "0xABC", "inner": []}

        with tempfile.TemporaryDirectory() as tmpdir:
            ast_file = Path(tmpdir) / "ast_dump.json"
            with open(ast_file, "w") as f:
                json.dump(tu, f)

            result = ClangASTLoader.load_ast(str(ast_file))
            assert result["id"] == "0xABC"


class TestBuildPathMapping:
    def test_relative_basename_matched(self) -> None:
        """Bare filename in AST is resolved to absolute path from FileMapping."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fmap = Path(tmpdir) / "FileMapping.txt"
            fmap.write_text("1\t/home/user/project/test.cpp\n2\t/home/user/project/util.cpp\n")

            mapping = ClangASTLoader.build_path_mapping(str(fmap), {"test.cpp", "util.cpp"})

            assert mapping["test.cpp"] == "/home/user/project/test.cpp"
            assert mapping["util.cpp"] == "/home/user/project/util.cpp"

    def test_dot_relative_path_matched(self) -> None:
        """Paths Clang records relative to the compilation dir ("./kernel/kernel.c") are resolved.

        Regression guard: without collapsing the leading "./" the suffix match against the
        absolute FileMapping entry fails, every node of that file keeps a non-canonical
        path, and location lookups against it silently return nothing.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            fmap = Path(tmpdir) / "FileMapping.txt"
            fmap.write_text("1\t/proj/main.c\n2\t/proj/kernel/kernel_cpu.c\n")

            mapping = ClangASTLoader.build_path_mapping(str(fmap), {"./kernel/kernel_cpu.c"})

            assert mapping["./kernel/kernel_cpu.c"] == "/proj/kernel/kernel_cpu.c"

    def test_dot_dot_relative_path_matched(self) -> None:
        """ "." and ".." segments anywhere in the AST path are collapsed before matching."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fmap = Path(tmpdir) / "FileMapping.txt"
            fmap.write_text("1\t/proj/main.h\n2\t/proj/util/timer/timer.h\n")

            mapping = ClangASTLoader.build_path_mapping(
                str(fmap), {"././main.h", "./kernel/./../main.h", "./kernel/./../util/timer/timer.h"}
            )

            assert mapping["././main.h"] == "/proj/main.h"
            assert mapping["./kernel/./../main.h"] == "/proj/main.h"
            assert mapping["./kernel/./../util/timer/timer.h"] == "/proj/util/timer/timer.h"

    def test_absolute_path_with_dot_segments_matched(self) -> None:
        """An absolute AST path carrying "." / ".." segments maps onto its canonical form."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fmap = Path(tmpdir) / "FileMapping.txt"
            fmap.write_text("1\t/proj/test.cpp\n")

            mapping = ClangASTLoader.build_path_mapping(str(fmap), {"/proj/./sub/../test.cpp"})

            assert mapping["/proj/./sub/../test.cpp"] == "/proj/test.cpp"

    def test_already_canonical_path_not_remapped(self) -> None:
        """Paths that already match a FileMapping entry are not included in the result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fmap = Path(tmpdir) / "FileMapping.txt"
            fmap.write_text("1\t/home/user/project/test.cpp\n")

            mapping = ClangASTLoader.build_path_mapping(str(fmap), {"/home/user/project/test.cpp"})

            assert "/home/user/project/test.cpp" not in mapping

    def test_no_match_produces_empty_mapping(self) -> None:
        """AST path that shares no suffix with any FileMapping entry produces no entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fmap = Path(tmpdir) / "FileMapping.txt"
            fmap.write_text("1\t/home/user/project/other.cpp\n")

            mapping = ClangASTLoader.build_path_mapping(str(fmap), {"test.cpp"})

            assert mapping == {}

    def test_suffix_guard_prevents_false_positive(self) -> None:
        """'other_test.cpp' must not match against a FileMapping entry ending '/test.cpp'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fmap = Path(tmpdir) / "FileMapping.txt"
            fmap.write_text("1\t/proj/test.cpp\n")

            mapping = ClangASTLoader.build_path_mapping(str(fmap), {"other_test.cpp"})

            assert mapping == {}

    def test_clang_special_entries_skipped(self) -> None:
        """Clang internal paths like '<scratch space>' are not mapped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fmap = Path(tmpdir) / "FileMapping.txt"
            fmap.write_text("1\t/proj/test.cpp\n")

            mapping = ClangASTLoader.build_path_mapping(str(fmap), {"<scratch space>"})

            assert mapping == {}

    def test_missing_file_mapping_returns_empty(self) -> None:
        """Missing FileMapping.txt returns an empty mapping (no crash)."""
        mapping = ClangASTLoader.build_path_mapping("/nonexistent/FileMapping.txt", {"test.cpp"})
        assert mapping == {}

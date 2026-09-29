# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
from pathlib import Path
from typing import Any, Optional


class ClangASTLoader:
    """Loads and parses Clang AST JSON dump"""

    @staticmethod
    def load_ast(ast_dump_path: str) -> dict[str, Any]:
        """Load JSON-formatted Clang AST from file.

        Handles files that contain multiple concatenated top-level JSON objects
        (one per translation unit), which Clang produces when multiple source
        files are compiled together.  When more than one object is found they
        are wrapped in a single synthetic ``TranslationUnitDecl`` root whose
        ``inner`` list contains all per-file roots.

        Args:
            ast_dump_path: Path to the ast_dump.json file

        Returns:
            Dictionary containing the AST root node

        Raises:
            FileNotFoundError: If the AST dump file does not exist
            json.JSONDecodeError: If the JSON is malformed
        """
        path = Path(ast_dump_path)

        if not path.exists():
            raise FileNotFoundError(f"AST dump file not found: {ast_dump_path}")

        if not path.is_file():
            raise ValueError(f"AST dump path is not a file: {ast_dump_path}")

        try:
            content = path.read_text(encoding="utf-8")
        except OSError as e:
            raise OSError(f"Failed to read {ast_dump_path}: {e}") from e

        roots = ClangASTLoader._parse_all_objects(content, ast_dump_path)

        if len(roots) == 1:
            return roots[0]

        # Multiple translation units: merge under a synthetic root so that the
        # rest of the pipeline sees a single tree entry point.
        return {"kind": "TranslationUnitDecl", "inner": roots}

    @staticmethod
    def _parse_all_objects(content: str, source_path: str) -> list[dict[str, Any]]:
        """Parse one or more concatenated JSON objects from *content*.

        Args:
            content: Raw file text
            source_path: Original file path (used only in error messages)

        Returns:
            List of parsed top-level objects (at least one)

        Raises:
            json.JSONDecodeError: If any object cannot be parsed
        """
        decoder = json.JSONDecoder()
        objects: list[dict[str, Any]] = []
        pos = 0
        text = content.lstrip()

        while pos < len(text):
            try:
                obj, end_pos = decoder.raw_decode(text, pos)
            except json.JSONDecodeError as e:
                raise json.JSONDecodeError(
                    f"Failed to parse AST JSON from {source_path} at offset {pos}: {e.msg}",
                    e.doc,
                    e.pos,
                ) from e
            objects.append(dict(obj))  # type: ignore[arg-type]
            pos = end_pos
            # skip inter-object whitespace
            while pos < len(text) and text[pos] in " \t\n\r":
                pos += 1

        if not objects:
            raise json.JSONDecodeError(f"No JSON objects found in {source_path}", content, 0)

        return objects

    @staticmethod
    def load_ast_from_project(project_path: str) -> Optional[dict[str, Any]]:
        """Load AST dump from standard DiscoPoP project location

        Args:
            project_path: Root path of the DiscoPoP project

        Returns:
            Dictionary containing the AST root node, or None if file doesn't exist
        """
        ast_dump_path = Path(project_path) / "profiler" / "ast_dump.json"

        if not ast_dump_path.exists():
            return None

        return ClangASTLoader.load_ast(str(ast_dump_path))

    @staticmethod
    def build_path_mapping(file_mapping_path: str, ast_file_paths: set[str]) -> dict[str, str]:
        """Build a mapping from AST file paths to the canonical absolute paths in FileMapping.txt.

        Clang sometimes records source file paths as bare filenames (e.g. ``test.cpp``)
        or as paths relative to the compilation directory (e.g. ``./kernel/kernel.c``,
        ``./kernel/./../main.h``) while ``FileMapping.txt`` always stores absolute paths.
        This method resolves the discrepancy by suffix-matching each AST path -- after
        collapsing its ``.`` and ``..`` segments -- against the FileMapping entries: a
        FileMapping path ``/a/b/test.cpp`` is considered a match for the AST path
        ``test.cpp`` because the former ends with ``/test.cpp``.

        Only AST paths that actually differ from their FileMapping counterpart are
        included in the returned dict; callers can therefore use it as a plain
        substitution table.

        Args:
            file_mapping_path: Path to ``FileMapping.txt``
            ast_file_paths: Set of raw ``file`` strings collected from the AST graph

        Returns:
            Dict mapping each non-canonical AST path to its canonical absolute path.
            Empty when ``FileMapping.txt`` is absent or no substitution is needed.
        """
        fm_path = Path(file_mapping_path)
        if not fm_path.exists():
            return {}

        filemapping_entries: list[str] = []
        with open(fm_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    filemapping_entries.append(parts[1])

        filemapping_set = set(filemapping_entries)
        mapping: dict[str, str] = {}

        for ast_path in ast_file_paths:
            # Skip empty strings, Clang internal markers, and already-canonical paths
            if not ast_path or ast_path.startswith("<") or ast_path in filemapping_set:
                continue

            # Collapse "." and ".." segments so that a path Clang recorded relative to the
            # compilation directory ("./kernel/./../main.h") still suffix-matches the
            # absolute FileMapping entry ("/a/b/main.h").
            normalized = os.path.normpath(ast_path)
            if normalized in filemapping_set:
                mapping[ast_path] = normalized
                continue

            # Find a FileMapping entry whose path ends with /<normalized>.
            # The separator guard prevents "other_test.cpp".endswith("/test.cpp") from matching.
            for fm_entry in filemapping_entries:
                if fm_entry.endswith("/" + normalized) or fm_entry.endswith("\\" + normalized):
                    mapping[ast_path] = fm_entry
                    break

        return mapping

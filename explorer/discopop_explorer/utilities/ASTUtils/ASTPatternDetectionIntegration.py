# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Integration utilities for AST analysis in pattern detection"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional, Tuple, Union

import networkx as nx

from discopop_explorer.utilities.ASTUtils.ASTLoader import ClangASTLoader
from discopop_explorer.utilities.ASTUtils.ASTGraph import ClangASTGraph
from discopop_explorer.utilities.ASTUtils.ASTQueries import (
    ASTQueries,
    ASTVariableAndTypeQueries,
)
from discopop_explorer.utilities.ASTUtils.ASTVisualization import ASTVisualization
from discopop_library.PathManagement.PathManagement import load_file_mapping


class ASTPatternDetectionHelper:
    """Helper class for AST analysis during pattern detection

    Provides convenient methods for pattern detectors to query AST information.
    """

    def __init__(self) -> None:
        """Initialize helper with no AST loaded"""
        self.ast_graph: Optional[nx.DiGraph[str]] = None
        self.file_mapping: Dict[int, Path] = {}
        # memoized results of get_variables_at_location, keyed by the resolved location. The
        # scope of a source location does not change while an AST is loaded, and pattern
        # detection asks about the same loop header once per copy of the loop in the task graph -
        # of which there are many - so this is the difference between one scope walk per loop and
        # one per copy.
        self._variables_at_location_cache: Dict[
            Tuple[str, int, Optional[int]], Tuple[Tuple[str, Optional[str]], ...]
        ] = {}
        # memoized results of get_variables_assigned_in_loop_at, keyed by the resolved location,
        # for the same reason: the answer is a property of the source, and pattern detection asks
        # about one loop header once per copy of that loop in the task graph.
        self._assigned_in_loop_cache: Dict[Tuple[str, int], FrozenSet[str]] = {}

    def load_ast_from_project(self, project_path: str) -> None:
        """Load and build AST graph from project.

        Also loads ``FileMapping.txt`` so that callers can pass integer file IDs
        (as used throughout the rest of the DiscoPoP pipeline) instead of raw
        filenames.  After building the graph, file paths stored in node ``loc``
        dicts are normalised against ``FileMapping.txt`` so lookups by file ID
        resolve correctly.

        Args:
            project_path: Root path of the DiscoPoP project (.discopop directory)
        """
        file_mapping_path = str(Path(project_path) / "FileMapping.txt")

        # Load FileMapping.txt so file-ID lookups work later
        try:
            self.file_mapping = load_file_mapping(file_mapping_path)
        except (ValueError, OSError):
            self.file_mapping = {}

        self._variables_at_location_cache.clear()
        self._assigned_in_loop_cache.clear()

        ast_dict = ClangASTLoader.load_ast_from_project(project_path)
        if ast_dict is None:
            print(
                f"[ASTUtils] ast_dump.json not found under {project_path}/profiler/",
                file=sys.stderr,
            )
            return
        try:
            self.ast_graph = ClangASTGraph().build_from_ast(ast_dict)
        except Exception:
            print("[ASTUtils] Failed to build AST graph:", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            self.ast_graph = None
            return

        # Normalise file paths to match FileMapping.txt entries
        ast_file_paths: set[str] = {
            attrs["loc"]["file"]
            for _, attrs in self.ast_graph.nodes(data=True)
            if isinstance(attrs.get("loc"), dict) and attrs["loc"].get("file")
        }
        path_mapping = ClangASTLoader.build_path_mapping(file_mapping_path, ast_file_paths)
        if path_mapping:
            ClangASTGraph.normalize_file_paths(self.ast_graph, path_mapping)

    def get_variables_at_location(
        self, file_id: Union[int, str], line: int, column: Optional[int] = None
    ) -> list[tuple[str, Optional[str]]]:
        """Get variables visible at a specific source location.

        Args:
            file_id: Integer file identifier as defined in ``FileMapping.txt``,
                or a filename string (e.g. ``"compute.cpp"``) used directly.
            line: Line number
            column: Column number, or ``None`` to consider all columns on *line*

        Returns:
            List of (var_name, var_type) tuples, or empty list when the file is
            unknown or the AST has not been loaded.
        """
        if not self.ast_graph:
            return []

        if isinstance(file_id, int):
            file_path = self.file_mapping.get(file_id)
            if file_path is None:
                return []
            file_path_str = str(file_path)
        else:
            file_path_str = file_id

        cache_key = (file_path_str, line, column)
        cached = self._variables_at_location_cache.get(cache_key)
        if cached is None:
            cached = tuple(
                ASTVariableAndTypeQueries.find_all_variables_in_scope(self.ast_graph, file_path_str, line, column)
            )
            self._variables_at_location_cache[cache_key] = cached
        # a copy, so that a caller mutating the returned list cannot corrupt the cache
        return list(cached)

    def get_variables_assigned_in_loop_at(self, file_id: Union[int, str], line: int) -> FrozenSet[str]:
        """Get the variables assigned directly inside the loop whose header is at a location.

        "Directly" means the variable's own storage is written (``p = &a[i]``), as opposed to
        memory reached through it (``p[i] = x``).  See
        :meth:`ASTVariableAndTypeQueries.find_variables_assigned_in_loop_at`.

        Args:
            file_id: Integer file identifier as defined in ``FileMapping.txt``,
                or a filename string used directly.
            line: Line the loop header starts on

        Returns:
            Frozen set of variable names, empty when the file is unknown, the AST has not been
            loaded, or no loop starts on *line*.
        """
        if not self.ast_graph:
            return frozenset()

        if isinstance(file_id, int):
            file_path = self.file_mapping.get(file_id)
            if file_path is None:
                return frozenset()
            file_path_str = str(file_path)
        else:
            file_path_str = file_id

        cache_key = (file_path_str, line)
        cached = self._assigned_in_loop_cache.get(cache_key)
        if cached is None:
            cached = frozenset(
                ASTVariableAndTypeQueries.find_variables_assigned_in_loop_at(self.ast_graph, file_path_str, line)
            )
            self._assigned_in_loop_cache[cache_key] = cached
        return cached

    def get_variable_declarations_in_scope(self, scope_name: str) -> list[tuple[str, Optional[str]]]:
        """Get variables declared in a scope by function/loop name

        Args:
            scope_name: Name of the function or loop

        Returns:
            List of (var_name, var_type) tuples
        """
        if not self.ast_graph:
            return []

        for node_id, attrs in self.ast_graph.nodes(data=True):
            if attrs.get("name") == scope_name:
                kind = attrs.get("kind")
                if kind in {"FunctionDecl", "ForStmt", "WhileStmt"}:
                    return ASTVariableAndTypeQueries.get_variables_in_scope(self.ast_graph, node_id)

        return []

    def get_ast_statistics(self) -> Optional[dict[str, Any]]:
        """Get statistics about the loaded AST

        Returns:
            Dictionary with graph statistics or None if no AST loaded
        """
        if not self.ast_graph:
            return None

        return ASTVisualization.get_statistics(self.ast_graph)

    def get_ast_visualization(self) -> Optional[str]:
        """Get GraphViz DOT format representation of AST

        Returns:
            DOT format string or None if no AST loaded
        """
        if not self.ast_graph:
            return None

        return ASTVisualization.get_graphviz_format(self.ast_graph)

    def print_ast_structure(self, max_depth: Optional[int] = None) -> None:
        """Print ASCII representation of AST structure

        Args:
            max_depth: Maximum depth to print (None = unlimited)
        """
        if not self.ast_graph:
            print("No AST loaded")
            return

        ASTVisualization.print_tree_structure(self.ast_graph, max_depth=max_depth)

    def get_ast_graph(self) -> Optional[nx.DiGraph[str]]:
        """Get the underlying AST graph for direct querying

        Returns:
            AST graph or None if not loaded
        """
        return self.ast_graph

    def is_ast_loaded(self) -> bool:
        """Check if AST is available

        Returns:
            True if AST is loaded, False otherwise
        """
        return self.ast_graph is not None

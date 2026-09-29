<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License.  See the LICENSE file in the package base
directory for details.
-->

# AST Utilities for DiscoPoP Pattern Detection

This module provides utilities for loading and querying Clang AST information during pattern detection in DiscoPoP.

## Overview

The AST (Abstract Syntax Tree) utilities enable pattern detectors to access source-level information such as variable declarations, types, and code structure. This is automatically loaded from the `ast_dump.json` file created during instrumentation.

## Components

### 1. AST Loading (`ASTLoader.py`)

Load Clang AST JSON dumps from files:

```python
from discopop_explorer.utilities.ASTUtils import ClangASTLoader

# Load from standard project location (returns None if file not found)
ast_dict = ClangASTLoader.load_ast_from_project("/path/to/project")

# Load from specific file (raises FileNotFoundError / json.JSONDecodeError on failure)
ast_dict = ClangASTLoader.load_ast("/path/to/ast_dump.json")
```

### 2. AST Graph Building (`ASTGraph.py`)

Convert AST JSON to networkx DiGraph for querying:

```python
from discopop_explorer.utilities.ASTUtils import ClangASTGraph

builder = ClangASTGraph()
graph = builder.build_from_ast(ast_dict)

# Graph nodes contain: kind, name, type, loc, range, inner
print(f"Graph has {len(graph.nodes)} nodes and {len(graph.edges)} edges")
```

Node attributes:
- `kind` — AST node kind string (e.g. `"FunctionDecl"`, `"VarDecl"`)
- `name` — identifier name, or `None`
- `type` — type string, or `None`
- `loc` — `{"file": str|None, "line": int|None, "column": int|None}`
- `range` — `{"begin_line", "begin_column", "end_line", "end_column"}` (all `int|None`)
- `inner` — raw child list from the original JSON

### 3. AST Queries (`ASTQueries.py`)

Query AST structure and extract information:

```python
from discopop_explorer.utilities.ASTUtils import ASTQueries, ASTVariableAndTypeQueries

# Find nodes by kind
all_of_kind = ASTQueries.find_nodes_by_kind(graph, "VarDecl")   # -> list[str]
functions    = ASTQueries.find_functions(graph)                  # -> list[str]
loops        = ASTQueries.find_loops(graph)                      # -> list[str]  (ForStmt / WhileStmt / DoStmt)
declarations = ASTQueries.find_declarations(graph)               # -> list[str]  (VarDecl only)

# Navigate tree
parent   = ASTQueries.get_parent(graph, node_id)                 # -> str | None
children = ASTQueries.get_children(graph, node_id)              # -> list[str]
scope    = ASTQueries.find_enclosing_scope(graph, node_id)       # -> str | None

# Look up by location
nodes_in_file = ASTQueries.find_nodes_in_file(graph, "main.cpp")
nodes_at_loc  = ASTQueries.find_nodes_at_location(graph, "main.cpp", line=42, column=15)

# Retrieve all attributes of a node
info = ASTQueries.get_node_info(graph, node_id)                  # -> dict[str, Any]

# Find variable declarations at a location
# Returns: [(name, type, node_kind), ...]
decls = ASTVariableAndTypeQueries.find_declarations_at_location(graph, "main.cpp", 42, 15)

# Find variable references (DeclRefExpr) at a location
# Returns: [(name, type, node_kind), ...]
refs = ASTVariableAndTypeQueries.find_references_at_location(graph, "main.cpp", 42, 15)

# Find all variables visible at a location (walks up to enclosing scope)
# Returns: [(name, type), ...]
variables = ASTVariableAndTypeQueries.find_all_variables_in_scope(
    graph, "main.cpp", line=42, column=15
)

# Find variables declared directly inside a scope node
variables = ASTVariableAndTypeQueries.get_variables_in_scope(graph, scope_node_id)
```

### 4. AST Visualization (`ASTVisualization.py`)

Visualize and analyze AST graphs:

```python
from discopop_explorer.utilities.ASTUtils import ASTVisualization

# Compute layout for visualization
# layout_type: "spring" | "circular" | "tree" | "kamada_kawai"
layout = ASTVisualization.get_layout(graph, "spring")

# Get node styling
labels = ASTVisualization.get_node_labels(graph)   # {node_id: label_str}
colors = ASTVisualization.get_node_colors(graph)   # list[str]  (hex colors per node)
sizes  = ASTVisualization.get_node_sizes(graph)    # list[float]

# Filter subgraphs
functions_only = ASTVisualization.filter_graph_by_kind(graph, ["FunctionDecl"])
file_subset    = ASTVisualization.filter_graph_by_file(graph, "main.cpp")
shallow        = ASTVisualization.filter_graph_by_depth(graph, root_node_id, max_depth=3)

# Generate GraphViz format for visualization
dot_format = ASTVisualization.get_graphviz_format(graph)

# Get statistics
stats = ASTVisualization.get_statistics(graph)
# Returns dict with keys:
#   num_nodes, num_edges, is_tree, num_connected_components,
#   node_kinds (dict[kind, count]), avg_degree

# Print tree structure
ASTVisualization.print_tree_structure(graph, max_depth=3)
# Optional parameters: root_node_id (default: all roots), indent, max_depth
```

## Integration with Pattern Detection

The `PatternDetectorX` class automatically loads the AST from the project and provides access via `ast_helper`:

```python
from discopop_explorer.pattern_detection import PatternDetectorX

# AST is loaded automatically during detect_patterns
detector = PatternDetectorX(pet_graph)

# Access AST operations through the helper
helper = detector.ast_helper

# Query variables at a location
variables = helper.get_variables_at_location("main.cpp", 42, 15)

# Query variables in a scope by name
variables = helper.get_variable_declarations_in_scope("compute")

# Get AST statistics
stats = helper.get_ast_statistics()

# Get visualization
dot = helper.get_ast_visualization()

# Print AST structure
helper.print_ast_structure(max_depth=3)

# Check if AST is loaded
if helper.is_ast_loaded():
    # Get direct access to networkx graph
    graph = helper.get_ast_graph()
```

## Usage Examples

### Example 1: Find Variable Types in a Loop

```python
def detect_pattern_variables(detector, loop_location):
    """Find all variables used in a loop"""
    variables = detector.ast_helper.get_variables_at_location(
        "compute.cpp",
        line=loop_location["line"],
        column=loop_location["column"]
    )

    for var_name, var_type in variables:
        print(f"  Variable: {var_name} ({var_type})")
```

### Example 2: Analyze Function Scope

```python
def analyze_function(detector, function_name):
    """Get all variables declared in a function"""
    variables = detector.ast_helper.get_variable_declarations_in_scope(function_name)

    type_counts = {}
    for var_name, var_type in variables:
        type_counts[var_type] = type_counts.get(var_type, 0) + 1

    return type_counts
```

### Example 3: Export AST Visualization

```python
def export_ast_diagram(detector, output_file):
    """Export AST as GraphViz diagram"""
    dot_format = detector.ast_helper.get_ast_visualization()

    if dot_format:
        with open(output_file, 'w') as f:
            f.write(dot_format)
        print(f"Saved AST diagram to {output_file}")
```

## Graceful Degradation

If the AST file is not available (e.g., instrumentation failed), all methods return empty results gracefully:

```python
variables = detector.ast_helper.get_variables_at_location("file.cpp", 1, 1)
# Returns: [] if no AST available

stats = detector.ast_helper.get_ast_statistics()
# Returns: None if no AST available
```

## Performance Considerations

- **Loading**: One-time cost when `detect_patterns` is called
- **Queries**: O(n) where n is number of nodes (typically < 10k for most projects)
- **Visualization**: O(n) for layout computation, O(n²) for some layout algorithms

## Testing

See `test_ASTLoader.py`, `test_ASTGraph.py`, `test_ASTQueries.py`, and `test_ASTVisualization.py` for comprehensive test coverage (52 unit tests).

Integration tests in `test_pattern_detection_ast_integration.py` cover the complete workflow (8 tests).

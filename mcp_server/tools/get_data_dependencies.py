# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import logging
from pathlib import Path
from typing import Any, Optional

from mcp.types import TextContent, Tool, ToolAnnotations

from mcp_server.tools.helpers import ToolContext

logger = logging.getLogger("discopop-mcp")

# A large region (a whole function, a file) can have thousands of dependencies;
# beyond this many the answer costs more tokens than it is worth to the caller.
MAX_DEPENDENCIES = 200

DEP_TYPES = ("RAW", "WAR", "WAW")
# Also the order of the buckets, both in the result and when cutting it.
DIRECTIONS = ("incoming", "outgoing", "intra_region")

TOOL = Tool(
    name="get_data_dependencies",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Return data dependencies (RAW, WAR, WAW) that cross or lie within a specified code region "
        "(file + line range). The results contain both statically and dynamically identified data dependencies. "
        "Dynamic dependencies are observed from profiling runs and correctly capture aliasing and other cases "
        "that pure static analysis cannot resolve — making the combined result reliable "
        "for general code analysis beyond parallelisation.\n\n"
        "Results are grouped into three directions:\n"
        "  - incoming: dependency whose source is outside the region and sink is inside\n"
        "  - outgoing: dependency whose source is inside the region and sink is outside\n"
        "  - intra_region: both source and sink are within the region\n\n"
        "Each entry has dep_type, var_name, source and sink. An end in the queried file_path is given "
        "as its line number only; an end in another file as {file, line}.\n\n"
        "Use dep_types and directions to restrict the result. Optionally filter by var_name to focus "
        "on a specific variable. Note: when var_name is set, incoming dependencies are automatically "
        "excluded because the same memory location may be referenced under a different name in the "
        "outer scope (aliasing).\n\n"
        f"At most {MAX_DEPENDENCIES} dependencies are returned; num_dependencies is always the full count, "
        "and truncated=true marks a cut result. Narrow the line range or use the filters to see the rest.\n\n"
        "Requires gather_data to have been run first. Cheap to call: results are cached in memory "
        "after the first load, so successive calls for different regions or filters incur no additional I/O."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root directory.",
            },
            "file_path": {
                "type": "string",
                "description": "Absolute path to the source file containing the code region.",
            },
            "start_line": {
                "type": "integer",
                "description": "First line of the code region (inclusive).",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line of the code region (inclusive).",
            },
            "dep_types": {
                "type": "array",
                "items": {"type": "string", "enum": list(DEP_TYPES)},
                "description": "Dependency types to return: RAW (flow), WAR (anti), WAW (output). Default: all.",
            },
            "directions": {
                "type": "array",
                "items": {"type": "string", "enum": list(DIRECTIONS)},
                "description": "Directions to return. Default: all.",
            },
            "var_name": {
                "type": "string",
                "description": (
                    "If set, only return dependencies for this variable name. "
                    "Incoming dependencies are automatically excluded when this filter is active "
                    "because aliasing may cause the same memory to appear under a different name "
                    "outside the region."
                ),
            },
        },
        "required": ["project_path", "file_path", "start_line", "end_line"],
        "additionalProperties": False,
    },
)


def _parse_line_id(line_id: str) -> tuple[int, int]:
    parts = line_id.split(":")
    return int(parts[0]), int(parts[1])


def _location(file_id: int, line: int, target_file_id: int, file_mapping: dict[int, Path]) -> Any:
    """One end of a dependency: the bare line in the queried file, {file, line} elsewhere."""
    if file_id == target_file_id:
        return line
    return {"file": str(file_mapping[file_id]) if file_id in file_mapping else None, "line": line}


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path: str = arguments.get("project_path", "")
        file_path: str = arguments.get("file_path", "")
        start_line: int = int(arguments.get("start_line", 0))
        end_line: int = int(arguments.get("end_line", 0))
        # An omitted or empty list means "no restriction".
        dep_types: set[str] = set(arguments.get("dep_types") or DEP_TYPES)
        directions: set[str] = set(arguments.get("directions") or DIRECTIONS)
        var_name_filter: Optional[str] = arguments.get("var_name", None)

        # Enforce var_name aliasing constraint
        incoming_excluded_by_var_name = False
        if var_name_filter is not None and "incoming" in directions:
            directions.discard("incoming")
            incoming_excluded_by_var_name = True

        # Load DetectionResult (cached)
        detection_result = ctx.get_detection_result(project_path)
        if detection_result is None:
            return ctx.error("No detection result found. Run gather_data first.", project_path, "get_data_dependencies")

        # Load FileMapping (cached)
        file_mapping = ctx.get_file_mapping(project_path)
        if file_mapping is None:
            return ctx.error("FileMapping.txt not found. Run gather_data first.", project_path, "get_data_dependencies")

        # Resolve target file_id
        resolved_request = Path(file_path).resolve()
        target_file_id: Optional[int] = None
        for fid, fpath in file_mapping.items():
            if fpath.resolve() == resolved_request:
                target_file_id = fid
                break
        if target_file_id is None:
            return ctx.error(
                f"file_path not found in FileMapping.txt: {file_path}", project_path, "get_data_dependencies"
            )

        # Import DiscoPoP enums (available via installed packages)
        from discopop_explorer.enums.DepType import DepType
        from discopop_explorer.enums.EdgeType import EdgeType

        dtype_filter = {DepType[name] for name in dep_types if name in DEP_TYPES}

        # (sort key, direction, entry); sorted before cutting so that a truncated result is reproducible
        found: list[tuple[tuple[Any, ...], str, dict[str, Any]]] = []
        seen: set[tuple[Any, Any, Any, Any]] = set()

        pet = detection_result.pet
        for _src_node, _tgt_node, dep in pet.g.edges(data="data"):
            if dep.etype != EdgeType.DATA:
                continue
            if dep.dtype is None or dep.source_line is None or dep.sink_line is None:
                continue
            if dep.dtype == DepType.INIT:
                continue
            if dep.dtype not in dtype_filter:
                continue

            src_file_id, src_line = _parse_line_id(dep.source_line)
            snk_file_id, snk_line = _parse_line_id(dep.sink_line)

            src_in = src_file_id == target_file_id and start_line <= src_line <= end_line
            snk_in = snk_file_id == target_file_id and start_line <= snk_line <= end_line

            if src_in and snk_in:
                category = "intra_region"
            elif not src_in and snk_in:
                category = "incoming"
            elif src_in and not snk_in:
                category = "outgoing"
            else:
                continue  # neither endpoint in region
            if category not in directions:
                continue

            if var_name_filter is not None and dep.var_name != var_name_filter:
                continue

            dedup_key = (dep.source_line, dep.sink_line, dep.var_name, dep.dtype)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            entry: dict[str, Any] = {
                "dep_type": dep.dtype.name,
                "var_name": dep.var_name,
                "source": _location(src_file_id, src_line, target_file_id, file_mapping),
                "sink": _location(snk_file_id, snk_line, target_file_id, file_mapping),
            }
            sort_key = (
                DIRECTIONS.index(category),
                snk_file_id != target_file_id,
                snk_file_id,
                snk_line,
                src_file_id != target_file_id,
                src_file_id,
                src_line,
                dep.var_name or "",
                dep.dtype.name,
            )
            found.append((sort_key, category, entry))

        total = len(found)
        found.sort(key=lambda item: item[0])
        buckets: dict[str, list[dict[str, Any]]] = {direction: [] for direction in DIRECTIONS}
        for _key, category, entry in found[:MAX_DEPENDENCIES]:
            buckets[category].append(entry)

        result: dict[str, Any] = {
            "status": "success",
            "project_path": project_path,
            "file_path": file_path,
            "start_line": start_line,
            "end_line": end_line,
            "num_dependencies": total,
            "dependencies": buckets,
        }
        if incoming_excluded_by_var_name:
            result["incoming_excluded_due_to_var_name_filter"] = True
        if total > MAX_DEPENDENCIES:
            per_direction = {direction: 0 for direction in DIRECTIONS}
            for _key, category, _entry in found:
                per_direction[category] += 1
            result["truncated"] = True
            result["num_dependencies_by_direction"] = per_direction
            result["next_step"] = (
                f"Only the first {MAX_DEPENDENCIES} of {total} dependencies are listed, ordered by direction "
                "(incoming, outgoing, intra_region), then sink and source line. To see the rest, narrow the "
                "query: a smaller start_line/end_line range, var_name, dep_types or directions."
            )
        if total == 0:
            # The dynamic part only knows code that the profiling run executed, so an empty
            # result must not be read as proof that the region is free of dependencies.
            result["next_step"] = (
                "No dependency is recorded for this region. Either it has none, or the profiling "
                "run never executed these lines; in that case run gather_data with a configuration "
                "whose input reaches them before concluding that the region is independent."
            )

        ctx.log_response("get_data_dependencies", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error querying data dependencies: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

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

TOOL = Tool(
    name="get_data_dependencies",
    annotations=ToolAnnotations(readOnlyHint=True),
    description=(
        "Return data dependencies (RAW, WAR, WAW) that cross or lie within a specified code region "
        "(file + line range). The results contain both statically and dynamically identified data dependencies. "
        "Dynamic dependencies are observed from profiling runs and correctly capture aliasing and other cases "
        "that pure static analysis cannot resolve — making the combined result reliable "
        "for general code analysis beyond parallelisation.\n\n"
        "Results are grouped into three categories:\n"
        "  - incoming: dependency whose source is outside the region and sink is inside\n"
        "  - outgoing: dependency whose source is inside the region and sink is outside\n"
        "  - intra_region: both source and sink are within the region\n\n"
        "Use the include_* flags to restrict which dependency types (RAW/WAR/WAW) and which "
        "direction categories (incoming/outgoing/intra_region) are returned.\n\n"
        "Optionally filter by var_name to focus on a specific variable. Note: when var_name is "
        "set, incoming dependencies are automatically excluded because the same memory location "
        "may be referenced under a different name in the outer scope (aliasing).\n\n"
        "Requires gather_data to have been run first.\n\n"
        "Performance: this tool is cheap to call. The underlying DetectionResult and FileMapping "
        "are cached in memory after the first load, so successive calls for different regions or "
        "filter combinations within the same project incur no additional I/O. "
        "Use the include_* flags and var_name to request only what is needed, or narrow the "
        "start_line/end_line range to a smaller code region — both reduce the number of returned "
        "dependencies and therefore conserve tokens."
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
            "include_raw": {
                "type": "boolean",
                "description": "Include Read-After-Write (flow) dependencies. Default: true.",
            },
            "include_war": {
                "type": "boolean",
                "description": "Include Write-After-Read (anti) dependencies. Default: true.",
            },
            "include_waw": {
                "type": "boolean",
                "description": "Include Write-After-Write (output) dependencies. Default: true.",
            },
            "include_incoming": {
                "type": "boolean",
                "description": "Include dependencies flowing into the region. Default: true.",
            },
            "include_outgoing": {
                "type": "boolean",
                "description": "Include dependencies flowing out of the region. Default: true.",
            },
            "include_intra_region": {
                "type": "boolean",
                "description": "Include dependencies fully within the region. Default: true.",
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


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path: str = arguments.get("project_path", "")
        file_path: str = arguments.get("file_path", "")
        start_line: int = int(arguments.get("start_line", 0))
        end_line: int = int(arguments.get("end_line", 0))
        include_raw: bool = bool(arguments.get("include_raw", True))
        include_war: bool = bool(arguments.get("include_war", True))
        include_waw: bool = bool(arguments.get("include_waw", True))
        include_incoming: bool = bool(arguments.get("include_incoming", True))
        include_outgoing: bool = bool(arguments.get("include_outgoing", True))
        include_intra_region: bool = bool(arguments.get("include_intra_region", True))
        var_name_filter: Optional[str] = arguments.get("var_name", None)

        # Enforce var_name aliasing constraint
        incoming_excluded_by_var_name = False
        if var_name_filter is not None and include_incoming:
            include_incoming = False
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

        dtype_filter = set()
        if include_raw:
            dtype_filter.add(DepType.RAW)
        if include_war:
            dtype_filter.add(DepType.WAR)
        if include_waw:
            dtype_filter.add(DepType.WAW)

        buckets: dict[str, list[dict[str, Any]]] = {"incoming": [], "outgoing": [], "intra_region": []}
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
                if not include_intra_region:
                    continue
            elif not src_in and snk_in:
                category = "incoming"
                if not include_incoming:
                    continue
            elif src_in and not snk_in:
                category = "outgoing"
                if not include_outgoing:
                    continue
            else:
                continue  # neither endpoint in region

            if var_name_filter is not None and dep.var_name != var_name_filter:
                continue

            dedup_key = (dep.source_line, dep.sink_line, dep.var_name, dep.dtype)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            src_file_str = str(file_mapping[src_file_id]) if src_file_id in file_mapping else None
            snk_file_str = str(file_mapping[snk_file_id]) if snk_file_id in file_mapping else None

            entry: dict[str, Any] = {
                "dep_type": dep.dtype.name,
                "var_name": dep.var_name,
                "source": {"file": src_file_str, "line": src_line},
                "sink": {"file": snk_file_str, "line": snk_line},
            }
            buckets[category].append(entry)

        total = sum(len(v) for v in buckets.values())
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

        ctx.log_response("get_data_dependencies", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error querying data dependencies: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any, Optional

from mcp.types import TextContent, Tool, ToolAnnotations

from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.detailed_hotspot_loader import (
    HotspotRegionInfo,
    hotspots_are_degenerate,
    hotspots_json_path,
    load_detailed_hotspots,
)
from mcp_server.tools.helpers import ToolContext

logger = logging.getLogger("discopop-mcp")

DEFAULT_LIMIT = 20
HOTNESS_NAMES = ["YES", "MAYBE", "NO"]
# hottest class first, as the hotspot-guided search of run_auto_tuning ranks them
_HOTNESS_TIER = {HotspotType.YES: 0, HotspotType.MAYBE: 1, HotspotType.NO: 2}

TOOL = Tool(
    name="get_hotspots",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "List the code regions (loops and functions) where the program spends its time, as "
        "measured by the hotspot detection of gather_data(hotspot_config_names=[...]). Use it to "
        "see which parts of a program matter for its runtime, e.g. before deciding where to look "
        "for or at parallelization suggestions."
        "\n\n"
        "Each region has a hotness: YES — above-average runtime that also grows with the input "
        "more than average; MAYBE — only one of the two; NO — neither. Regions come hottest "
        "class first, then by their longest measured runtime, with one inclusive runtime per "
        "hotspot profiling run. With a single profiling run (or identical inputs), growth with "
        "the input cannot be judged and the result says so."
        "\n\n"
        "Cheap to call."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root directory.",
            },
            "hotness": {
                "type": "array",
                "items": {"type": "string", "enum": HOTNESS_NAMES},
                "minItems": 1,
                "description": "Only return regions of these classes. Default: ['YES', 'MAYBE'].",
            },
            "region_type": {
                "type": "string",
                "enum": ["loop", "function"],
                "description": "Only return loops or only functions. Default: both.",
            },
            "file_path": {
                "type": "string",
                "description": "Only return regions in this source file (absolute path).",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of regions to return. Default: {DEFAULT_LIMIT}.",
            },
        },
        "required": ["project_path"],
        "additionalProperties": False,
    },
)


def demangle(names: list[str]) -> dict[str, str]:
    """C++ symbol names in readable form, as far as a c++filt is available; one call for all."""
    mangled = sorted({name for name in names if name.startswith("_Z")})
    tool = shutil.which("llvm-cxxfilt") or shutil.which("c++filt")
    if not mangled or tool is None:
        return {}
    try:
        proc = subprocess.run([tool], input="\n".join(mangled), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {}
    readable = proc.stdout.splitlines()
    if proc.returncode != 0 or len(readable) != len(mangled):
        return {}
    return dict(zip(mangled, readable))


def rank_key(region: HotspotRegionInfo) -> tuple[int, float, int, int]:
    return (_HOTNESS_TIER[region.hotness], -region.max_val, region.file_id, region.start_line)


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path: str = arguments.get("project_path", "")
        hotness_filter = {HotspotType[name] for name in arguments.get("hotness", ["YES", "MAYBE"])}
        region_type: Optional[str] = arguments.get("region_type")
        file_path: Optional[str] = arguments.get("file_path")
        limit = int(arguments.get("limit", DEFAULT_LIMIT))

        dot_dp = str(Path(project_path) / ".discopop")
        if not Path(hotspots_json_path(dot_dp)).exists():
            result: dict[str, Any] = {
                "status": "success",
                "project_path": project_path,
                "num_regions": 0,
                "regions": [],
                "next_step": (
                    "No hotspot detection results exist. Run gather_data with hotspot_config_names "
                    "set, ideally to two configurations with different input sizes."
                ),
            }
            ctx.log_response("get_hotspots", result)
            return [TextContent(type="text", text=json.dumps(result))]

        file_mapping = ctx.get_file_mapping(project_path) or {}
        file_id_filter: Optional[int] = None
        if file_path is not None:
            resolved_request = Path(file_path).resolve()
            file_id_filter = next(
                (fid for fid, path in file_mapping.items() if path.resolve() == resolved_request), None
            )
            if file_id_filter is None:
                return ctx.error(
                    f"file_path is not part of the analysed program: {file_path}", project_path, "get_hotspots"
                )

        all_regions = load_detailed_hotspots(dot_dp)
        regions = sorted(
            (
                r
                for r in all_regions
                if r.hotness in hotness_filter
                and (region_type is None or r.node_type.name.lower() == region_type)
                and (file_id_filter is None or r.file_id == file_id_filter)
            ),
            key=rank_key,
        )
        shown = regions[: max(limit, 0)]
        readable = demangle([r.name for r in shown if r.node_type.name == "FUNCTION"])

        entries = []
        for region in shown:
            path = file_mapping.get(region.file_id)
            entry: dict[str, Any] = {
                "file": str(path) if path is not None else None,
                "line": region.start_line,
                "type": region.node_type.name.lower(),
            }
            if region.node_type.name == "FUNCTION":
                entry["name"] = readable.get(region.name, region.name)
            entry["hotness"] = region.hotness.name
            entry["max_runtime"] = region.max_val
            entry["runtimes"] = region.runtimes
            entries.append(entry)

        counts = {name: 0 for name in HOTNESS_NAMES}
        for region in all_regions:
            counts[region.hotness.name] += 1
        result = {
            "status": "success",
            "project_path": project_path,
            "num_regions_by_hotness": counts,
            "num_regions": len(regions),
            "regions": entries,
        }
        if len(regions) > len(shown):
            result["truncated"] = True
        if not all_regions:
            result["warning"] = (
                "The hotspot results hold no region: the profiled runs measured no function or loop. "
                "Check that the configurations in hotspot_config_names run the program."
            )
        elif hotspots_are_degenerate(all_regions):
            result["warning"] = (
                "All regions show the same runtime in every profiling run, so the classification only "
                "reflects the average runtime, not how it grows with the input. Run gather_data with "
                "hotspot_config_names set to two configurations with different input sizes for a "
                "meaningful one."
            )
        ctx.log_response("get_hotspots", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error reading hotspot results: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

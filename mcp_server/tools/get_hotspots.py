# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mcp.types import TextContent, Tool, ToolAnnotations

from discopop_library.HostpotLoader.detailed_hotspot_loader import (
    HotspotRegionInfo,
    hotspots_are_degenerate,
    hotspots_json_path,
    load_detailed_hotspots,
)
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from mcp_server.tools.helpers import ToolContext
from mcp_server.tools.hotspot_text import display_path, hotspot_prefix, runtime_text, total_runtime

logger = logging.getLogger("discopop-mcp")

DEFAULT_LIMIT = 10

TOOL = Tool(
    name="get_hotspots",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "List the loops and functions where the program spends its time, as measured by the hotspot "
        "detection of gather_data, longest running first. Use it to see which parts of a program matter "
        "for its runtime. A Hotspot has an above-average runtime that also grows with the input more than "
        "average; a Potential Hotspot only one of the two. Each line gives the longest measured runtime "
        "(inclusive of what the region calls) and its share of the program's. "
        "\n\n"
        "By default the first hotspots are shown and the last line says how many are not; raise limit "
        "for more. main is left out, as it always takes all of the runtime."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root directory.",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of hotspots to list. Default: {DEFAULT_LIMIT}.",
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


def _short_name(name: str) -> str:
    """A function name without its parameter list: 'ns::f(int, double*)' -> 'ns::f'."""
    if not name.endswith(")"):
        return name
    depth = 0
    for index in range(len(name) - 1, -1, -1):
        depth += {")": 1, "(": -1}.get(name[index], 0)
        if depth == 0:
            # operator() has the parameter list of its own right behind its name
            return name[:index] if not name[:index].endswith("operator") else name
    return name


def _describe(
    region: HotspotRegionInfo, total: float, project_path: str, file_mapping: dict[int, Path], name: str
) -> str:
    kind = region.node_type.name.capitalize()
    path = display_path(project_path, file_mapping.get(region.file_id))
    label = f" {_short_name(name)}" if region.node_type == HotspotNodeType.FUNCTION else ""
    return f"{hotspot_prefix(region)}{kind} {path}:{region.start_line}{label} ({runtime_text(region, total)})"


def _counted(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _count(regions: list[HotspotRegionInfo], hotness: HotspotType) -> int:
    return sum(1 for region in regions if region.hotness == hotness)


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path: str = arguments.get("project_path", "")
        limit = max(int(arguments.get("limit", DEFAULT_LIMIT)), 0)

        dot_dp = str(Path(project_path) / ".discopop")
        if not Path(hotspots_json_path(dot_dp)).exists():
            return ctx.error("No hotspot results exist. Run gather_data first.", project_path, TOOL.name)

        file_mapping = ctx.get_file_mapping(project_path) or {}
        all_regions = load_detailed_hotspots(dot_dp)
        total = total_runtime(all_regions)
        # the longest running first; main takes everything and says nothing
        hotspots = sorted(
            (
                region
                for region in all_regions
                if region.hotness in (HotspotType.YES, HotspotType.MAYBE)
                and not (region.node_type == HotspotNodeType.FUNCTION and region.name == "main")
            ),
            key=lambda region: (-region.max_val, region.file_id, region.start_line),
        )
        shown, hidden = hotspots[:limit], hotspots[limit:]
        readable = demangle([r.name for r in shown if r.node_type == HotspotNodeType.FUNCTION])

        lines = [
            (
                f"{_counted(_count(hotspots, HotspotType.YES), 'hotspot')} and "
                f"{_counted(_count(hotspots, HotspotType.MAYBE), 'potential hotspot')}, longest running first:"
                if hotspots
                else "No hotspots found."
            )
        ]
        lines += [_describe(r, total, project_path, file_mapping, readable.get(r.name, r.name)) for r in shown]
        if hidden:
            parts = [
                _counted(count, noun)
                for count, noun in (
                    (_count(hidden, HotspotType.YES), "hotspot"),
                    (_count(hidden, HotspotType.MAYBE), "potential hotspot"),
                )
                if count
            ]
            lines.append(f"{' and '.join(parts)} not shown (limit={limit}); pass a larger limit to see them.")
        if not all_regions:
            lines.append(
                "The hotspot results hold no region: the profiled runs measured no function or loop. Check that "
                "the configurations in hotspot_config_names run the program."
            )
        elif hotspots_are_degenerate(all_regions):
            lines.append(
                "Only one input size was profiled, so how the runtime grows with the input cannot be judged and "
                "the classification reflects the runtime alone. Pass two configurations with different input sizes "
                "as hotspot_config_names to gather_data for a meaningful one."
            )
        ctx.log_action(project_path, TOOL.name, f"Listed {len(shown)} of {len(hotspots)} hotspots")
        return [TextContent(type="text", text="\n".join(lines))]

    except Exception as e:
        error_msg = f"Error reading hotspot results: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return ctx.error(error_msg, arguments.get("project_path", ""), TOOL.name)

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

from discopop_library.HostpotLoader.detailed_hotspot_loader import HotspotRegionInfo, load_detailed_hotspots
from mcp_server.tools.helpers import ToolContext
from mcp_server.tools.hotspot_text import (
    display_path,
    hotspot_prefix,
    resolve_source_path,
    runtime_text,
    total_runtime,
)

logger = logging.getLogger("discopop-mcp")

DEFAULT_LIMIT = 10
# patterns.json lists suggestions per pattern type under these keys
_PATTERN_TYPE_KEYS = {"do_all": "doall", "reduction": "reduction"}

TOOL = Tool(
    name="get_parallelization_suggestions",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "List the parallelization suggestions found by gather_data, hottest first. Each line gives "
        "the code region (its kind, file and lines), how much of the runtime it takes (a Hotspot or "
        "Potential Hotspot, with its measured runtime and share of the program's), the pattern type "
        "(e.g. doall or reduction) and the change to make, e.g. the OpenMP pragma with its "
        "data-sharing clauses to put directly above the region. "
        "Suggestions on the same code are marked as nested in or an alternative to each other. "
        "\n\n"
        "By default the first suggestions are shown and the line at the end says how many are not; "
        "raise limit for more. "
        "\n\n"
        "Apply a suggestion by editing the source yourself. "
        "explain_parallelization tells why code without a suggestion was not parallelized."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root.",
            },
            "file_path": {
                "type": "string",
                "description": "Only list suggestions for this source file (absolute, or relative to the project).",
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of suggestions to list. Default: {DEFAULT_LIMIT}.",
            },
        },
        "required": ["project_path"],
        "additionalProperties": False,
    },
)


def _summarize_patch(patch_content: str) -> tuple[Optional[int], Optional[str]]:
    """The line a patch targets and the pragma it inserts.

    A suggestion is one added pragma above one code region, so those two facts are what a
    summary needs; everything else in the diff is context that only matters when the
    patch is being read rather than chosen between.
    """
    line: Optional[int] = None
    pragma: Optional[str] = None
    for raw_line in patch_content.splitlines():
        if raw_line.startswith("@@") and line is None:
            # "@@ -17,6 +17,7 @@" — the first number of the original-file range
            try:
                line = int(raw_line.split("-", 1)[1].split(",", 1)[0].split()[0])
            except (IndexError, ValueError):
                line = None
        elif raw_line.startswith("+") and not raw_line.startswith("+++") and pragma is None:
            added = raw_line[1:].strip()
            if added:
                pragma = added
    return line, pragma


def _line_number(line_id: Any) -> Optional[int]:
    try:
        return int(str(line_id).split(":")[1])
    except (IndexError, ValueError):
        return None


def _suggestion_facts(dot_discopop: Path) -> dict[str, dict[str, Any]]:
    """Per suggestion id: pattern type, collapse depth, file id and start line, from patterns.json."""
    facts: dict[str, dict[str, Any]] = {}
    try:
        with open(dot_discopop / "explorer" / "patterns.json") as f:
            patterns = json.load(f).get("patterns", {})
    except (OSError, ValueError):
        return facts
    for key, pattern_type in _PATTERN_TYPE_KEYS.items():
        for pattern in patterns.get(key) or []:
            start = str(pattern.get("start_line", ""))
            entry: dict[str, Any] = {"type": pattern_type, "line": _line_number(start)}
            try:
                entry["file_id"] = int(start.split(":")[0])
            except ValueError:
                pass
            if isinstance(pattern.get("collapse_level"), int) and pattern["collapse_level"] > 1:
                entry["collapse"] = pattern["collapse_level"]
            facts[str(pattern.get("pattern_id"))] = entry
    return facts


def _regions(dot_discopop: Path) -> dict[str, tuple[int, int, int, str]]:
    """Per suggestion id: (file id, first line, last line, kind) of the code it covers, from the
    explorer's pattern decisions; empty for results of versions which did not record them."""
    path = dot_discopop / "explorer" / "pattern_decisions.json"
    if not path.exists():
        return {}
    try:
        from discopop_explorer.classes.patterns.PatternDecisions import ACCEPTED, PatternDecisionLog

        log = PatternDecisionLog.load(str(path))
    except Exception as e:
        logger.warning(f"Failed to load {path}: {e}")
        return {}
    regions: dict[str, tuple[int, int, int, str]] = {}
    for decision in log.decisions:
        if decision.outcome != ACCEPTED:
            continue
        region = decision.region
        for pattern in decision.patterns:
            regions[str(pattern["pattern_id"])] = (region.file_id, region.start_line, region.end_line, region.kind)
    return regions


def _hotspot_regions(dot_discopop: Path) -> tuple[dict[tuple[int, int, str], HotspotRegionInfo], float]:
    """The hotspot region of every loop and function by (file id, first line, kind), and the program's runtime."""
    try:
        regions = load_detailed_hotspots(str(dot_discopop))
    except Exception as e:
        logger.warning(f"Failed to load the hotspot detection results: {e}")
        return {}, 0.0
    by_place = {(r.file_id, r.start_line, r.node_type.name.lower()): r for r in regions}
    return by_place, total_runtime(regions)


def _relations(pid: str, regions: dict[str, tuple[int, int, int, str]]) -> dict[str, list[str]]:
    """The suggestions on code enclosing this suggestion's, and those on the same code."""
    own = regions.get(pid)
    if own is None:
        return {}
    nested_in: list[str] = []
    same_region: list[str] = []
    for other, region in regions.items():
        if other == pid or region[0] != own[0]:
            continue
        if region[1:3] == own[1:3]:
            same_region.append(other)
        elif region[1] <= own[1] and own[2] <= region[2]:
            nested_in.append(other)
    relations: dict[str, list[str]] = {}
    if nested_in:
        relations["nested_in"] = sorted(nested_in, key=int)
    if same_region:
        relations["same_region"] = sorted(same_region, key=int)
    return relations


def _describe(suggestion: dict[str, Any], hotspot: Optional[HotspotRegionInfo], total: float) -> str:
    """One line per suggestion: the code region, its weight, the pattern and the change."""
    lines = f"{suggestion['line']}-{suggestion['end_line']}" if "end_line" in suggestion else f"{suggestion['line']}"
    place = f"{suggestion['kind']} {suggestion['file']}:{lines}"
    weight = f" ({runtime_text(hotspot, total)})" if hotspot is not None else ""
    text = f"Suggestion {suggestion['pattern_id']}: {hotspot_prefix(hotspot)}{place}{weight}: {suggestion['type']}"
    text += f", {suggestion['pragma']}"
    if "nested_in" in suggestion:
        text += f"; nested in suggestion {', '.join(suggestion['nested_in'])}"
    if "same_region" in suggestion:
        text += f"; alternative to suggestion {', '.join(suggestion['same_region'])}"
    return text


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path = arguments.get("project_path", "")
        file_path_filter: Optional[str] = arguments.get("file_path")
        limit = max(int(arguments.get("limit", DEFAULT_LIMIT)), 0)

        dot_discopop = Path(project_path) / ".discopop"
        patch_gen_dir = dot_discopop / "patch_generator"

        if not patch_gen_dir.exists():
            return ctx.error("No suggestions exist. Run gather_data first.", project_path, TOOL.name)

        file_mapping = ctx.get_file_mapping(project_path) or {}
        file_id_filter: Optional[int] = None
        if file_path_filter is not None:
            resolved_request = resolve_source_path(project_path, file_path_filter)
            file_id_filter = next(
                (fid for fid, path in file_mapping.items() if path.resolve() == resolved_request), None
            )
            if file_id_filter is None:
                return ctx.error(
                    f"file_path is not part of the analysed program: {file_path_filter}", project_path, TOOL.name
                )

        facts = _suggestion_facts(dot_discopop)
        regions = _regions(dot_discopop)
        hotspots, total = _hotspot_regions(dot_discopop)

        # (hotspot region, suggestion) per patch; a suggestion that changes several files has one per file
        entries: list[tuple[Optional[HotspotRegionInfo], dict[str, Any]]] = []
        pattern_dirs = sorted(
            (d for d in patch_gen_dir.iterdir() if d.is_dir() and d.name.isdigit()), key=lambda d: int(d.name)
        )
        for pattern_dir in pattern_dirs:
            pid = pattern_dir.name
            fact = facts.get(pid, {})
            region = regions.get(pid)
            line = fact.get("line") or (region[1] if region else None)
            for patch_file in sorted(pattern_dir.glob("*.patch")):
                file_id = int(patch_file.stem) if patch_file.stem.isdigit() else None
                if file_id_filter is not None and file_id != file_id_filter:
                    continue
                patch_content = patch_file.read_text()
                mapped = file_mapping.get(file_id) if file_id is not None else None
                patch_source = ToolContext.extract_source_from_patch(patch_content)
                source = mapped if mapped is not None else (Path(patch_source) if patch_source else None)
                pragma_line, pragma = _summarize_patch(patch_content)
                suggestion: dict[str, Any] = {
                    "pattern_id": pid,
                    "file": display_path(project_path, source),
                    "type": fact.get("type", "pattern"),
                    "line": line if line is not None else pragma_line,
                    "pragma": pragma or "(no pragma)",
                    # the doall and reduction patterns are loops; a decision log says it for any region
                    "kind": (region[3] if region is not None and region[3] else "loop").capitalize(),
                }
                if region is not None:
                    suggestion["end_line"] = region[2]
                suggestion.update(_relations(pid, regions))
                kind = suggestion["kind"].lower()
                hotspot = (
                    hotspots.get((fact["file_id"], line, kind)) if "file_id" in fact and line is not None else None
                )
                entries.append((hotspot, suggestion))

        # the longest running first; regions without a measurement keep their order after them
        entries.sort(key=lambda e: -e[0].max_val if e[0] is not None else float("inf"))
        shown = entries[:limit]

        lines = [f"{len({s['pattern_id'] for _, s in entries})} parallelization suggestions, hottest first:"]
        lines += [_describe(s, hotspot, total) for hotspot, s in shown]
        if len(shown) < len(entries):
            lines.append(
                f"{len(entries) - len(shown)} more suggestions not shown (limit={limit}); "
                "pass a larger limit or file_path to see them."
            )
        if entries:
            lines.append(
                "Apply a suggestion by making the change it shows (an OpenMP pragma goes directly above the code it "
                "names). explain_parallelization tells why code has no suggestion."
            )
        else:
            lines[0] = "No parallelization suggestions."
            lines.append("explain_parallelization tells why code was not parallelized.")
        text = "\n".join(lines)
        ctx.log_action(project_path, TOOL.name, f"Listed {len(shown)} of {len(entries)} suggestions")
        return [TextContent(type="text", text=text)]

    except Exception as e:
        error_msg = f"Error retrieving parallelization suggestions: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

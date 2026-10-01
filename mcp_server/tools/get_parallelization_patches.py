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

# MG has 96 suggestions; with the full diffs that is 54 KB.
DEFAULT_LIMIT = 50
# patterns.json lists suggestions per pattern type under these keys
_PATTERN_TYPE_KEYS = {"do_all": "doall", "reduction": "reduction"}

TOOL = Tool(
    name="get_parallelization_patches",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    description=(
        "Retrieve the generated OpenMP parallelization patches. Call this after "
        "gather_data to inspect or present the suggested code changes. "
        "\n\n"
        "Which of them to apply is measured by run_auto_tuning, not decided by reading them. "
        "Use detail='summary' when you only need to see what was found — one line per "
        "suggestion instead of the full diffs. "
        "\n\n"
        "Each detected pattern results in a unified-diff patch file stored under "
        ".discopop/patch_generator/<pattern_id>/. The patch inserts an OpenMP pragma "
        "(e.g. #pragma omp parallel for with appropriate clauses) directly above the "
        "loop it applies to. "
        "\n\n"
        "Use the optional pattern_id parameter to retrieve a single patch when the "
        "user asks about a specific suggestion. Omit it to retrieve all patches. "
        "To see the data dependencies behind a suggestion, call get_data_dependencies "
        "with its source file and line range; explain_parallelization tells why code "
        "without a suggestion was not parallelized. "
        "\n\n"
        "Without hotspot detection (gather_data with hotspot_config_names), the patches "
        "cover every candidate in the code base, including regions that contribute "
        "negligibly to the runtime; get_hotspots shows where the time goes. "
        "\n\n"
        "Example patch content:\n"
        "  --- original/main.cpp\n"
        "  +++ main.cpp\n"
        "  @@ -17,6 +17,7 @@\n"
        "  +  #pragma omp parallel for firstprivate(N)\n"
        "     for (int i = 0; i < N; i++) {\n"
        "       Arr[i] = i % 13;\n"
        "     }\n"
        "\n"
        "Apply patches with manage_patches(action='apply', suggestion_ids=[...]), never by "
        "editing source files."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root.",
            },
            "pattern_id": {
                "type": "string",
                "description": (
                    "If provided, return only the patch for this suggestion ID — the same "
                    "IDs that this tool returns as pattern_id and that run_auto_tuning and "
                    "manage_patches use as suggestion_ids. Omit to return all available patches."
                ),
            },
            "pattern_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Only return these suggestions.",
            },
            "file_path": {
                "type": "string",
                "description": "Only return suggestions for this source file (absolute path).",
            },
            "detail": {
                "type": "string",
                "enum": ["full", "summary"],
                "description": (
                    "How much of each suggestion to return. 'full' (the default) includes the "
                    "unified diff; 'summary' groups the suggestions by source file and gives per "
                    "suggestion only its id, pattern type, lines, the pragma it inserts, its hotspot "
                    "class (if hotspot detection ran) and the suggestions on enclosing code "
                    "('nested_in') and alternatives for the same code ('same_region') — enough to see what was suggested, at a fraction of the size."
                ),
            },
            "limit": {
                "type": "integer",
                "description": f"Maximum number of suggestions to return. Default: {DEFAULT_LIMIT}.",
            },
        },
        "required": ["project_path"],
        "additionalProperties": False,
    },
)


def _summarize_patch(patch_content: str) -> tuple[Optional[int], Optional[str]]:
    """The line a patch targets and the pragma it inserts.

    A suggestion is one added pragma above one loop, so those two facts are what a
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


def _regions(dot_discopop: Path) -> dict[str, tuple[int, int, int]]:
    """Per suggestion id: (file id, first line, last line) of the code it covers, from the
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
    regions: dict[str, tuple[int, int, int]] = {}
    for decision in log.decisions:
        if decision.outcome != ACCEPTED:
            continue
        region = decision.region
        for pattern in decision.patterns:
            regions[str(pattern["pattern_id"])] = (region.file_id, region.start_line, region.end_line)
    return regions


def _hotness(dot_discopop: Path) -> dict[tuple[int, int], str]:
    """Hotspot class per (file id, first line) of a loop; empty without hotspot detection."""
    from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
    from discopop_library.HostpotLoader.detailed_hotspot_loader import load_detailed_hotspots

    try:
        return {
            (r.file_id, r.start_line): r.hotness.name
            for r in load_detailed_hotspots(str(dot_discopop))
            if r.node_type == HotspotNodeType.LOOP
        }
    except Exception as e:
        logger.warning(f"Failed to load the hotspot detection results: {e}")
        return {}


def _relations(pid: str, regions: dict[str, tuple[int, int, int]]) -> dict[str, list[str]]:
    """The suggestions on code enclosing this suggestion's, and those on the same code."""
    own = regions.get(pid)
    if own is None:
        return {}
    nested_in: list[str] = []
    same_region: list[str] = []
    for other, region in regions.items():
        if other == pid or region[0] != own[0]:
            continue
        if region[1:] == own[1:]:
            same_region.append(other)
        elif region[1] <= own[1] and own[2] <= region[2]:
            nested_in.append(other)
    relations: dict[str, list[str]] = {}
    if nested_in:
        relations["nested_in"] = sorted(nested_in, key=int)
    if same_region:
        relations["same_region"] = sorted(same_region, key=int)
    return relations


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path = arguments.get("project_path", "")
        pattern_id_filter: Optional[str] = arguments.get("pattern_id")
        pattern_ids_filter: Optional[set[str]] = (
            {str(i) for i in arguments["pattern_ids"]} if arguments.get("pattern_ids") else None
        )
        file_path_filter: Optional[str] = arguments.get("file_path")
        summary_only: bool = arguments.get("detail", "full") == "summary"
        limit = int(arguments.get("limit", DEFAULT_LIMIT))

        p = Path(project_path)
        dot_discopop = p / ".discopop"
        patch_gen_dir = dot_discopop / "patch_generator"

        if not patch_gen_dir.exists():
            return ctx.error("patch_generator directory not found. Run gather_data first.")

        file_mapping = ctx.get_file_mapping(project_path) or {}
        file_id_filter: Optional[int] = None
        if file_path_filter is not None:
            resolved_request = Path(file_path_filter).resolve()
            file_id_filter = next(
                (fid for fid, path in file_mapping.items() if path.resolve() == resolved_request), None
            )
            if file_id_filter is None:
                return ctx.error(
                    f"file_path is not part of the analysed program: {file_path_filter}",
                    project_path,
                    "get_parallelization_patches",
                )

        facts = _suggestion_facts(dot_discopop)
        regions = _regions(dot_discopop)
        hotness = _hotness(dot_discopop)

        patches = []
        # Suggestion ids are strings throughout this server (run_auto_tuning, manage_patches,
        # the applicator); only the directory name has to be numeric.
        pattern_dirs = sorted(
            (d for d in patch_gen_dir.iterdir() if d.is_dir() and d.name.isdigit()), key=lambda d: int(d.name)
        )
        for pattern_dir in pattern_dirs:
            pid = pattern_dir.name
            if pattern_id_filter is not None and pid != str(pattern_id_filter):
                continue
            if pattern_ids_filter is not None and pid not in pattern_ids_filter:
                continue

            # one patch per file the suggestion changes, named <file id>.patch
            for patch_file in sorted(pattern_dir.glob("*.patch")):
                file_id = int(patch_file.stem) if patch_file.stem.isdigit() else None
                if file_id_filter is not None and file_id != file_id_filter:
                    continue
                patch_content = patch_file.read_text()
                mapped = file_mapping.get(file_id) if file_id is not None else None
                source_file = (
                    str(mapped) if mapped is not None else ToolContext.extract_source_from_patch(patch_content)
                )
                fact = facts.get(pid, {})
                patch: dict[str, Any] = {"pattern_id": pid, "source_file": source_file}
                if "type" in fact:
                    patch["type"] = fact["type"]
                if "collapse" in fact:
                    patch["collapse"] = fact["collapse"]
                region = regions.get(pid)
                line = fact.get("line") or (region[1] if region else None)
                if line is not None:
                    patch["line"] = line
                if region is not None:
                    patch["end_line"] = region[2]
                if hotness and line is not None and "file_id" in fact:
                    patch["hotness"] = hotness.get((fact["file_id"], line), "unclassified")
                patch.update(_relations(pid, regions))
                if summary_only:
                    patch["pragma"] = _summarize_patch(patch_content)[1]
                else:
                    patch["patch_content"] = patch_content
                patches.append(patch)

        # limit counts suggestions; one that changes several files keeps all its patches
        shown_ids = list(dict.fromkeys(patch["pattern_id"] for patch in patches))[: max(limit, 0)]
        shown = [patch for patch in patches if patch["pattern_id"] in set(shown_ids)]
        result: dict[str, Any] = {
            "status": "success",
            "project_path": project_path,
            "num_suggestions": len({patch["pattern_id"] for patch in patches}),
        }
        if summary_only:
            # the file is named once per file rather than once per suggestion
            by_file: dict[str, list[dict[str, Any]]] = {}
            for patch in shown:
                by_file.setdefault(str(patch.pop("source_file")), []).append(patch)
            result["files"] = [{"file": f, "suggestions": entries} for f, entries in by_file.items()]
        else:
            result["patches"] = shown
        if len(shown) < len(patches):
            result["truncated"] = True

        pattern_ids: list[str] = sorted({patch["pattern_id"] for patch in patches}, key=int)
        ctx.log_action(
            project_path,
            "get_parallelization_patches",
            f"Found {len(patches)} patches across {len(pattern_ids)} pattern IDs: {pattern_ids}",
        )
        if pattern_ids:
            # Repeated here because a caller that reached the patches is exactly the one
            # about to pick from them by hand.
            result["next_step"] = (
                "Which of these to apply is a question run_auto_tuning answers by measuring; "
                "call it (optionally with apply=true) before applying anything. "
                "get_data_dependencies shows the dependencies behind a suggestion, given its "
                "source file and line range."
            )
            if result.get("truncated"):
                result["next_step"] += (
                    " Not all suggestions are shown: narrow with file_path or pattern_ids, raise limit, "
                    "or use detail='summary'."
                )
        ctx.log_response("get_parallelization_patches", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error retrieving parallelization patches: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

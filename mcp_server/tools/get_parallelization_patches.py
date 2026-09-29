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
    name="get_parallelization_patches",
    annotations=ToolAnnotations(readOnlyHint=True),
    description=(
        "Retrieve the generated OpenMP parallelization patches. Call this after "
        "gather_data to inspect or present the suggested code changes. "
        "\n\n"
        "Reading the patches is not how you decide which of them to apply: which "
        "combination is actually fastest is what run_auto_tuning measures, and it has to "
        "run before anything is applied. Use detail='summary' when you only need to see "
        "what was found — one line per suggestion instead of the full diffs. "
        "\n\n"
        "Each detected pattern results in a unified-diff patch file stored under "
        ".discopop/patch_generator/<pattern_id>/. The patch inserts an OpenMP pragma "
        "(e.g. #pragma omp parallel for with appropriate clauses) directly above the "
        "loop it applies to. Patches are in standard unified diff format and can be "
        "applied with the patch command or via discopop_patch_applicator. "
        "\n\n"
        "Use the optional pattern_id parameter to retrieve a single patch when the "
        "user asks about a specific suggestion. Omit it to retrieve all patches. "
        "\n\n"
        "NOTE: If the optional hotspot detection pipeline was not run prior to "
        "pattern detection, the returned patches cover every parallelization candidate "
        "found in the code base — they are not guaranteed to correspond to hotspots "
        "and may include regions with negligible contribution to overall runtime. "
        "To restrict suggestions to hotspot regions, re-run gather_data with "
        "hotspot_config_names set. "
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
        "IMPORTANT: To apply a patch, always use manage_patches(action='apply', "
        "suggestion_ids=[...]) — never read the patch content here and edit source files manually. "
        "The manage_patches tool applies changes in one tool call and consumes far fewer tokens."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_path": {
                "type": "string",
                "description": "Absolute path to the project root.",
            },
            "pattern_id": {
                "type": "integer",
                "description": (
                    "If provided, return only the patch for this specific pattern ID "
                    "(as shown in patterns.json). Omit to return all available patches."
                ),
            },
            "detail": {
                "type": "string",
                "enum": ["full", "summary"],
                "description": (
                    "How much of each patch to return. 'full' (the default) includes the "
                    "unified diff; 'summary' returns only the pattern id, the source file, "
                    "the target line and the pragma that would be inserted — enough to see "
                    "what was suggested, at a fraction of the size."
                ),
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


def handle(arguments: dict[str, Any], ctx: ToolContext) -> list[TextContent]:
    try:
        project_path = arguments.get("project_path", "")
        pattern_id_filter: Optional[int] = arguments.get("pattern_id")
        summary_only: bool = arguments.get("detail", "full") == "summary"

        p = Path(project_path)
        patch_gen_dir = p / ".discopop" / "patch_generator"

        if not patch_gen_dir.exists():
            return ctx.error("patch_generator directory not found. Run run_pattern_detection first.")

        patches = []
        for pattern_dir in sorted(patch_gen_dir.iterdir(), key=lambda d: d.name):
            if not pattern_dir.is_dir():
                continue
            try:
                pid = int(pattern_dir.name)
            except ValueError:
                continue

            if pattern_id_filter is not None and pid != pattern_id_filter:
                continue

            for patch_file in sorted(pattern_dir.glob("*.patch")):
                patch_content = patch_file.read_text()
                source_file = ToolContext.extract_source_from_patch(patch_content)
                patch: dict[str, Any] = {"pattern_id": pid, "source_file": source_file}
                if summary_only:
                    line, pragma = _summarize_patch(patch_content)
                    patch["target_line"] = line
                    patch["pragma"] = pragma
                else:
                    patch["patch_content"] = patch_content
                patches.append(patch)

        pattern_ids: list[int] = sorted({p["pattern_id"] for p in patches if isinstance(p["pattern_id"], int)})
        ctx.log_action(
            project_path,
            "get_parallelization_patches",
            f"Found {len(patches)} patches across {len(pattern_ids)} pattern IDs: {pattern_ids}",
        )
        result = {
            "status": "success",
            "project_path": project_path,
            "patches": patches,
        }
        if pattern_ids:
            # Repeated here because a caller that reached the patches is exactly the one
            # about to pick from them by hand.
            result["next_step"] = (
                "Which of these to apply is a question run_auto_tuning answers by measuring; "
                "call it (optionally with apply=true) before applying anything."
            )
        ctx.log_response("get_parallelization_patches", result)
        return [TextContent(type="text", text=json.dumps(result))]

    except Exception as e:
        error_msg = f"Error retrieving parallelization patches: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return [TextContent(type="text", text=json.dumps({"status": "error", "message": error_msg}))]

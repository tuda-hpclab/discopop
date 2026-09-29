# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the agent is actually asked.

One conversation per suggestion, covering the whole patch set: a compiler error in one
file is regularly caused by the patch to another, so splitting the set into per-file
conversations would hide the cause from the model.

``--prompts`` walks a **ladder** of templates, from terse to increasingly explicit:

1. ``minimal`` -- the patch and the diagnostics, nothing else.
2. ``context`` -- adds the source before and after the patch, line numbered.
3. ``guided`` -- adds what DiscoPoP itself determined about the region (the shared,
   private, firstprivate and reduction variables), which is usually exactly the
   information a missing-clause error needs.

A later attempt therefore does not just re-roll the dice: it asks a better question.
The templates live as files under ``prompts/`` so they can be edited without touching
code, and ``--prompt-dir`` points at a different set.

**Budgeting.** A multi-file suggestion can outgrow a sensible prompt, so the material
is tiered by whether the diagnostics implicate a file, and dropped under
``--max-prompt-chars`` in a fixed, documented order (see :func:`render`). The patches
themselves are never dropped: a file whose patch is missing cannot be reasoned about,
and the model would have to guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from discopop_library.PatchRepair.diagnostics import Diagnostic, truncate_diagnostics
from discopop_library.PatchRepair.patchset import PatchSet

logger = logging.getLogger("PatchRepair").getChild("prompts")

BUILTIN_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "prompts")

# The ladder, in the order attempts walk it. Cycled when --prompts exceeds its length.
PROMPT_LADDER = ("minimal", "context", "guided")
RETRY_TEMPLATE = "retry"

# Clause fields of a pattern worth showing: what DiscoPoP decided, in its own words.
PATTERN_CLAUSE_FIELDS = (
    ("private", "private"),
    ("first_private", "firstprivate"),
    ("last_private", "lastprivate"),
    ("shared", "shared"),
    ("reduction", "reduction"),
)


def output_contract(file_ids: List[int]) -> str:
    """The answer format, spelled out. The single most load-bearing part of the prompt."""
    example_id = file_ids[0] if file_ids else 0
    lines = [
        "## How to answer",
        "",
        "**Do not use any tools.** Do not read files, do not edit files, do not run",
        "commands. Everything needed is in this message, and the project you would read",
        "is not the one the patch belongs to. Answer directly with text.",
        "",
        "Answer with the corrected patch and nothing else -- no explanation outside the",
        "blocks, no code fences inside them.",
        "",
        "Emit **one block per file that needs changing**, and no block at all for a file",
        "whose patch is already correct:",
        "",
        "```",
        "===BEGIN PATCH " + str(example_id) + "===",
        "--- a/<path>",
        "+++ b/<path>",
        "@@ ... @@",
        " <context line>",
        "+<added line>",
        "===END PATCH " + str(example_id) + "===",
        "```",
        "",
        "The file ids of this suggestion are: " + ", ".join(str(i) for i in file_ids) + ".",
        "",
        "Rules:",
        "",
        "* **The diff must apply to the ORIGINAL, UNPATCHED file.** This is the easiest",
        "  thing to get wrong here. The patch above *adds* the OpenMP directive, so the",
        "  original file does not contain it at all. To change the directive, change the",
        "  `+` line inside the patch. Do **not** write a diff that removes the current",
        "  directive and adds a corrected one -- there is nothing to remove in the",
        "  original file, and such a patch will be rejected.",
        "* **Keep the parallelization.** Do not delete the `#pragma omp` directives: a",
        "  patch that fixes the error by removing them compiles, but silently turns the",
        "  suggestion into a no-op, and will be rejected.",
        "* Prefer correcting the directive's clauses (`private`, `firstprivate`,",
        "  `shared`, `reduction`, `collapse`) over restructuring the code.",
        "* Change nothing outside the region the original patch touches.",
        "* Exact line numbers in the `@@` headers are not critical -- the patch is",
        "  re-derived after it applies -- but the context lines must match the real code.",
    ]
    return "\n".join(lines)


@dataclass
class PromptContext:
    """Everything a prompt can be built from, before any budgeting is applied."""

    suggestion_id: int
    pattern_type: str
    patch_set: PatchSet
    # file_id -> the file's full text, before and after the patch
    original_sources: Dict[int, str] = field(default_factory=dict)
    patched_sources: Dict[int, str] = field(default_factory=dict)
    diagnostics_text: str = ""
    diagnostics: List[Diagnostic] = field(default_factory=list)
    implicated_file_ids: List[int] = field(default_factory=list)
    pattern: Optional[Dict[str, Any]] = None
    # The line ranges each file's patch touches, used to window the source.
    touched_lines: Dict[int, List[int]] = field(default_factory=dict)


def template_for_attempt(attempt: int, prompt_dir: Optional[str] = None) -> str:
    """The ladder rung attempt ``attempt`` (1-based) uses."""
    return PROMPT_LADDER[(attempt - 1) % len(PROMPT_LADDER)]


def load_template(name: str, prompt_dir: Optional[str] = None) -> str:
    """The template text, from ``--prompt-dir`` if it defines one, else the built-in."""
    if prompt_dir:
        override = os.path.join(prompt_dir, name + ".md")
        if os.path.exists(override):
            with open(override, "r") as f:
                return strip_license_header(f.read())
    with open(os.path.join(BUILTIN_PROMPT_DIR, name + ".md"), "r") as f:
        return strip_license_header(f.read())


def strip_license_header(text: str) -> str:
    """Drop a leading HTML comment from a template.

    The templates are source files of this repository and carry its license header like
    every other file, but they are also sent to a model verbatim. A licence notice at
    the top of the prompt costs tokens and tells the model something it has no use for,
    so it is stripped on the way out. Only a *leading* comment is removed: a comment
    further down is part of what the author wrote.
    """
    stripped = text.lstrip()
    if not stripped.startswith("<!--"):
        return text
    end = stripped.find("-->")
    if end == -1:
        return text
    return stripped[end + len("-->") :].lstrip("\r\n")


def render(
    context: PromptContext,
    template_name: str,
    context_lines: int,
    max_error_chars: int,
    max_prompt_chars: int,
    prompt_dir: Optional[str] = None,
) -> str:
    """Build the prompt, shrinking it until it fits.

    Content is dropped in a fixed order, cheapest information first:

    1. the source of files the diagnostics do not implicate;
    2. ``context_lines``, halved repeatedly down to 10;
    3. the diagnostics, truncated further.

    The patch set is never dropped, so a prompt that is still too long is sent too
    long: a truncated patch would be worse than a large prompt.
    """
    template = load_template(template_name, prompt_dir)

    include_all_sources = True
    lines = context_lines
    errors = max_error_chars
    for _ in range(8):
        prompt = _render_once(context, template, lines, errors, include_all_sources)
        if max_prompt_chars <= 0 or len(prompt) <= max_prompt_chars:
            return prompt
        if include_all_sources and len(context.patch_set.entries) > len(context.implicated_file_ids) > 0:
            include_all_sources = False
            continue
        if lines > 10:
            lines = max(10, lines // 2)
            continue
        if errors > 1000:
            errors = max(1000, errors // 2)
            continue
        break
    logger.warning(
        "The prompt for suggestion "
        + str(context.suggestion_id)
        + " is longer than --max-prompt-chars even after dropping everything droppable."
    )
    return _render_once(context, template, lines, errors, include_all_sources)


def render_retry(failure: str, file_ids: List[int], prompt_dir: Optional[str] = None) -> str:
    """The follow-up turn: the task is already in context, only the failure is new."""
    template = load_template(RETRY_TEMPLATE, prompt_dir)
    return _substitute(template, {"failure": failure, "output_contract": output_contract(file_ids)})


def _render_once(
    context: PromptContext,
    template: str,
    context_lines: int,
    max_error_chars: int,
    include_all_sources: bool,
) -> str:
    file_ids = context.patch_set.file_ids
    shown = context.implicated_file_ids if (not include_all_sources and context.implicated_file_ids) else file_ids

    return _substitute(
        template,
        {
            "identity": _identity(context),
            "patch_blocks": _patch_blocks(context),
            "original_source": _sources(context, context.original_sources, shown, context_lines, "before"),
            "patched_source": _sources(context, context.patched_sources, shown, context_lines, "after"),
            "diagnostics": truncate_diagnostics(context.diagnostics_text, max_error_chars).strip() or "(none)",
            "pattern_metadata": _pattern_metadata(context),
            "output_contract": output_contract(file_ids),
        },
    )


def _substitute(template: str, values: Dict[str, str]) -> str:
    """Fill ``{placeholder}`` in, leaving anything unknown alone.

    Deliberately not ``str.format``: a template contains braces of its own (C code in an
    example, a JSON snippet), and ``format`` would choke on them. A placeholder DiscoPoP
    does not know stays in the text rather than raising, so a user's own template cannot
    fail a run at the point where the model was about to be asked.
    """
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _identity(context: PromptContext) -> str:
    lines = [
        "## The suggestion",
        "",
        "* DiscoPoP suggestion id: " + str(context.suggestion_id),
        "* Pattern type: " + (context.pattern_type or "unknown"),
        "* Files (DiscoPoP file id -> path):",
    ]
    implicated = set(context.implicated_file_ids)
    for file_id, target in sorted(context.patch_set.targets().items()):
        marker = "  <- the compiler errors are in this file" if file_id in implicated else ""
        lines.append("    * " + str(file_id) + " -> " + str(target) + marker)
    return "\n".join(lines)


def _patch_blocks(context: PromptContext) -> str:
    lines = ["## The patch to fix", ""]
    for file_id, entry in sorted(context.patch_set.entries.items()):
        lines.append("### File id " + str(file_id) + " (" + os.path.basename(str(entry.target)) + ")")
        lines.append("")
        lines.append("```")
        lines.append(entry.text.rstrip("\n"))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def _sources(
    context: PromptContext,
    sources: Dict[int, str],
    shown_file_ids: List[int],
    context_lines: int,
    label: str,
) -> str:
    blocks: List[str] = []
    for file_id in sorted(shown_file_ids):
        text = sources.get(file_id)
        if text is None:
            continue
        entry = context.patch_set.entries.get(file_id)
        name = os.path.basename(str(entry.target)) if entry is not None else str(file_id)
        window = _window(text, context.touched_lines.get(file_id, []), context_lines)
        blocks.append("### File id " + str(file_id) + " (" + name + "), " + label + " the patch\n")
        blocks.append("```")
        blocks.append(window)
        blocks.append("```\n")
    return "\n".join(blocks) if blocks else "(not included)"


def _window(text: str, touched: List[int], context_lines: int) -> str:
    """The patched region plus ``context_lines`` around it, with absolute line numbers.

    The whole file when it is short enough to be cheaper than explaining a window, and
    an elision marker between windows so the model can see that lines are missing rather
    than believe two distant regions are adjacent.
    """
    lines = text.splitlines()
    if not touched:
        selected = set(range(1, len(lines) + 1))
    else:
        selected = set()
        for line_number in touched:
            for candidate in range(line_number - context_lines, line_number + context_lines + 1):
                if 1 <= candidate <= len(lines):
                    selected.add(candidate)

    rendered: List[str] = []
    previous: Optional[int] = None
    width = len(str(len(lines)))
    for number in sorted(selected):
        if previous is not None and number != previous + 1:
            rendered.append(" " * width + "  ...")
        rendered.append(str(number).rjust(width) + "  " + lines[number - 1])
        previous = number
    return "\n".join(rendered)


def _pattern_metadata(context: PromptContext) -> str:
    """What DiscoPoP determined about the region, as the guided template shows it."""
    pattern = context.pattern
    if not pattern:
        return "(DiscoPoP recorded no further metadata for this suggestion.)"

    lines: List[str] = []
    pragma = str(pattern.get("pragma") or "").strip()
    if pragma:
        lines.append("* Directive DiscoPoP generated: `" + pragma + "`")
    for key, clause in PATTERN_CLAUSE_FIELDS:
        values = pattern.get(key)
        if isinstance(values, list) and values:
            lines.append("* `" + clause + "`: " + ", ".join(str(v) for v in values))
        elif isinstance(values, list):
            lines.append("* `" + clause + "`: (empty)")
    for key, label in (
        ("scheduling_clause", "Scheduling"),
        ("collapse_level", "Collapse level"),
        ("average_iteration_count", "Average iteration count"),
    ):
        value = pattern.get(key)
        if value not in (None, "", -1):
            lines.append("* " + label + ": " + str(value))
    start, end = pattern.get("start_line"), pattern.get("end_line")
    if start and end:
        lines.append("* Region (file id:line): " + str(start) + " to " + str(end))
    return "\n".join(lines) if lines else "(DiscoPoP recorded no further metadata for this suggestion.)"


def load_pattern_metadata(dot_dp_path: str, suggestion_id: int) -> Optional[Dict[str, Any]]:
    """The explorer's own record of one suggestion, or None.

    Read from ``patterns.json`` rather than from the pickled detection result: it is the
    same data in a form that can be put in a prompt as-is.
    """
    patterns_path = os.path.join(dot_dp_path, "explorer", "patterns.json")
    if not os.path.exists(patterns_path):
        return None
    try:
        with open(patterns_path, "r") as f:
            document = json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.debug("Could not read " + patterns_path + "; continuing without pattern metadata.")
        return None
    for pattern_type, patterns in (document.get("patterns") or {}).items():
        if not isinstance(patterns, list):
            continue
        for pattern in patterns:
            if isinstance(pattern, dict) and pattern.get("pattern_id") == suggestion_id:
                enriched = dict(pattern)
                enriched.setdefault("pattern_type", pattern_type)
                return enriched
    return None


def pattern_type_of(dot_dp_path: str, suggestion_id: int) -> str:
    pattern = load_pattern_metadata(dot_dp_path, suggestion_id)
    return str((pattern or {}).get("pattern_type") or "unknown")

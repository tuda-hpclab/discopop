# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The prompt templates of the patch repair and completion, as the GUI edits them.

The tool reads a template from ``.discopop/patch_repair/prompts/<name>.md`` when that file exists and from the
built-in set otherwise (``PatchRepair/prompts.py``, option ``--prompt-dir``). Editing is therefore writing a file of
that name; resetting is deleting it. A template saved unchanged is not written at all, so what was never customized
keeps following the built-in text when DiscoPoP is updated.

Toolkit independent.
"""

import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

from discopop_library.PatchRepair.PatchRepairArguments import PROJECT_PROMPT_DIR_NAME
from discopop_library.PatchRepair.prompts import (
    COMPLETION_LADDER,
    COMPLETION_RETRY_TEMPLATE,
    PROMPT_LADDER,
    RETRY_TEMPLATE,
    load_template,
)

GROUP_REPAIR = "Patch Repair"
GROUP_COMPLETION = "Patch Completion"

# the placeholders a template can use, with what the tool puts there
PLACEHOLDERS: Dict[str, str] = {
    "identity": "the suggestion id, its pattern type and the files of its patch set",
    "patch_blocks": "the patch of every file of the suggestion",
    "original_source": "the code before the patch, around the patched region (line numbered)",
    "patched_source": "the code after the patch, around the patched region (line numbered)",
    "diagnostics": "the compiler's error messages",
    "pattern_metadata": "what DiscoPoP determined about the region (directive, clauses, region)",
    "placeholders": "the markers to replace and what each one asks for (completion)",
    "failure": "what was wrong with the previous answer (follow-up turn)",
    "output_contract": "the answer format; fixed by the tool and the one thing an answer is parsed by",
}


@dataclass(frozen=True)
class TemplateInfo:
    name: str
    group: str
    title: str
    description: str
    # the placeholders the tool fills in for this template
    available: Tuple[str, ...]
    # without these the prompt cannot work: the answer is parsed by the contract, and a diff against the original
    # source cannot be written without seeing it
    required: Tuple[str, ...]


_REPAIR_PLACEHOLDERS = (
    "identity",
    "patch_blocks",
    "original_source",
    "patched_source",
    "diagnostics",
    "pattern_metadata",
    "output_contract",
)

TEMPLATES: Tuple[TemplateInfo, ...] = (
    TemplateInfo(
        PROMPT_LADDER[0],
        GROUP_REPAIR,
        "Repair, 1st prompt (minimal)",
        "The first attempt: the patch and the diagnostics, nothing else.",
        _REPAIR_PLACEHOLDERS,
        ("original_source", "output_contract"),
    ),
    TemplateInfo(
        PROMPT_LADDER[1],
        GROUP_REPAIR,
        "Repair, 2nd prompt (context)",
        "The second attempt: adds the source before and after the patch.",
        _REPAIR_PLACEHOLDERS,
        ("original_source", "output_contract"),
    ),
    TemplateInfo(
        PROMPT_LADDER[2],
        GROUP_REPAIR,
        "Repair, 3rd prompt (guided)",
        "The third attempt (and the first again after it): adds what DiscoPoP determined about the region.",
        _REPAIR_PLACEHOLDERS,
        ("original_source", "output_contract"),
    ),
    TemplateInfo(
        RETRY_TEMPLATE,
        GROUP_REPAIR,
        "Repair, follow-up turn",
        "Sent inside an attempt when the answer was rejected; the conversation already holds the task.",
        ("failure", "output_contract"),
        ("failure", "output_contract"),
    ),
    TemplateInfo(
        COMPLETION_LADDER[0],
        GROUP_COMPLETION,
        "Completion prompt",
        "Asks to replace the placeholders the patch generator left in a patch.",
        ("identity", "patch_blocks", "original_source", "patched_source", "pattern_metadata", "placeholders")
        + ("output_contract",),
        ("original_source", "placeholders", "output_contract"),
    ),
    TemplateInfo(
        COMPLETION_RETRY_TEMPLATE,
        GROUP_COMPLETION,
        "Completion, follow-up turn",
        "Sent inside an attempt when the answer was rejected; the conversation already holds the task.",
        ("failure", "output_contract"),
        ("failure", "output_contract"),
    ),
)


def template_info(name: str) -> TemplateInfo:
    for info in TEMPLATES:
        if info.name == name:
            return info
    raise KeyError(name)


def templates_of_group(group: str) -> List[TemplateInfo]:
    return [info for info in TEMPLATES if info.group == group]


def project_prompt_dir(dot_dp: str) -> str:
    return os.path.join(dot_dp, "patch_repair", PROJECT_PROMPT_DIR_NAME)


def _override_path(dot_dp: str, name: str) -> str:
    template_info(name)  # an unknown name must not become a file name
    return os.path.join(project_prompt_dir(dot_dp), name + ".md")


def builtin_text(name: str) -> str:
    template_info(name)
    return load_template(name)


def is_customized(dot_dp: str, name: str) -> bool:
    return os.path.exists(_override_path(dot_dp, name))


def current_text(dot_dp: str, name: str) -> str:
    """What the tool sends for ``name`` in this project: the project's template, else the built-in one."""
    template_info(name)
    return load_template(name, project_prompt_dir(dot_dp))


def missing_placeholders(name: str, text: str) -> List[str]:
    """The required placeholders ``text`` does not contain."""
    return [key for key in template_info(name).required if "{" + key + "}" not in text]


def unknown_placeholders(name: str, text: str) -> List[str]:
    """Placeholders ``text`` uses that the tool does not fill in for ``name``; they stay in the prompt verbatim."""
    available = set(template_info(name).available)
    return [key for key in PLACEHOLDERS if "{" + key + "}" in text and key not in available]


def save_template(dot_dp: str, name: str, text: str) -> bool:
    """Store ``text`` as the project's template; True if a file was written.

    The text of the built-in template is stored as no file at all, so a template the user reverted by hand is not
    frozen at today's wording.
    """
    path = _override_path(dot_dp, name)
    normalized = text.strip("\n") + "\n"
    if normalized.strip() == builtin_text(name).strip():
        reset_template(dot_dp, name)
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(normalized)
    return True


def reset_template(dot_dp: str, name: str) -> None:
    path = _override_path(dot_dp, name)
    if os.path.exists(path):
        os.remove(path)

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The prompt templates of the suggestion check, and the project's own versions of them.

The templates shipped with DiscoPoP are in prompts/. A project can replace each of them: its version is stored in
``.discopop/project/prompts/suggestion_check/<name>.md`` (kept by "Reset Project", like the configurations) and is used
instead of the shipped one. The GUI edits them (Settings > Suggestion check prompts), the command line takes another
directory with --prompt-dir. Toolkit-free.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from discopop_library.PatchRepair.prompts import strip_license_header

PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")


@dataclass(frozen=True)
class Template:
    name: str
    title: str
    purpose: str
    # what the check fills in, with a short description each
    placeholders: Tuple[Tuple[str, str], ...]


TEMPLATES: Tuple[Template, ...] = (
    Template(
        "check",
        "Check",
        "The first prompt of every attempt: the agent decides and, for an approval, changes its copy of the project.",
        (
            ("description", "the suggestion: location and the directive DiscoPoP would suggest without the blockers"),
            ("blockers", "the blockers in words, with the lines and the data involved"),
            ("code", "the loop and the code around every blocker, with line numbers"),
        ),
    ),
    Template(
        "review",
        "Review",
        "The prompt of the second agent, which checks an approval in a read-only copy with the changes applied.",
        (
            ("description", "the suggestion, as in the check"),
            ("blockers", "the blockers, as in the check"),
            ("code", "the code before the changes, as in the check"),
            ("patch", "the changes of the approval, as a diff"),
            ("assumption", "the assumption the approval states"),
            ("result_differences", 'how the results may differ, as the approval declares: "none" or "rounding"'),
            ("justifications", "the justification of every blocker, with its evidence"),
        ),
    ),
    Template(
        "retry",
        "Follow-up",
        "A follow-up turn in the same attempt, when an answer or the changes cannot be used.",
        (("failure", "what was wrong with the answer or the changes"),),
    ),
)
TEMPLATE_NAMES = tuple(t.name for t in TEMPLATES)


def template(name: str) -> Template:
    for candidate in TEMPLATES:
        if candidate.name == name:
            return candidate
    raise KeyError("no prompt template " + repr(name) + ", expected one of " + ", ".join(TEMPLATE_NAMES))


def custom_prompt_dir(dot_dp_path: str) -> str:
    """where a project keeps its own versions of the templates"""
    return os.path.join(dot_dp_path, "project", "prompts", "suggestion_check")


def _custom_path(prompt_dir: str, name: str) -> str:
    template(name)
    return os.path.join(prompt_dir, name + ".md")


def default_template(name: str) -> str:
    """the template shipped with DiscoPoP"""
    template(name)
    with open(os.path.join(PROMPT_DIR, name + ".md")) as f:
        return strip_license_header(f.read())


def custom_template(prompt_dir: Optional[str], name: str) -> Optional[str]:
    """the project's own version, None if it has none"""
    if not prompt_dir:
        return None
    path = _custom_path(prompt_dir, name)
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        return strip_license_header(f.read())


def effective_template(name: str, prompt_dir: Optional[str] = None) -> str:
    """the template the check uses: the project's own version if there is one, else the shipped one"""
    custom = custom_template(prompt_dir, name)
    return custom if custom is not None else default_template(name)


def is_customized(prompt_dir: Optional[str], name: str) -> bool:
    return custom_template(prompt_dir, name) is not None


def save_template(prompt_dir: str, name: str, text: str) -> bool:
    """stores the project's own version; a text equal to the shipped template removes it instead, so that later
    changes of the shipped template apply again. Returns whether a custom version is stored now."""
    if text == default_template(name):
        reset_template(prompt_dir, name)
        return False
    os.makedirs(prompt_dir, exist_ok=True)
    with open(_custom_path(prompt_dir, name), "w") as f:
        f.write(text)
    return True


def reset_template(prompt_dir: str, name: str) -> None:
    """back to the shipped template"""
    path = _custom_path(prompt_dir, name)
    if os.path.exists(path):
        os.remove(path)


def placeholders_in(text: str) -> List[str]:
    found: List[str] = []
    for match in PLACEHOLDER.finditer(text):
        if match.group(1) not in found:
            found.append(match.group(1))
    return found


def missing_placeholders(name: str, text: str) -> List[str]:
    """the placeholders of the template which the text does not use: their content would not reach the agent"""
    used = set(placeholders_in(text))
    return [p for p, _ in template(name).placeholders if p not in used]


def unknown_placeholders(name: str, text: str) -> List[str]:
    """placeholders the check does not fill: they would reach the agent as they are"""
    known = {p for p, _ in template(name).placeholders}
    return [p for p in placeholders_in(text) if p not in known]


def digest(text: str) -> str:
    """a short fingerprint of a template, recorded with the results"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def prompt_info(prompt_dir: Optional[str]) -> Dict[str, Dict[str, object]]:
    """per template: whether the project's own version is used, and the fingerprint of the one used"""
    return {
        name: {"custom": is_customized(prompt_dir, name), "sha256": digest(effective_template(name, prompt_dir))}
        for name in TEMPLATE_NAMES
    }

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
from pathlib import Path

import pytest

from discopop_library.PatchRepair.prompts import TEMPLATE_NAMES, load_template
from discopop_library.ProjectManager.services import prompt_templates as pt


def test_every_template_the_tool_reads_can_be_edited() -> None:
    assert sorted(info.name for info in pt.TEMPLATES) == sorted(TEMPLATE_NAMES)


def test_every_builtin_template_uses_its_required_placeholders() -> None:
    """The defaults must pass the very check the editor applies to a user's text."""
    for info in pt.TEMPLATES:
        assert pt.missing_placeholders(info.name, pt.builtin_text(info.name)) == []
        assert pt.unknown_placeholders(info.name, pt.builtin_text(info.name)) == []


def test_current_text_is_the_builtin_until_customized(tmp_path: Path) -> None:
    assert pt.current_text(str(tmp_path), "minimal") == pt.builtin_text("minimal")
    assert not pt.is_customized(str(tmp_path), "minimal")


def test_a_saved_template_is_what_the_tool_reads(tmp_path: Path) -> None:
    dot_dp = str(tmp_path)
    assert pt.save_template(dot_dp, "completion", "Be brief.\n{original_source}\n{placeholders}\n{output_contract}")
    assert pt.is_customized(dot_dp, "completion")
    # the very directory PatchRepairArguments picks up by default
    assert load_template("completion", pt.project_prompt_dir(dot_dp)).startswith("Be brief.")
    assert pt.current_text(dot_dp, "completion").startswith("Be brief.")
    # the other templates are not touched
    assert pt.current_text(dot_dp, "minimal") == pt.builtin_text("minimal")


def test_saving_the_builtin_text_writes_no_file(tmp_path: Path) -> None:
    dot_dp = str(tmp_path)
    pt.save_template(dot_dp, "retry", "changed {failure} {output_contract}")
    assert pt.is_customized(dot_dp, "retry")
    assert pt.save_template(dot_dp, "retry", pt.builtin_text("retry")) is False
    assert not pt.is_customized(dot_dp, "retry")


def test_reset_removes_the_override_and_is_harmless_without_one(tmp_path: Path) -> None:
    dot_dp = str(tmp_path)
    pt.reset_template(dot_dp, "guided")
    pt.save_template(dot_dp, "guided", "x {original_source} {output_contract}")
    pt.reset_template(dot_dp, "guided")
    assert pt.current_text(dot_dp, "guided") == pt.builtin_text("guided")
    assert not os.path.exists(os.path.join(pt.project_prompt_dir(dot_dp), "guided.md"))


def test_placeholder_checks() -> None:
    assert pt.missing_placeholders("retry", "Try again.") == ["failure", "output_contract"]
    # {diagnostics} is not filled in for a follow-up turn
    assert pt.unknown_placeholders("retry", "{failure} {output_contract} {diagnostics}") == ["diagnostics"]


def test_an_unknown_name_is_not_turned_into_a_path(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        pt.save_template(str(tmp_path), "../escape", "x")

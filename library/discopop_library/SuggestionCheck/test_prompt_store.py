# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The project's own versions of the prompt templates."""

from __future__ import annotations

from pathlib import Path

import pytest

from discopop_library.SuggestionCheck import prompt_store
from discopop_library.SuggestionCheck.prompt_store import (
    TEMPLATE_NAMES,
    custom_prompt_dir,
    default_template,
    effective_template,
    is_customized,
    missing_placeholders,
    prompt_info,
    reset_template,
    save_template,
    unknown_placeholders,
)


@pytest.mark.parametrize("name", TEMPLATE_NAMES)
def test_the_shipped_templates_use_exactly_their_placeholders(name: str) -> None:
    text = default_template(name)
    assert missing_placeholders(name, text) == []
    assert unknown_placeholders(name, text) == []
    # without the license header
    assert "BSD License" not in text


def test_a_project_version_replaces_the_shipped_one_until_it_is_reset(tmp_path: Path) -> None:
    prompt_dir = custom_prompt_dir(str(tmp_path / ".discopop"))
    assert prompt_dir == str(tmp_path / ".discopop" / "project" / "prompts" / "suggestion_check")
    assert effective_template("check", prompt_dir) == default_template("check")
    assert not is_customized(prompt_dir, "check")

    assert save_template(prompt_dir, "check", "mine {description}")
    assert effective_template("check", prompt_dir) == "mine {description}"
    assert is_customized(prompt_dir, "check")
    # the others stay the shipped ones
    assert effective_template("review", prompt_dir) == default_template("review")

    reset_template(prompt_dir, "check")
    assert effective_template("check", prompt_dir) == default_template("check")
    reset_template(prompt_dir, "check")  # nothing to reset


def test_saving_the_shipped_text_removes_the_project_version(tmp_path: Path) -> None:
    prompt_dir = str(tmp_path / "prompts")
    save_template(prompt_dir, "retry", "mine {failure}")
    assert not save_template(prompt_dir, "retry", default_template("retry"))
    assert not is_customized(prompt_dir, "retry")


def test_placeholders_which_are_missing_or_unknown() -> None:
    assert missing_placeholders("check", "{description} {code}") == ["blockers"]
    assert unknown_placeholders("check", "{description} {blockers} {code} {patch} {x_y}") == ["patch", "x_y"]


def test_an_unknown_template_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(KeyError):
        save_template(str(tmp_path), "../escape", "x")
    with pytest.raises(KeyError):
        default_template("nope")


def test_the_results_record_which_templates_were_used(tmp_path: Path) -> None:
    prompt_dir = str(tmp_path / "prompts")
    save_template(prompt_dir, "review", "mine {patch}")
    info = prompt_info(prompt_dir)
    assert set(info) == set(TEMPLATE_NAMES)
    assert info["review"] == {"custom": True, "sha256": prompt_store.digest("mine {patch}")}
    assert info["check"] == {"custom": False, "sha256": prompt_store.digest(default_template("check"))}

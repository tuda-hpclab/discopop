# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for what the agent is actually asked."""

from pathlib import Path

from discopop_library.PatchRepair.patchset import PatchEntry, PatchSet
from discopop_library.PatchRepair.prompts import (
    PROMPT_LADDER,
    PromptContext,
    load_template,
    output_contract,
    render,
    strip_license_header,
    template_for_attempt,
)


def test_the_license_header_is_not_sent_to_the_model() -> None:
    """The templates are source files and carry the header; the prompt must not."""
    for name in PROMPT_LADDER + ("retry",):
        assert not load_template(name).lstrip().startswith("<!--")


def test_only_a_leading_comment_is_stripped() -> None:
    # a comment further down is part of what the author wrote
    text = "Do this.\n\n<!-- a note the author meant to keep -->\n"
    assert strip_license_header(text) == text


def test_the_ladder_cycles_when_more_attempts_are_asked_for_than_it_has_rungs() -> None:
    assert template_for_attempt(1) == PROMPT_LADDER[0]
    assert template_for_attempt(len(PROMPT_LADDER) + 1) == PROMPT_LADDER[0]


def test_every_rung_shows_the_file_the_diff_is_against() -> None:
    """The mistake a real model made first, so no rung may leave it out.

    A model shown only the patch and the error has no way to write a diff that applies:
    the answer is a diff *against* the original source, so the original source is not
    optional context even in the tersest rung.
    """
    for name in PROMPT_LADDER:
        assert "{original_source}" in load_template(name)


def test_the_contract_forbids_tool_use() -> None:
    # a coding agent pointed at a task will otherwise reach for its edit tool
    assert "Do not use any tools" in output_contract([0])


def test_the_contract_names_the_suggestions_file_ids() -> None:
    contract = output_contract([3, 7])
    assert "3, 7" in contract
    assert "===BEGIN PATCH 3===" in contract


def _context(tmp_path: Path, files: int = 1) -> PromptContext:
    patch_set = PatchSet(suggestion_id=1)
    originals = {}
    patched = {}
    for file_id in range(files):
        target = tmp_path / ("f" + str(file_id) + ".cpp")
        target.write_text("\n".join("line " + str(n) for n in range(1, 400)) + "\n")
        patch_set.entries[file_id] = PatchEntry(file_id, "--- a\n+++ b\n@@ -10,1 +10,2 @@\n+x\n", target)
        originals[file_id] = target.read_text()
        patched[file_id] = target.read_text()
    return PromptContext(
        suggestion_id=1,
        pattern_type="do_all",
        patch_set=patch_set,
        original_sources=originals,
        patched_sources=patched,
        diagnostics_text="f0.cpp:11:1: error: something went wrong\n" * 200,
        implicated_file_ids=[0],
        touched_lines={file_id: [10] for file_id in range(files)},
    )


def test_the_prompt_is_shrunk_to_fit(tmp_path: Path) -> None:
    context = _context(tmp_path, files=4)
    prompt = render(context, "context", context_lines=60, max_error_chars=8000, max_prompt_chars=6000)
    # the cap is honoured by dropping context, not by truncating mid-sentence
    assert len(prompt) <= 6000


def test_the_patches_are_never_dropped_to_make_the_prompt_fit(tmp_path: Path) -> None:
    """A file whose patch is missing cannot be reasoned about; the model would guess."""
    context = _context(tmp_path, files=3)
    prompt = render(context, "context", context_lines=60, max_error_chars=8000, max_prompt_chars=500)
    for file_id in range(3):
        assert "### File id " + str(file_id) in prompt


def test_source_windows_carry_absolute_line_numbers(tmp_path: Path) -> None:
    """The compiler's line numbers are only usable against a numbered listing."""
    context = _context(tmp_path)
    prompt = render(context, "context", context_lines=5, max_error_chars=8000, max_prompt_chars=0)
    assert "10  line 10" in prompt
    # and an elision marker where lines were left out
    assert "..." in prompt

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for the completion mode: finding the placeholders and holding the agent to replacing them."""

import os
from pathlib import Path
from typing import List

import pytest

from discopop_library.CodeGenerator.classes.UnpackedSuggestion import RECURSIVE_TASK_CUTOFF_MARKER
from discopop_library.PatchRepair.PatchRepairArguments import (
    MODE_COMPLETE,
    PROJECT_PROMPT_DIR_NAME,
    PatchRepairArguments,
)
from discopop_library.PatchRepair.completion import (
    describe_placeholders,
    placeholders_in_patch,
    placeholders_of,
    remaining_placeholders,
)
from discopop_library.PatchRepair.patching import check_pragmas_preserved
from discopop_library.PatchRepair.patchset import PatchEntry, PatchSet
from discopop_library.PatchRepair.prompts import (
    COMPLETION_LADDER,
    PromptContext,
    TEMPLATE_NAMES,
    load_template,
    output_contract,
    render,
    render_retry,
    template_for_attempt,
)

PATCH = (
    "--- a/fib.cpp\n"
    "+++ b/fib.cpp\n"
    "@@ -3,2 +3,3 @@\n"
    " long fib(int n) {\n"
    "+#pragma omp task shared(a)" + RECURSIVE_TASK_CUTOFF_MARKER + "\n"
    "   a = fib(n - 1);\n"
)
COMPLETED = PATCH.replace(RECURSIVE_TASK_CUTOFF_MARKER, " final(n <= 25)")


def _set(text: str) -> PatchSet:
    return PatchSet(suggestion_id=4, entries={1: PatchEntry(file_id=1, text=text, target=Path("fib.cpp"))})


def test_the_marker_of_the_generator_is_found_with_its_kind() -> None:
    found = placeholders_in_patch(PATCH, file_id=1)
    assert len(found) == 1
    assert found[0].kind == "recursive task cutoff"
    assert found[0].file_id == 1
    assert found[0].line.startswith("#pragma omp task shared(a)")
    assert "final(" in found[0].instruction


def test_a_marker_in_a_context_line_is_not_a_placeholder() -> None:
    """Only what the patch adds is the generator's; a comment that was already in the code stays."""
    context = PATCH.replace("+#pragma omp task shared(a)", " #pragma omp task shared(a)")
    assert placeholders_in_patch(context) == []


def test_an_unregistered_todo_marker_is_still_found() -> None:
    text = "+++ b/x.cpp\n+#pragma omp for /* DiscoPoP TODO: choose a schedule */\n"
    (found,) = placeholders_in_patch(text)
    assert found.kind == "other"
    assert found.instruction


def test_completed_patch_has_no_remaining_placeholder() -> None:
    assert remaining_placeholders(_set(COMPLETED)) is None
    assert placeholders_of(_set(COMPLETED)) == []


def test_a_kept_marker_is_rejected_with_a_message_for_the_agent() -> None:
    message = remaining_placeholders(_set(PATCH))
    assert message is not None
    assert "file id 1" in message
    assert "DiscoPoP TODO" in message


def test_adding_the_clause_keeps_the_directive() -> None:
    """The pragma gate must accept the very change completion asks for."""
    assert check_pragmas_preserved(_set(PATCH), _set(COMPLETED)) is None


def test_the_description_names_what_to_do_once_per_kind() -> None:
    both = placeholders_in_patch(PATCH, 1) + placeholders_in_patch(PATCH, 2)
    text = describe_placeholders(both)
    assert text.count("What to do for recursive task cutoff") == 1
    assert "file id 2" in text
    assert describe_placeholders([]) == "(none)"


def test_every_template_has_a_file() -> None:
    for name in TEMPLATE_NAMES:
        assert not load_template(name).lstrip().startswith("<!--")


def test_the_completion_templates_show_the_original_source_and_the_placeholders() -> None:
    template = load_template(COMPLETION_LADDER[0])
    for part in ("{original_source}", "{placeholders}", "{patch_blocks}", "{output_contract}"):
        assert part in template


def test_the_completion_prompt_is_rendered_with_its_own_contract() -> None:
    placeholders = placeholders_of(_set(PATCH))
    context = PromptContext(
        suggestion_id=4,
        pattern_type="task",
        patch_set=_set(PATCH),
        original_sources={1: "long fib(int n) {\n  a = fib(n - 1);\n}\n"},
        placeholders=describe_placeholders(placeholders),
        mode=MODE_COMPLETE,
    )
    prompt = render(context, template_for_attempt(1, mode=MODE_COMPLETE), 60, 8000, 60000)
    assert "recursive task cutoff" in prompt
    assert "No placeholder may remain" in prompt
    assert "{" + "placeholders" + "}" not in prompt
    assert "fix the error" not in output_contract([1], MODE_COMPLETE)
    retry = render_retry("it failed", [1], mode=MODE_COMPLETE)
    assert "completed patch" in retry and "No placeholder may remain" in retry


def test_the_repair_contract_is_unchanged_by_the_mode_argument() -> None:
    assert "No placeholder may remain" not in output_contract([1])
    assert "Prefer correcting the directive's clauses" in output_contract([1])


def _dot_dp(tmp_path: Path) -> Path:
    """The files PatchRepairArguments insists on."""
    dot_dp = tmp_path / "project" / ".discopop"
    configs = dot_dp / "project" / "configs"
    (configs / "tiny").mkdir(parents=True)
    (dot_dp / "explorer").mkdir()
    (dot_dp / "patch_generator").mkdir()
    for name in ("FileMapping.txt", "line_mapping.json"):
        (dot_dp / name).write_text("")
    (configs / "seq_settings.json").write_text("{}")
    (configs / "tiny" / "execute.sh").write_text("")
    (configs / "tiny" / "compile.sh").write_text("")
    (configs / "compile.sh").write_text("")
    return dot_dp


def _arguments(dot_dp: Path, **kwargs: object) -> PatchRepairArguments:
    return PatchRepairArguments(
        log_level="WARNING", write_log=False, dot_dp_path=str(dot_dp), configuration="tiny", **kwargs  # type: ignore
    )


def test_an_unknown_mode_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown mode"):
        _arguments(_dot_dp(tmp_path), mode="polish")


def test_the_project_prompt_directory_is_used_when_it_exists(tmp_path: Path) -> None:
    dot_dp = _dot_dp(tmp_path)
    assert _arguments(dot_dp).prompt_dir is None
    prompts = dot_dp / "patch_repair" / PROJECT_PROMPT_DIR_NAME
    prompts.mkdir(parents=True)
    assert _arguments(dot_dp).prompt_dir == str(prompts)
    # an explicit directory wins
    assert _arguments(dot_dp, prompt_dir="/elsewhere").prompt_dir == "/elsewhere"


def test_a_project_template_replaces_only_the_built_in_one_of_its_name(tmp_path: Path) -> None:
    (tmp_path / "completion.md").write_text("<!-- license -->\nMy own words {placeholders}")
    assert load_template("completion", str(tmp_path)) == "My own words {placeholders}"
    assert load_template("minimal", str(tmp_path)) == load_template("minimal")
    assert os.path.exists(str(tmp_path / "completion.md"))


def test_an_accepted_completion_is_recorded_as_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The turn loop is shared with repair; the status is what tells the two apart."""
    from discopop_library.PatchRepair import loop as repair_loop
    from discopop_library.PatchRepair.results import STATUS_COMPLETED, STATUS_FAILED, ProgressReporter, SuggestionRecord

    arguments = PatchRepairArguments.__new__(PatchRepairArguments)
    arguments.mode = MODE_COMPLETE
    arguments.prompts, arguments.retries, arguments.max_attempts, arguments.agent_error_retries = 1, 0, 6, 0
    arguments.prompt_dir = None
    arguments.context_lines, arguments.max_error_chars, arguments.max_prompt_chars = 60, 8000, 60000
    arguments.patch_repair_path = ""
    templates: List[str] = []

    def fake_render(_context: PromptContext, template: str, **_kwargs: object) -> str:
        templates.append(template)
        return "prompt"

    monkeypatch.setattr(repair_loop, "render", fake_render)
    monkeypatch.setattr(repair_loop, "_one_turn", lambda *a, **k: (True, "", object(), True))
    monkeypatch.setattr(repair_loop, "_attempt_dir", lambda *a, **k: "")
    monkeypatch.setattr(repair_loop, "_write_back", lambda *a, **k: None)

    class _Module:
        def new_session_id(self) -> None:
            return None

    reporter = ProgressReporter()
    monkeypatch.setattr(reporter, "_emit", lambda _obj: None)
    record = SuggestionRecord(suggestion_id=4, hotspot_type="yes", status=STATUS_FAILED)
    patch_set = _set(PATCH)
    context = PromptContext(suggestion_id=4, pattern_type="task", patch_set=patch_set, mode=MODE_COMPLETE)
    repair_loop._run_turns(arguments, context, patch_set, record, _Module(), {}, reporter, 4)
    assert record.status == STATUS_COMPLETED
    assert templates == ["completion"]

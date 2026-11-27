# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from discopop_library.ProjectManager.services import suggestion_check_view as view
from discopop_library.SuggestionCheck.check import STATE_APPROVED, STATE_FAILED, STATE_REJECTED, Outcome
from discopop_library.SuggestionCheck.answers import Justification
from discopop_library.SuggestionCheck.publish import MARKER_FILE, PublishResult
from discopop_library.SuggestionCheck.results import Results
from discopop_library.SuggestionCheck.unsure import Fingerprint, load_unsure_suggestions

BLOCKER = {
    "type": "RAW",
    "source_line": "1:12",
    "sink_line": "1:11",
    "origin": "profiled",
    "accesses": [{"variable": "seed", "memory_region": "MR1"}, {"variable": "seed"}, {"memory_region": "x"}],
}


def write_unsure(dot_dp: Path, ids: List[int]) -> None:
    (dot_dp / "explorer").mkdir(parents=True, exist_ok=True)
    suggestions = [
        {
            "pattern_id": i,
            "type": "do_all",
            "start_line": "1:" + str(10 + i),
            "end_line": "1:" + str(10 + i),
            "region": {"file_id": 1, "end_line": 30 + i},
            "pragma": "#pragma omp parallel for",
            "blockers": [BLOCKER],
        }
        for i in ids
    ]
    (dot_dp / "explorer" / "unsure_suggestions.json").write_text(
        json.dumps({"format_version": 1, "suggestions": suggestions})
    )


@pytest.fixture
def dot_dp(tmp_path: Path) -> Path:
    dot = tmp_path / ".discopop"
    dot.mkdir()
    (dot / "FileMapping.txt").write_text("1\t/project/src/main.cpp\n2\t/project/src/util.cpp\n")
    write_unsure(dot, [3, 12])
    return dot


def record_real_results(dot_dp: Path, run_info: Optional[Dict[str, Any]] = None) -> None:
    """results.json as the check writes it: one approval with a patch, one unsure, one failed."""
    unsure = {s.pattern_id: s for s in load_unsure_suggestions(str(dot_dp))}
    results = Results(
        str(dot_dp / "suggestion_check"),
        Fingerprint.of(str(dot_dp / "explorer" / "unsure_suggestions.json")),
        run_info if run_info is not None else {"review": True, "backend": "claude", "model": "sonnet"},
    )
    patch = SimpleNamespace(entries={1: SimpleNamespace(text="--- a/main.cpp\n+++ b/main.cpp\n+#pragma omp\n")})
    approved = Outcome(
        3,
        STATE_APPROVED,
        verdict="approved",
        assumption="the order of the seeds does not matter",
        justifications=[Justification(1, "each iteration draws its own number", ["main.cpp:12"])],
        result_differences="rounding",
        review={"verdict": "agree", "reason": "fine"},
        patch=patch,  # type: ignore[arg-type]
        calls=2,
        tool_calls=7,
    )
    results.record(unsure[3], approved)
    results.record(unsure[12], Outcome(12, STATE_REJECTED, verdict="unsure", reason="cannot tell"))
    results.close()


def test_the_results_of_the_check_are_read(dot_dp: Path) -> None:
    record_real_results(dot_dp)
    records = view.load_results(str(dot_dp))
    assert records is not None and sorted(records) == ["12", "3"]
    rows = view.result_rows(records, view.read_file_mapping(str(dot_dp)))
    assert [row.cells() for row in rows] == [
        ("3", "main.cpp:13", "Approved", "rounding", "7", "agree", "sonnet", ""),
        ("12", "main.cpp:22", "Unsure", "", "0", "", "sonnet", ""),
    ]
    assert [row.tone for row in rows] == [view.TONE_OK, view.TONE_STOP]
    assert not view.results_are_stale(str(dot_dp))
    assert view.approved_patch_files(str(dot_dp), "3") == ["1"]
    assert "+#pragma omp" in view.patch_text(str(dot_dp), "3", "1", records["3"])


def test_a_new_explorer_run_makes_the_results_stale(dot_dp: Path) -> None:
    record_real_results(dot_dp)
    assert not view.results_are_stale(str(dot_dp))
    write_unsure(dot_dp, [3, 12, 40])
    assert view.results_are_stale(str(dot_dp))
    os.remove(dot_dp / "explorer" / "unsure_suggestions.json")
    assert view.results_are_stale(str(dot_dp))


def test_no_or_unreadable_results(dot_dp: Path) -> None:
    assert view.load_results(str(dot_dp)) is None
    assert not view.results_are_stale(str(dot_dp))
    (dot_dp / "suggestion_check").mkdir()
    (dot_dp / "suggestion_check" / "results.json").write_text("{broken")
    assert view.load_results(str(dot_dp)) is None
    (dot_dp / "suggestion_check" / "results.json").write_text(json.dumps({"suggestions": {"1": {}}}))
    assert view.load_results(str(dot_dp)) is None
    assert view.records_of({"suggestions": [{"pattern_id": 2}, "x", {"no": 1}]}) == {"2": {"pattern_id": 2}}


def test_the_states(dot_dp: Path) -> None:
    assert view.state_display({"state": STATE_APPROVED}) == ("Approved", view.TONE_OK)
    assert view.state_display({"state": STATE_REJECTED, "verdict": "rejected"}) == ("Rejected", view.TONE_IDLE)
    # the review disagreed: the agent approved, the suggestion is rejected
    assert view.state_display({"state": STATE_REJECTED, "verdict": "approved"}) == ("Rejected", view.TONE_IDLE)
    assert view.state_display({"state": STATE_REJECTED, "verdict": "unsure"}) == ("Unsure", view.TONE_STOP)
    assert view.state_display({"state": STATE_FAILED}) == ("Error", view.TONE_FAIL)
    assert view.state_display({"state": "new"}) == ("new", view.TONE_IDLE)
    assert view.state_display({}) == ("unknown", view.TONE_IDLE)


def test_the_review_verdict() -> None:
    assert view.review_verdict({"review": {"verdict": "disagree"}}) == "disagree"
    # the run setting stored with every entry (review on / off) can stand where the review is
    assert view.review_verdict({"review": False, "state": STATE_APPROVED}) == "off"
    assert view.review_verdict({"review": True, "state": STATE_APPROVED}) == "agree"
    assert view.review_verdict({"review": True, "state": STATE_REJECTED, "reason": "the review disagreed: x"}) == (
        "disagree"
    )
    assert view.review_verdict({"state": STATE_REJECTED, "reason": "the review gave no usable answer"}) == "no answer"
    assert view.review_verdict({"review": True, "state": STATE_REJECTED, "reason": "no"}) == ""


def test_the_model_cost_and_location_columns() -> None:
    rows = view.result_rows(
        {
            "1": {"state": STATE_FAILED, "backend": "opencode", "start_line": "9:4", "cost": 0.5},
            "2": {"state": STATE_FAILED, "start_line": "bad"},
        },
        {},
        published=["1"],
    )
    assert rows[0].cells() == ("1", "9:4", "Error (in use)", "", "0", "", "opencode (default)", "$0.5000")
    assert rows[1].location == "bad" and rows[1].cost == ""
    assert view.has_cost(rows) and not view.has_cost(rows[1:])
    assert view.cost_text({"cost": True}) == ""
    assert view.location_text("", {}) == "" and view.location_text("x:1", {1: "a"}) == "x:1"


def test_the_preferred_row() -> None:
    rows = view.result_rows({"1": {"state": STATE_FAILED}, "2": {"state": STATE_APPROVED}}, {})
    assert view.preferred_row(rows, None) == "2"
    assert view.preferred_row(rows, "1") == "1"
    assert view.preferred_row(rows[:1], "9") == "1"
    assert view.preferred_row([], "1") is None


def test_the_unsure_suggestions_and_the_scope(dot_dp: Path) -> None:
    unsure = view.load_unsure(str(dot_dp))
    assert sorted(unsure) == ["12", "3"] and unsure["3"].start_line == "1:13" and len(unsure["3"].blockers) == 1
    assert view.unsure_ids(str(dot_dp)) == ["3", "12"]
    assert view.has_unsure_suggestions(str(dot_dp))
    available = ["3", "12", "13"]
    assert view.parse_scope("  ", available) is None
    # ranges are expanded, unknown ids are left out: the check refuses them
    assert view.parse_scope("12-20, 3, 99, x", available) == ("3", "12", "13")
    assert view.parse_scope("99", available) == ()
    assert view.scope_text(None, available) == "All 3 unsure suggestion(s): 3, 12, 13"
    assert view.scope_text(("3",), available) == "1 of 3 selected: 3"
    assert view.scope_text((), available).startswith("None of the available")
    assert view.scope_text(None, []).startswith("No unsure suggestions")


def test_unreadable_unsure_suggestions(tmp_path: Path) -> None:
    assert view.load_unsure(str(tmp_path)) == {} and not view.has_unsure_suggestions(str(tmp_path))
    (tmp_path / "explorer").mkdir()
    (tmp_path / "explorer" / "unsure_suggestions.json").write_text(json.dumps({"suggestions": [1, {"x": 1}]}))
    assert view.load_unsure(str(tmp_path)) == {}


def test_the_details_of_an_approval(dot_dp: Path) -> None:
    record_real_results(dot_dp)
    records = view.load_results(str(dot_dp))
    assert records is not None
    mapping = view.read_file_mapping(str(dot_dp))
    unsure = view.load_unsure(str(dot_dp))
    text = view.detail_text("3", records["3"], unsure["3"], mapping, {"assumption": "a"})
    assert text.startswith("Suggestion 3: Approved\nLoop: main.cpp:13 to line 33")
    assert "Directive without the blockers: #pragma omp parallel for" in text
    assert "In use: published to patch_generator/3" in text
    assert view.AGENT_NOTE in text
    assert "Assumption: the order of the seeds does not matter" in text
    assert "Result differences: rounding" in text
    assert "  Blocker 1: RAW dependency main.cpp:12 -> main.cpp:11 on seed (profiled)" in text
    assert "    each iteration draws its own number\n    Evidence: main.cpp:12" in text
    assert "Agent calls: 2 (unanswered: 0), tool calls: 7" in text
    assert "Agent: claude / sonnet" in text


def test_the_details_of_a_rejection() -> None:
    record = {
        "state": STATE_FAILED,
        "reason": "no usable answer",
        "review": {"verdict": "disagree", "reason": "races"},
        "read_blocker_files": False,
        "gates": [{"attempt": 1, "turn": 0, "detail": "bad json"}, {"review_turn": 1, "detail": "unreadable"}],
    }
    unsure = view.UnsureEntry("4", blockers=(BLOCKER,))
    text = view.detail_text("4", record, unsure, {1: "/a/m.cpp"})
    assert text.startswith("Suggestion 4: Error\n\nReason: no usable answer")
    assert "Blockers:\n  1. RAW dependency m.cpp:12 -> m.cpp:11 on seed (profiled)" in text
    assert "Review: disagree - races" in text
    assert "Opened the files of the blockers: no" in text
    assert "  [attempt 1, turn 0] bad json\n  [review_turn 1] unreadable" in text
    assert view.detail_text(None, None, None, {}) == "(select a suggestion in the Results tab)"
    assert "Reason: (none given)" in view.detail_text("5", {"state": STATE_REJECTED, "review": False}, None, {})


def test_the_assumption_line() -> None:
    records: Dict[str, Dict[str, Any]] = {
        "1": {"state": STATE_APPROVED, "assumption": "A", "result_differences": "rounding"},
        "2": {"state": STATE_APPROVED, "result_differences": "none"},
        "3": {"state": STATE_REJECTED},
    }
    assert view.assumption_text(records, ["1", "2", "3"]) == (
        "Rests on the agent's assumption - 1: A [results may differ by rounding]; 2: (none stated)"
    )
    assert view.assumption_text(records, ["3"]).startswith("Select an approved suggestion")


def test_the_transcript_files_in_call_order(tmp_path: Path) -> None:
    directory = tmp_path / "suggestion_check" / "transcripts" / "5"
    directory.mkdir(parents=True)
    names = [
        "review_0_answer.txt",
        "check_2_0_prompt.txt",
        "check_1_10_prompt.txt",
        "check_1_0_tools.txt",
        "check_1_0_answer.txt",
        "check_1_0_prompt.txt",
        "check_1_0_events.jsonl",
        "check_1_2_prompt.txt",
        "review_0_prompt.txt",
    ]
    for name in names:
        (directory / name).write_text(name)
    assert view.transcript_files(str(tmp_path), "5") == [
        "check_1_0_prompt.txt",
        "check_1_0_answer.txt",
        "check_1_0_tools.txt",
        "check_1_2_prompt.txt",
        "check_1_10_prompt.txt",
        "check_2_0_prompt.txt",
        "review_0_prompt.txt",
        "review_0_answer.txt",
    ]
    assert view.transcript_text(str(tmp_path), "5", "review_0_answer.txt") == "review_0_answer.txt"
    assert view.transcript_text(str(tmp_path), "5", "") == "(no transcript recorded for suggestion 5)"
    assert view.transcript_text(str(tmp_path), "5", "gone.txt") == "(cannot be read)"
    assert view.transcript_text(str(tmp_path), None, "") == "(select a suggestion in the Results tab)"
    assert view.transcript_files(str(tmp_path), "6") == []


def test_the_patch_texts(tmp_path: Path) -> None:
    assert view.patch_text(str(tmp_path), None, "", None) == "(select a suggestion in the Results tab)"
    assert view.patch_text(str(tmp_path), "2", "", {"state": STATE_REJECTED}) == (
        "(suggestion 2 was not approved, so it has no patch)"
    )
    assert view.patch_text(str(tmp_path), "2", "", {"state": STATE_APPROVED}) == (
        "(no patch files found for suggestion 2)"
    )
    assert view.patch_text(str(tmp_path), "2", "0", None) == "(no patch found)"


def test_the_publish_and_withdraw_plans() -> None:
    records: Dict[str, Dict[str, Any]] = {
        "1": {"state": STATE_APPROVED},
        "2": {"state": STATE_REJECTED},
        "10": {"state": STATE_APPROVED},
    }
    assert view.approved_ids(records) == ["1", "10"]
    assert view.publish_plan(records, ["10", "2"]) == view.PublishPlan(["10"], "Use approved suggestion 10")
    assert view.publish_plan(records, ["1", "10"]).label == "Use approved suggestions 1, 10"
    assert view.publish_plan(records, ["2"]) == view.PublishPlan(["1", "10"], "Use all approved suggestions (2)")
    assert view.publish_plan({}, []) == view.PublishPlan([], "Use approved suggestions")
    assert view.withdraw_plan(["1", "10"], ["10"]) == view.PublishPlan(["10"], "Withdraw 10")
    assert view.withdraw_plan(["1", "10"], ["2"]) == view.PublishPlan(["1", "10"], "Withdraw all (2)")
    assert view.withdraw_plan([], ["2"]) == view.PublishPlan([], "Withdraw")


def test_publishing_and_withdrawing(dot_dp: Path) -> None:
    record_real_results(dot_dp)
    result = view.publish(str(dot_dp), ["3", "12"])
    assert result.published == [3] and result.skipped == {12: "not approved"}
    assert (dot_dp / "patch_generator" / "3" / MARKER_FILE).is_file()
    assert view.published_suggestions(str(dot_dp)) == ["3"]
    marker = view.marker(str(dot_dp), "3")
    assert marker is not None and marker["assumption"] == "the order of the seeds does not matter"
    assert view.marker(str(dot_dp), "12") is None and view.marker(str(dot_dp), "x") is None
    assert view.withdraw(str(dot_dp), ["3"]) == ["3"]
    assert view.published_suggestions(str(dot_dp)) == []


def test_the_publish_messages() -> None:
    assert view.publish_message(PublishResult()) == "Nothing to publish."
    message = view.publish_message(PublishResult([3, 4], {7: "not approved"}))
    assert message.startswith("Now in use: 3, 4. ")
    assert message.endswith("\nNot used 7: not approved")
    text = view.confirm_publish_text({"3": {"assumption": "A", "result_differences": "rounding"}, "4": {}}, ["3", "4"])
    assert view.AGENT_NOTE in text
    assert "3: A\n   The results may differ from the sequential program by rounding.\n4: (no assumption stated)" in text


def write_llm_config(dot_dp: Path, content: str) -> None:
    (dot_dp / "patch_repair").mkdir(exist_ok=True)
    (dot_dp / "patch_repair" / "llm_config.json").write_text(content)


def test_the_stored_connections(dot_dp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCOPOP_PATCH_REPAIR_LLM_CONFIG", raising=False)
    assert view.llm_config_path(str(dot_dp)) == str(dot_dp / "patch_repair" / "llm_config.json")
    # no configuration: only choosing in the panel
    assert view.load_connections(str(dot_dp)) == ([], "")
    assert view.connection_choices([]) == [view.NO_CONNECTION]
    write_llm_config(
        dot_dp,
        json.dumps(
            {
                "connections": {
                    "fast": {"backend": "claude", "model": "haiku"},
                    "local": {"backend": "opencode"},
                    "odd": {"backend": "nonexistent"},
                }
            }
        ),
    )
    names, error = view.load_connections(str(dot_dp))
    assert names == ["fast", "local", "odd"] and error == ""
    assert view.connection_choices(names) == [view.NO_CONNECTION, "fast", "local", "odd"]
    assert view.resolve_connection(str(dot_dp), "fast") == view.ConnectionInfo(
        "claude", "haiku", "fast: claude / haiku"
    )
    assert view.resolve_connection(str(dot_dp), "local") == view.ConnectionInfo(
        "opencode", "", "local: opencode / (backend default)"
    )
    assert view.resolve_connection(str(dot_dp), "odd").error.startswith("Unknown backend: nonexistent")
    assert view.resolve_connection(str(dot_dp), "gone").error.startswith("Unknown LLM connection: gone")


def test_an_unreadable_llm_configuration(dot_dp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DISCOPOP_PATCH_REPAIR_LLM_CONFIG", raising=False)
    write_llm_config(dot_dp, "{broken")
    names, error = view.load_connections(str(dot_dp))
    assert names == [] and error.startswith("Could not read the LLM configuration")
    assert view.resolve_connection(str(dot_dp), "x").error.startswith("Could not read")


def test_the_backend_description_and_the_budget() -> None:
    assert view.backend_description("1.2", "Agent.\nMore") == "1.2 -- Agent."
    assert view.backend_description("", "Agent.") == "Agent."
    assert view.budget_text(2, 2, True) == (
        "At most 2 x (1 + 2) = 6 agent calls per suggestion, plus up to 3 for the review."
    )
    assert view.budget_text(3, 0, False) == "At most 3 x (1 + 0) = 3 agent calls per suggestion."


def test_the_progress_summaries() -> None:
    assert view.progress_summary({"event": "start", "suggestions": [1, 2]}, 0) == [
        ("Checking 2 unsure suggestion(s)...", view.TONE_BUSY)
    ]
    assert view.progress_summary({"event": "check", "pattern_id": 7}, 2) == [
        ("Checking suggestion 7 (of 2)...", view.TONE_BUSY)
    ]
    assert view.progress_summary({"event": "done", "pattern_id": 7}, 2) == []
    [(text, tone)] = view.progress_summary({"event": "end", "counts": {"approved": 1, "rejected": 2}}, 3)
    assert text.startswith("1 approved, 2 rejected, 0 without an answer. ") and tone == view.TONE_OK
    assert view.progress_summary({"event": "end", "counts": {"rejected": 1}}, 1)[0][1] == view.TONE_IDLE
    assert view.progress_summary({"event": "end", "counts": {"failed": 1}}, 1)[0][1] == view.TONE_FAIL
    [(text, tone)] = view.progress_summary({"event": "aborted", "reason": "main.cpp changed"}, 1)
    assert text == "Aborted: the project changed during the check. main.cpp changed" and tone == view.TONE_FAIL
    assert view.progress_summary({}, 0) == []


def test_choosing_backend_and_model_with_stored_connections() -> None:
    assert view.manual_choice_problem([]) == "" and view.manual_choice_problem(["a"]) == ""
    assert view.manual_choice_problem(["a", "b"]).startswith("Several connections are stored")
    assert view.manual_choice_note([]).startswith("Stored connections are shared with patch repair")
    assert view.manual_choice_note(["a"]) == (
        "The backend and the model below override those of the only stored connection, a; its other settings "
        "apply, an empty model is its model."
    )

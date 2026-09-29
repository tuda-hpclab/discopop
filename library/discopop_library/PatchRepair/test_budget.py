# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for what the repair budget is allowed to be spent on.

``--prompts`` x ``--retries`` bounds how many times a *model* is asked. A call that
never produced an answer -- an unreachable provider, a server error, no response within
the timeout -- costs no tokens and gives the model no chance, so it must not consume
that budget: a flaky endpoint would otherwise spend the whole allowance without the
model ever seeing the prompt, and the suggestion would be recorded as one a model could
not repair. Observed in practice: 4 of 6 attempts lost to ``UnknownError: Unexpected
server error`` on a run that reported "not repaired".

The turn loop is driven here through a stubbed ``_one_turn``, so these tests pin the
accounting without invoking an agent.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from discopop_library.PatchRepair import loop as repair_loop
from discopop_library.PatchRepair.PatchRepairArguments import PatchRepairArguments
from discopop_library.PatchRepair.patchset import PatchEntry, PatchSet
from discopop_library.PatchRepair.prompts import PromptContext
from discopop_library.PatchRepair.results import (
    STATUS_FAILED,
    STATUS_REPAIRED,
    STATUS_UNREACHABLE,
    ProgressReporter,
    SuggestionRecord,
)

ANSWERED = True
UNANSWERED = False


def _arguments(
    prompts: int = 2, retries: int = 2, max_attempts: int = 6, agent_error_retries: int = 2
) -> PatchRepairArguments:
    """A budget, without the project the real constructor validates.

    Built through ``__new__`` like ``patching._diff_arguments`` does: ``__post_init__``
    checks for a .discopop directory with patches in it, and the turn loop reads none
    of that.
    """
    arguments = PatchRepairArguments.__new__(PatchRepairArguments)
    arguments.prompts = prompts
    arguments.retries = retries
    arguments.max_attempts = max_attempts
    arguments.agent_error_retries = agent_error_retries
    arguments.patch_repair_path = ""
    arguments.prompt_dir = None
    arguments.context_lines = 60
    arguments.max_error_chars = 8000
    arguments.max_prompt_chars = 60000
    return arguments


class _Recorder:
    """Collects the outcomes the loop asks for, and replays a scripted answer."""

    def __init__(self, script: List[Tuple[bool, bool]]):
        # (answered, accepted) per call, in order
        self.script = list(script)
        self.calls = 0

    def turn(self, *args: Any, **kwargs: Any) -> Tuple[bool, str, Optional[object], bool]:
        answered, accepted = self.script[self.calls] if self.calls < len(self.script) else (UNANSWERED, False)
        self.calls += 1
        if accepted:
            return True, "", object(), True
        return False, "rejected", None, answered


@pytest.fixture
def stubbed(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Run ``repair_suggestion``'s turn loop against a scripted ``_one_turn``."""

    def run(script: List[Tuple[bool, bool]], **argument_overrides: int) -> Dict[str, Any]:
        arguments = _arguments(**argument_overrides)
        recorder = _Recorder(script)
        monkeypatch.setattr(repair_loop, "_one_turn", recorder.turn)
        monkeypatch.setattr(repair_loop, "_attempt_dir", lambda *a, **k: "")
        monkeypatch.setattr(repair_loop, "_session_after", lambda *a, **k: "session")
        monkeypatch.setattr(repair_loop, "render_retry", lambda *a, **k: "retry")
        monkeypatch.setattr(repair_loop, "_write_back", lambda *a, **k: None)
        patch_set = _patch_set()
        record = SuggestionRecord(suggestion_id=1, hotspot_type="yes", status=STATUS_FAILED)
        reporter = ProgressReporter()
        # The reporter prints its events to stdout; a unit test has no consumer for
        # them and they would bury pytest's own output.
        monkeypatch.setattr(reporter, "_emit", lambda _obj: None)
        repair_loop._run_turns(
            arguments,
            PromptContext(suggestion_id=1, pattern_type="do_all", patch_set=patch_set),
            patch_set,
            record,
            _StubModule(),
            {},
            reporter,
            1,
        )
        return {"record": record, "calls": recorder.calls}

    return run


def _patch_set() -> PatchSet:
    """A one-file patch set; its contents never matter, only that it is non-empty."""
    return PatchSet(
        suggestion_id=1,
        entries={1: PatchEntry(file_id=1, text="", target=Path("code.cpp"))},
    )


class _StubModule:
    @staticmethod
    def new_session_id() -> str:
        return "new"


def test_an_unanswered_call_does_not_consume_a_prompt(stubbed: Any) -> None:
    """Two dead calls, then a good one: the fix is found, not lost to the budget."""
    result = stubbed([(UNANSWERED, False), (UNANSWERED, False), (ANSWERED, True)], prompts=1, retries=0)
    record = result["record"]
    assert record.status == STATUS_REPAIRED
    # three calls were made, two of which never reached the model
    assert result["calls"] == 3
    assert record.attempts == 3
    assert record.unanswered == 2


def test_answered_rejections_still_consume_the_budget(stubbed: Any) -> None:
    """A model that answers badly gets exactly the agreed number of chances."""
    result = stubbed([(ANSWERED, False)] * 10, prompts=2, retries=1)
    assert result["calls"] == 4  # 2 prompts x (1 + 1 retry)
    assert result["record"].status == STATUS_FAILED
    assert result["record"].unanswered == 0


def test_the_allowance_bounds_a_dead_agent(stubbed: Any) -> None:
    """An endpoint that never answers ends the suggestion instead of looping."""
    result = stubbed([(UNANSWERED, False)] * 50, prompts=3, retries=2, agent_error_retries=2)
    # the allowance is spent, plus the call that exceeds it
    assert result["calls"] == 3
    assert result["record"].status == STATUS_UNREACHABLE


def test_an_unreachable_agent_is_not_reported_as_a_failed_repair(stubbed: Any) -> None:
    """The distinction the whole change exists for.

    STATUS_FAILED says a model was asked and could not fix the patch. Reporting an
    outage that way measures nothing and reads as a measurement of the model.
    """
    result = stubbed([(UNANSWERED, False)] * 10, agent_error_retries=0)
    assert result["record"].status == STATUS_UNREACHABLE
    assert result["record"].status != STATUS_FAILED


def test_the_allowance_is_shared_across_prompts(stubbed: Any) -> None:
    """One dead call per prompt still ends the run once the allowance is gone.

    The allowance is per suggestion, not per prompt: an agent failing intermittently
    across several prompts is the same outage as one failing repeatedly within one.
    """
    script = [(UNANSWERED, False), (ANSWERED, False), (UNANSWERED, False), (ANSWERED, False)]
    result = stubbed(script, prompts=3, retries=0, agent_error_retries=1)
    # call 1 dead (allowance 1/1), call 2 answered+rejected, call 3 dead (over allowance)
    assert result["calls"] == 3
    assert result["record"].status == STATUS_UNREACHABLE
    assert result["record"].unanswered == 2

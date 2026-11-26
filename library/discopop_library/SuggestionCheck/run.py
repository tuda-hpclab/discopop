# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""discopop_suggestion_check: checks the unsure suggestions of the explorer with an LLM agent."""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from typing import Any, Callable, Dict, List, Optional

from discopop_library.PatchRepair import llm_backends, llm_config
from discopop_library.PathManagement.PathManagement import load_file_mapping
from discopop_library.SuggestionCheck.SuggestionCheckArguments import SuggestionCheckArguments
from discopop_library.SuggestionCheck.check import STATE_FAILED, Agent, AgentReply, Budget, Outcome, check_suggestion
from discopop_library.SuggestionCheck.facts import SourceFiles
from discopop_library.SuggestionCheck.results import Results
from discopop_library.SuggestionCheck.unsure import (
    UNSURE_SUGGESTIONS_FILE,
    Fingerprint,
    UnsureSuggestion,
    UnsureSuggestionsError,
    load_plain_patch,
    load_unsure_suggestions,
)

logger = logging.getLogger("SuggestionCheck")

# makes the agents for one run: the checking agent and the reviewer
AgentFactory = Callable[[], Agent]


def backend_agent(profile: Dict[str, Any], timeout: float) -> Agent:
    """an agent which drives the backend of profile. Without tools for now: it runs in an empty directory, never in
    the project, and gets everything in the prompt (design/agent_checked_suggestions.md, §5.2)."""
    module = llm_backends.for_profile(profile)

    def ask(prompt: str, session: Optional[str]) -> AgentReply:
        new_session = None if session else module.new_session_id()
        sandbox = tempfile.mkdtemp(prefix="discopop_suggestion_check_agent_")
        try:
            invocation = llm_backends.run_agent(
                module, profile, prompt, cwd=sandbox, timeout=timeout, session=session, new_session=new_session
            )
        finally:
            shutil.rmtree(sandbox, ignore_errors=True)
        return AgentReply(
            text=invocation.text,
            answered=invocation.ok,
            failure=invocation.failure_reason(),
            session=session or invocation.session_id or new_session,
        )

    return ask


def _select(suggestions: List[UnsureSuggestion], arguments: SuggestionCheckArguments) -> List[UnsureSuggestion]:
    ids = arguments.suggestion_ids()
    if ids is not None:
        known = {s.pattern_id for s in suggestions}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise UnsureSuggestionsError("not an unsure suggestion: " + ", ".join(str(i) for i in unknown))
        suggestions = [s for s in suggestions if s.pattern_id in ids]
    if arguments.max_suggestions:
        suggestions = suggestions[: arguments.max_suggestions]
    return suggestions


def run(arguments: SuggestionCheckArguments, agent_factory: Optional[AgentFactory] = None) -> int:
    dot = os.path.abspath(arguments.dot_dp_path)
    try:
        suggestions = _select(load_unsure_suggestions(dot), arguments)
    except UnsureSuggestionsError as error:
        logger.error(str(error))
        print(str(error))
        return 1
    files = SourceFiles(load_file_mapping(os.path.join(dot, "FileMapping.txt")), os.path.dirname(dot))

    run_info: Dict[str, Any] = {"review": arguments.review, "verify": arguments.verify}
    if agent_factory is None:
        config = llm_config.load_config(
            arguments.llm_config or llm_config.default_config_path(arguments.patch_repair_path)
        )
        profile = llm_config.resolve_connection(
            config, name=arguments.connection, backend_override=arguments.backend, model_override=arguments.model
        )
        run_info["backend"] = llm_backends.backend_of(profile)
        run_info["model"] = profile.get("model")

        def agent_factory() -> Agent:
            return backend_agent(profile, arguments.agent_timeout)

    budget = Budget(arguments.prompts, arguments.retries, arguments.agent_error_retries)
    results = Results(
        arguments.suggestion_check_path, Fingerprint.of(os.path.join(dot, UNSURE_SUGGESTIONS_FILE)), run_info
    )
    counts: Dict[str, int] = dict()
    try:
        results.progress("start", suggestions=[s.pattern_id for s in suggestions])
        for suggestion in suggestions:
            results.progress("check", pattern_id=suggestion.pattern_id)
            try:
                plain = load_plain_patch(dot, suggestion.pattern_id, files.file_mapping)
            except FileNotFoundError:
                outcome = Outcome(suggestion.pattern_id, STATE_FAILED, reason="no plain patch; run the patch generator")
            else:
                outcome = check_suggestion(
                    suggestion,
                    plain,
                    files,
                    agent_factory(),
                    agent_factory() if arguments.review else None,
                    budget,
                    results.transcripts_dir(suggestion.pattern_id),
                )
            results.record(suggestion, outcome)
            counts[outcome.state] = counts.get(outcome.state, 0) + 1
            results.progress("done", pattern_id=suggestion.pattern_id, state=outcome.state, reason=outcome.reason)
        results.progress("end", counts=counts)
    finally:
        results.close()
    print(
        "Checked "
        + str(len(suggestions))
        + " unsure suggestion(s): "
        + ", ".join(str(n) + " " + state for state, n in sorted(counts.items()))
        + ". Approvals rest on the agent's assumptions; see "
        + os.path.join(arguments.suggestion_check_path, "results.json")
    )
    # rejections are results, not errors
    return 0

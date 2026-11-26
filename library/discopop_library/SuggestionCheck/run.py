# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""discopop_suggestion_check: checks the unsure suggestions of the explorer with an LLM agent."""

from __future__ import annotations

import copy
import json
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


# the agent gets no tools: everything it may use is in the prompt (design/agent_checked_suggestions.md, §5.2)
_CLAUDE_NO_TOOLS = ["--tools", "", "--strict-mcp-config", "--restricted"]
_OPENCODE_DENY_ALL = json.dumps({"permission": {"edit": "deny", "bash": "deny", "webfetch": "deny"}})


def without_tools(profile: Dict[str, Any]) -> Dict[str, Any]:
    """profile with the agent's tools switched off on its command line, not only asked for in the prompt"""
    restricted = copy.deepcopy(profile)
    backend = llm_backends.backend_of(restricted)
    if backend == "claude":
        restricted["extra_args"] = list(restricted.get("extra_args") or []) + _CLAUDE_NO_TOOLS
    elif backend == "opencode":
        # never auto-approve, and deny what writes or runs. Not yet verified against a real opencode run.
        restricted.setdefault("backend_options", {})["auto"] = False
        restricted["auto"] = False
        restricted["env"] = {**(restricted.get("env") or {}), "OPENCODE_CONFIG_CONTENT": _OPENCODE_DENY_ALL}
    return restricted


class BackendAgent:
    """an agent which drives the backend of a profile. Each conversation runs in an empty directory of its own,
    never in the project; a follow-up turn runs in the directory of its conversation, where the backends find their
    session."""

    def __init__(self, profile: Dict[str, Any], timeout: float) -> None:
        self.profile = without_tools(profile)
        self.module = llm_backends.for_profile(self.profile)
        self.timeout = timeout
        self._sandboxes: Dict[str, str] = dict()
        self._created: List[str] = []

    def __call__(self, prompt: str, session: Optional[str]) -> AgentReply:
        sandbox = self._sandboxes.get(session) if session else None
        if sandbox is None:
            sandbox = tempfile.mkdtemp(prefix="discopop_suggestion_check_agent_")
            self._created.append(sandbox)
        new_session = None if session else self.module.new_session_id()
        invocation = llm_backends.run_agent(
            self.module,
            self.profile,
            prompt,
            cwd=sandbox,
            timeout=self.timeout,
            session=session,
            new_session=new_session,
        )
        next_session = session or invocation.session_id or new_session
        if next_session:
            self._sandboxes[next_session] = sandbox
        return AgentReply(
            text=invocation.text,
            answered=invocation.ok,
            failure=invocation.failure_reason(),
            session=next_session,
        )

    def close(self) -> None:
        for sandbox in self._created:
            shutil.rmtree(sandbox, ignore_errors=True)
        self._created.clear()
        self._sandboxes.clear()


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
            return BackendAgent(profile, arguments.agent_timeout)

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
                agent = agent_factory()
                reviewer = agent_factory() if arguments.review else None
                try:
                    outcome = check_suggestion(
                        suggestion,
                        plain,
                        files,
                        agent,
                        reviewer,
                        budget,
                        results.transcripts_dir(suggestion.pattern_id),
                    )
                except Exception as error:  # noqa: BLE001 - one suggestion must not end the run
                    logger.exception("checking suggestion " + str(suggestion.pattern_id) + " failed")
                    outcome = Outcome(suggestion.pattern_id, STATE_FAILED, reason="internal error: " + str(error))
                finally:
                    for made in (agent, reviewer):
                        close = getattr(made, "close", None)
                        if close is not None:
                            close()
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
    # rejections are results, not errors; a run which judged nothing is one
    if suggestions and counts.get(STATE_FAILED, 0) == len(suggestions):
        return 1
    return 0

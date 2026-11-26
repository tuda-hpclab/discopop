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
from typing import Any, Callable, Dict, List, Optional

from discopop_library.PatchRepair import llm_backends, llm_config
from discopop_library.PathManagement.PathManagement import load_file_mapping
from discopop_library.ProjectManager.services.fingerprint_ignore import load_fingerprint_ignore
from discopop_library.SuggestionCheck.SuggestionCheckArguments import SuggestionCheckArguments
from discopop_library.SuggestionCheck.check import STATE_FAILED, Agent, AgentReply, Budget, Outcome, check_suggestion
from discopop_library.SuggestionCheck.facts import SourceFiles
from discopop_library.SuggestionCheck.results import Results
from discopop_library.SuggestionCheck.workspace import ProjectChanged, ProjectGuard
from discopop_library.SuggestionCheck.unsure import (
    UNSURE_SUGGESTIONS_FILE,
    Fingerprint,
    UnsureSuggestion,
    UnsureSuggestionsError,
    load_unsure_suggestions,
)

logger = logging.getLogger("SuggestionCheck")


# What the agent may do, switched on its command line, not only asked for in the prompt: read and edit files in its
# working directory (its copy of the project), nothing else (design/agent_checked_suggestions.md, §5.2).
EDIT = "edit"
READ = "read"
_CLAUDE_TOOLS = {EDIT: "Read,Edit,Write,Grep,Glob", READ: "Read,Grep,Glob"}
_OPENCODE_PERMISSIONS = {
    EDIT: {"edit": "allow", "bash": "deny", "webfetch": "deny"},
    READ: {"edit": "deny", "bash": "deny", "webfetch": "deny"},
}


def restricted(profile: Dict[str, Any], mode: str) -> Dict[str, Any]:
    """profile with the agent's tools restricted to mode (EDIT or READ) in its working directory"""
    result = copy.deepcopy(profile)
    backend = llm_backends.backend_of(result)
    if backend == "claude":
        arguments = ["--tools", _CLAUDE_TOOLS[mode], "--strict-mcp-config", "--restricted"]
        if mode == EDIT:
            # nobody answers permission prompts: edits in the working directory must not need one
            arguments += ["--permission-mode", "acceptEdits"]
        result["extra_args"] = list(result.get("extra_args") or []) + arguments
    elif backend == "opencode":
        # never auto-approve; what is not allowed is denied. Not yet verified against a real opencode run.
        result.setdefault("backend_options", {})["auto"] = False
        result["auto"] = False
        result["env"] = {
            **(result.get("env") or {}),
            "OPENCODE_CONFIG_CONTENT": json.dumps({"permission": _OPENCODE_PERMISSIONS[mode]}),
        }
    else:
        raise ValueError("the suggestion check cannot restrict the tools of the backend " + str(backend))
    return result


class BackendAgent:
    """an agent which drives the backend of a profile in the directory it is given"""

    def __init__(self, profile: Dict[str, Any], timeout: float, mode: str) -> None:
        self.profile = restricted(profile, mode)
        self.module = llm_backends.for_profile(self.profile)
        self.timeout = timeout

    def __call__(self, prompt: str, session: Optional[str], workdir: str) -> AgentReply:
        new_session = None if session else self.module.new_session_id()
        invocation = llm_backends.run_agent(
            self.module,
            self.profile,
            prompt,
            cwd=workdir,
            timeout=self.timeout,
            session=session,
            new_session=new_session,
        )
        return AgentReply(
            text=invocation.text,
            answered=invocation.ok,
            failure=invocation.failure_reason(),
            session=session or invocation.session_id or new_session,
        )


# makes the agents of one suggestion: (mode) -> agent
AgentFactory = Callable[[str], Agent]


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
    project_root = os.path.abspath(arguments.project_root or os.path.dirname(dot))
    files = SourceFiles(load_file_mapping(os.path.join(dot, "FileMapping.txt")), project_root)
    guard = ProjectGuard(project_root)
    # what the fingerprint of a build ignores, e.g. a build directory inside the project, is not copied either
    ignore = load_fingerprint_ignore(os.path.join(dot, "project"))

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

        def agent_factory(mode: str) -> Agent:
            return BackendAgent(profile, arguments.agent_timeout, mode)

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
                outcome = check_suggestion(
                    suggestion,
                    files,
                    project_root,
                    agent_factory(EDIT),
                    agent_factory(READ) if arguments.review else None,
                    budget,
                    results.transcripts_dir(suggestion.pattern_id),
                    guard.check,
                    ignore,
                )
            except ProjectChanged:
                raise
            except Exception as error:  # noqa: BLE001 - one suggestion must not end the run
                logger.exception("checking suggestion " + str(suggestion.pattern_id) + " failed")
                outcome = Outcome(suggestion.pattern_id, STATE_FAILED, reason="internal error: " + str(error))
            results.record(suggestion, outcome)
            counts[outcome.state] = counts.get(outcome.state, 0) + 1
            results.progress("done", pattern_id=suggestion.pattern_id, state=outcome.state, reason=outcome.reason)
        results.progress("end", counts=counts)
    except ProjectChanged as error:
        results.progress("aborted", reason=str(error))
        logger.error(str(error))
        print("ABORTED: " + str(error))
        return 2
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

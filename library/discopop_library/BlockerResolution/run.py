# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""discopop_blocker_resolution: an LLM agent resolves the blockers of the unsure suggestions of the explorer."""

from __future__ import annotations

import copy
import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

from discopop_library.PatchRepair import llm_backends, llm_config
from discopop_library.PathManagement.PathManagement import load_file_mapping
from discopop_library.ProjectManager.services.fingerprint_ignore import load_fingerprint_ignore
from discopop_library.BlockerResolution.BlockerResolutionArguments import BlockerResolutionArguments
from discopop_library.BlockerResolution.check import (
    STATE_APPROVED,
    STATE_FAILED,
    Agent,
    AgentReply,
    Budget,
    CheckOptions,
    Outcome,
    check_suggestion,
)
from discopop_library.BlockerResolution import hotspots
from discopop_library.BlockerResolution.discopop_tools import EXECUTABLE as DISCOPOP_TOOLS_EXECUTABLE
from discopop_library.BlockerResolution.discopop_tools import DiscoPoPTools
from discopop_library.BlockerResolution.discopop_tools import locate as locate_discopop_tools
from discopop_library.BlockerResolution.prompt_store import prompt_info
from discopop_library.BlockerResolution.facts import SourceFiles
from discopop_library.BlockerResolution.publish import publish_approved
from discopop_library.BlockerResolution.results import Results
from discopop_library.BlockerResolution.workspace import ProjectChanged, ProjectGuard
from discopop_library.BlockerResolution.unsure import (
    UNSURE_SUGGESTIONS_FILE,
    Fingerprint,
    UnsureSuggestion,
    UnsureSuggestionsError,
    load_unsure_suggestions,
)

logger = logging.getLogger("BlockerResolution")


# What the agent may do, switched on its command line, not only asked for in the prompt: read and edit files in its
# working directory (its copy of the project), nothing else (design/blocker_resolution.md, §5.2).
EDIT = "edit"
READ = "read"
_CLAUDE_TOOLS = {EDIT: "Read,Edit,Write,Grep,Glob", READ: "Read,Grep,Glob"}
_OPENCODE_PERMISSIONS = {
    EDIT: {"edit": "allow", "bash": "deny", "webfetch": "deny"},
    READ: {"edit": "deny", "bash": "deny", "webfetch": "deny"},
}


def restricted(profile: Dict[str, Any], mode: str, tools: Optional[DiscoPoPTools] = None) -> Dict[str, Any]:
    """profile with the agent's tools restricted to mode (EDIT or READ) in its working directory, and to the
    described tools of DiscoPoP's MCP server if tools is given"""
    result = copy.deepcopy(profile)
    backend = llm_backends.backend_of(result)
    if backend == "claude":
        arguments = ["--tools", _CLAUDE_TOOLS[mode], "--strict-mcp-config", "--restricted"]
        if mode == EDIT:
            # nobody answers permission prompts: edits in the working directory must not need one
            arguments += ["--permission-mode", "acceptEdits"]
        if tools is not None:
            arguments += tools.claude_arguments()
        result["extra_args"] = list(result.get("extra_args") or []) + arguments
    elif backend == "opencode":
        # never auto-approve; what is not allowed is denied. Not yet verified against a real opencode run.
        result.setdefault("backend_options", {})["auto"] = False
        result["auto"] = False
        config: Dict[str, Any] = {"permission": _OPENCODE_PERMISSIONS[mode]}
        if tools is not None:
            config.update(tools.opencode_config())
        result["env"] = {**(result.get("env") or {}), "OPENCODE_CONFIG_CONTENT": json.dumps(config)}
    else:
        raise ValueError("the blocker resolution cannot restrict the tools of the backend " + str(backend))
    return result


class BackendAgent:
    """an agent which drives the backend of a profile in the directory it is given"""

    def __init__(
        self, profile: Dict[str, Any], timeout: float, mode: str, tools: Optional[DiscoPoPTools] = None
    ) -> None:
        self.profile = restricted(profile, mode, tools)
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
            events=invocation.raw,
        )


# makes the agents of one suggestion: (mode) -> agent
AgentFactory = Callable[[str], Agent]


def _select(
    suggestions: List[UnsureSuggestion], arguments: BlockerResolutionArguments, classes: Dict[int, str]
) -> Tuple[List[UnsureSuggestion], List[UnsureSuggestion]]:
    """(to check, skipped by the hotspot filter). Explicit ids are checked whatever their hotspot class: whoever names
    them has decided they are worth the agent calls. The filter applies before --max-suggestions, which must not be
    spent on skipped loops."""
    ids = arguments.suggestion_ids()
    skipped: List[UnsureSuggestion] = []
    if ids is not None:
        known = {s.pattern_id for s in suggestions}
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise UnsureSuggestionsError("not an unsure suggestion: " + ", ".join(str(i) for i in unknown))
        suggestions = [s for s in suggestions if s.pattern_id in ids]
    else:
        suggestions, skipped = hotspots.split(suggestions, classes, arguments.selected_hotspot_types())
    if arguments.max_suggestions:
        suggestions = suggestions[: arguments.max_suggestions]
    return suggestions, skipped


def run(arguments: BlockerResolutionArguments, agent_factory: Optional[AgentFactory] = None) -> int:
    dot = os.path.abspath(arguments.dot_dp_path)
    try:
        unsure = load_unsure_suggestions(dot)
        classes = hotspots.classify(unsure, hotspots.load(dot))
        suggestions, skipped = _select(unsure, arguments, classes)
    except UnsureSuggestionsError as error:
        logger.error(str(error))
        print(str(error))
        return 1
    project_root = os.path.abspath(arguments.project_root or os.path.dirname(dot))
    files = SourceFiles(load_file_mapping(os.path.join(dot, "FileMapping.txt")), project_root)
    guard = ProjectGuard(project_root)
    # DiscoPoP's data through its MCP server, bound to the project root: the server reads <project>/.discopop
    tools: Optional[DiscoPoPTools] = None
    tools_state = "off"
    if arguments.discopop_tools:
        message = ""
        if os.path.realpath(dot) != os.path.realpath(os.path.join(project_root, ".discopop")):
            message = (
                "DiscoPoP's MCP server reads the data of <project root>/.discopop, but the data is in " + dot + " and "
                "the project root is " + project_root + ": the agents work without DiscoPoP's data."
            )
        else:
            tools = locate_discopop_tools(project_root)
            if tools is None:
                message = (
                    "DiscoPoP's MCP server (" + DISCOPOP_TOOLS_EXECUTABLE + ") was not found, or is too old to be "
                    "bound read-only to a project (--tools readonly --project): the agents work without DiscoPoP's "
                    "data. Install the current version, or pass --no-discopop-tools to silence this."
                )
        tools_state = "on" if tools is not None else "unavailable"
        if message:
            logger.warning(message)
            print(message)
    options = CheckOptions(
        ignore=load_fingerprint_ignore(os.path.join(dot, "project")),
        prompt_dir=arguments.effective_prompt_dir,
        accept_rounding=arguments.accept_rounding,
        discopop_tools=tools is not None,
    )

    run_info: Dict[str, Any] = {
        "review_enabled": arguments.review,
        "verify": arguments.verify,
        "accept_rounding": arguments.accept_rounding,
        "discopop_tools": tools_state,
        # which templates were used: a project can replace them (prompt_store)
        "prompts": prompt_info(options.prompt_dir),
    }
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
            return BackendAgent(profile, arguments.agent_timeout, mode, tools)

    budget = Budget(arguments.prompts, arguments.retries, arguments.agent_error_retries)
    results = Results(
        arguments.blocker_resolution_path, Fingerprint.of(os.path.join(dot, UNSURE_SUGGESTIONS_FILE)), run_info
    )
    counts: Dict[str, int] = dict()
    try:
        if skipped:
            results.skipped_by_hotspot = [
                {"pattern_id": s.pattern_id, "hotspot_type": classes[s.pattern_id]} for s in skipped
            ]
            message = (
                "Skipped "
                + str(len(skipped))
                + " cold suggestion(s), whose hotspot type is not in "
                + arguments.hotspot_types
                + ": "
                + ", ".join(str(s.pattern_id) for s in skipped)
            )
            logger.info(message)
            print(message)
        # written even if nothing is checked: which suggestions were skipped, and why; before the event, so that
        # results.json holds them when it arrives
        results.save()
        if skipped:
            results.progress("skipped_by_hotspot", suggestions=results.skipped_by_hotspot)
        approved_ids: List[int] = []
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
                    options,
                )
            except ProjectChanged:
                raise
            except Exception as error:  # noqa: BLE001 - one suggestion must not end the run
                logger.exception("checking suggestion " + str(suggestion.pattern_id) + " failed")
                outcome = Outcome(suggestion.pattern_id, STATE_FAILED, reason="internal error: " + str(error))
            if outcome.discopop_tools_failed and run_info["discopop_tools"] == "on":
                # the backend reported that the server did not start: recorded for this and the following results
                run_info["discopop_tools"] = "failed"
                message = "DiscoPoP's MCP server failed to start: the agents worked without DiscoPoP's data."
                logger.warning(message)
                print(message)
            results.record(suggestion, outcome, classes.get(suggestion.pattern_id))
            counts[outcome.state] = counts.get(outcome.state, 0) + 1
            if outcome.state == STATE_APPROVED:
                approved_ids.append(suggestion.pattern_id)
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
        + " unsure suggestion(s)"
        + (", skipped " + str(len(skipped)) + " cold suggestion(s)" if skipped else "")
        + (": " + ", ".join(str(n) + " " + state for state, n in sorted(counts.items())) if counts else "")
        + ". Approvals rest on the agent's assumptions; see "
        + os.path.join(arguments.blocker_resolution_path, "results.json")
    )
    if arguments.use_approved and approved_ids and not arguments.review:
        print(
            "Not in use: "
            + ", ".join(map(str, approved_ids))
            + " (approved without a review; --publish-approved uses them)"
        )
    elif arguments.use_approved and approved_ids:
        # approvals are used unless the user withdraws them: the assumption each rests on is in the marker file
        published = publish_approved(dot, approved_ids)
        print(
            "In use: "
            + (", ".join(map(str, published.published)) or "nothing")
            + " (withdraw with --withdraw-published)"
        )
        for pattern_id, reason in sorted(published.skipped.items()):
            print("Not in use " + str(pattern_id) + ": " + reason)
    # rejections are results, not errors; a run which judged nothing is one
    if suggestions and counts.get(STATE_FAILED, 0) == len(suggestions):
        return 1
    return 0

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The ``claude`` backend (Claude Code's command line interface).

Only its print mode is used:

    claude -p --output-format stream-json --verbose [--model <id>]
           [--resume <id> | --session-id <id>] -- "<prompt>"

Notes on the flags:

* ``-p`` / ``--output-format stream-json`` is the non-interactive mode with a machine
  readable event stream, which is where the answer, the session id, the token counts
  and the reported cost come from. ``--verbose`` is required for the stream to carry
  the assistant messages rather than only the result.
* ``--resume <id>`` continues a conversation, which is how a follow-up turn sees its
  own previous answer. Unlike opencode, ``claude`` lets the caller *name* the session
  up front (``--session-id``), so :func:`new_session_id` mints one: a first call that
  failed before any event came back can then still be continued.
* ``--permission-prompts none`` denies anything that would still ask. Nobody is there
  to answer, and a blocked prompt would burn the whole timeout. The agent is not asked
  to edit anything -- it answers with a diff -- so nothing it legitimately needs is
  denied by this.

Credentials are never handled here -- ``claude`` owns provider authentication.
"""

from typing import Any, Dict, List, Optional

from discopop_library.PatchRepair.llm_backends.base import (
    FieldSpec,
    as_float,
    as_int,
    empty_parse,
    iter_json_objects,
    new_uuid,
    probe,
    resolve_binary,
    text_of,
    walk,
)

NAME = "claude"
LABEL = "Claude Code"
DESCRIPTION = (
    "The claude CLI (Claude Code) in print mode. Uses whichever account or API key the "
    "CLI is already authenticated with.\n\n"
    "Authentication is configured in claude itself ('claude login'), never in DiscoPoP."
)

BINARY_ENV_VAR = "DISCOPOP_CLAUDE"
DEFAULT_BINARY = "claude"

# The CLI accepts aliases and full model ids beyond anything it lists, so a model
# missing from the list says nothing.
MODELS_ARE_EXHAUSTIVE = False

INSTALL_HINT = "See https://claude.com/claude-code for installation, then run 'claude login'."
AUTH_HINT = "Check the model name and that the CLI is authenticated ('claude login')."

FIELDS = (
    FieldSpec("agent", "Agent", "claude subagent to answer with; empty uses the default", default=""),
    FieldSpec(
        "effort",
        "Reasoning effort",
        "how much the model should think before answering",
        kind="choice",
        choices=("", "low", "medium", "high"),
        default="",
    ),
    FieldSpec(
        "append_system_prompt",
        "Extra system prompt",
        "appended to the system prompt of every call (optional)",
        default="",
    ),
)


def option(profile: Dict[str, Any], key: str, default: Any = "") -> Any:
    options = profile.get("backend_options")
    if isinstance(options, dict) and key in options:
        return options[key]
    return profile.get(key, default)


def binary(config: Optional[Dict[str, Any]] = None) -> str:
    return resolve_binary(BINARY_ENV_VAR, (config or {}).get("binary"), DEFAULT_BINARY)


def version(config: Optional[Dict[str, Any]] = None) -> Optional[str]:
    out = probe([binary(config), "--version"])
    return None if out is None else (out.strip() or None)


def available(config: Optional[Dict[str, Any]] = None) -> bool:
    return version(config) is not None


def list_models(config: Optional[Dict[str, Any]] = None) -> List[str]:
    """Known model aliases. Not exhaustive -- full ids are accepted too."""
    return ["opus", "sonnet", "haiku"]


def new_session_id() -> Optional[str]:
    """A name for the conversation this call starts.

    Minted by the caller so a first call whose process died before emitting any event
    can still be continued by the follow-up turn.
    """
    return new_uuid()


def build_argv(
    profile: Dict[str, Any],
    prompt: str,
    cwd: Optional[str] = None,
    session: Optional[str] = None,
    new_session: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """The ``claude -p`` command line for one invocation of ``profile``.

    ``cwd`` is accepted for the shared interface and is where the caller runs the
    process; ``claude`` has no flag for it, so it does not appear in the argv.
    """
    if config is None:
        config = profile.get("backend_config")
    argv = [binary(config), "-p", "--output-format", "stream-json", "--verbose"]

    if session:
        argv += ["--resume", str(session)]
    elif new_session:
        argv += ["--session-id", str(new_session)]

    model = str(profile.get("model") or "").strip()
    if model:
        argv += ["--model", model]
    agent = str(option(profile, "agent") or "").strip()
    if agent:
        argv += ["--agent", agent]
    effort = str(option(profile, "effort") or "").strip()
    if effort:
        argv += ["--effort", effort]
    append = str(option(profile, "append_system_prompt") or "").strip()
    if append:
        argv += ["--append-system-prompt", append]

    # Nobody is there to answer: anything that would still prompt is denied rather than
    # left blocking a call with no terminal attached.
    argv += ["--permission-prompts", "none"]

    argv += [str(a) for a in (profile.get("extra_args") or [])]
    argv += ["--", prompt]
    return argv


def parse_events(raw: str) -> Dict[str, Any]:
    """Extract the answer, the session id and the usage from the stream."""
    parsed = empty_parse()
    warnings: List[str] = parsed["warnings"]
    texts: List[str] = []
    result_text = ""

    for obj in iter_json_objects(raw):
        if isinstance(obj, dict):
            session_id = obj.get("session_id")
            if isinstance(session_id, str) and session_id and parsed["session_id"] is None:
                parsed["session_id"] = session_id

            if obj.get("type") == "result":
                # The terminal event carries the final answer and the totals.
                if isinstance(obj.get("result"), str):
                    result_text = obj["result"]
                parsed["cost"] = as_float(obj.get("total_cost_usd")) or parsed["cost"]
                if obj.get("is_error") and parsed["error"] is None:
                    parsed["error"] = str(obj.get("subtype") or obj.get("result") or "the agent reported an error")

            if obj.get("type") == "assistant":
                message = obj.get("message")
                if isinstance(message, dict):
                    text = text_of(message.get("content"))
                    if text.strip():
                        texts.append(text)
                    if isinstance(message.get("model"), str) and parsed["model"] is None:
                        parsed["model"] = message["model"]

        for node in walk(obj):
            if not isinstance(node, dict):
                continue
            usage = node.get("usage")
            if isinstance(usage, dict):
                parsed["input_tokens"] = as_int(usage.get("input_tokens")) or parsed["input_tokens"]
                parsed["output_tokens"] = as_int(usage.get("output_tokens")) or parsed["output_tokens"]

    # The result event is the authoritative final answer; the assistant messages are
    # the turns that led to it, and the last of those is the fallback.
    if result_text.strip():
        parsed["text"] = result_text
    elif texts:
        parsed["text"] = texts[-1]
    elif raw.strip() and parsed["error"] is None:
        parsed["text"] = raw
        warnings.append("no assistant message was recognized; using the raw output")
    return parsed

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The ``opencode`` backend (https://opencode.ai).

Only its one-shot mode is used:

    cd <dir> && opencode run --format json [-m <provider>/<model>[#<variant>]] [--session <id>] -- "<prompt>"

Notes on the flags, because each one is load-bearing:

* ``--format json`` gives a machine readable event stream, which is where the
  assistant's answer, the session id and the token counts come from.
* ``--session <id>`` continues an existing conversation, which is how a follow-up turn
  sees its own previous answer. The id is passed explicitly rather than using
  ``--continue`` ("the last session"): several repairs may run through the same
  installation, and picking up an unrelated conversation would be silent corruption.
  ``opencode`` names its own sessions, so :func:`new_session_id` returns None and the
  id is learned from the event stream.
* ``--auto`` is *not* passed by default. The harness needs it because its agent edits
  files; here the agent only has to answer with a diff, so nothing needs approving and
  not asking for edit permissions is the safer default. It stays available as a field
  for a model that insists on writing before it answers.

Credentials are never handled here -- ``opencode`` owns provider authentication.
"""

from typing import Any, Dict, List, Optional

from discopop_library.PatchRepair.llm_backends.base import (
    FieldSpec,
    as_float,
    as_int,
    empty_parse,
    iter_json_objects,
    probe,
    resolve_binary,
    text_of,
    walk,
)

NAME = "opencode"
LABEL = "opencode"
DESCRIPTION = (
    "The opencode CLI (https://opencode.ai). Talks to any provider it is authenticated "
    "for, including self-hosted OpenAI-compatible endpoints declared in its own "
    "configuration.\n\n"
    "Providers and models are configured in opencode itself ('opencode auth'), "
    "never in DiscoPoP."
)

# Overridable so a machine with a non-PATH install (or a wrapper script) can be pointed
# at explicitly.
BINARY_ENV_VAR = "DISCOPOP_OPENCODE"
DEFAULT_BINARY = "opencode"

# 'opencode models' lists exactly what it will accept, so a model missing from it is
# worth warning about.
MODELS_ARE_EXHAUSTIVE = True

INSTALL_HINT = "See https://opencode.ai for installation, then authenticate a provider with 'opencode auth login'."
AUTH_HINT = "Check the model name and that its provider is authenticated ('opencode auth list')."

FIELDS = (
    FieldSpec("agent", "Agent", "opencode agent to drive; empty uses opencode's default", default=""),
    FieldSpec(
        "model_variant",
        "Reasoning effort",
        "provider-specific model variant, e.g. high or max (optional); sent as <model>#<variant>",
    ),
    FieldSpec("attach", "Attach to server", "URL of a running opencode server (optional); sent as --server"),
    FieldSpec(
        "auto",
        "Approve tool use",
        "pass --auto. Not needed to answer with a diff, and off by default so the agent cannot edit anything",
        kind="bool",
        default=False,
    ),
)


def option(profile: Dict[str, Any], key: str, default: Any = "") -> Any:
    """A backend-specific setting of ``profile``.

    Read from ``backend_options`` first and from the top level second, so a connection
    that puts the key next to the shared ones keeps working.
    """
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
    """The models opencode knows about, or [] if they cannot be listed.

    Deliberately not an error when empty: the list depends on which providers are
    authenticated, and refusing to run because a model was not listed would be worse
    than letting the provider say so.
    """
    out = probe([binary(config), "models"])
    if out is None:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def new_session_id() -> Optional[str]:
    """None: opencode names its own sessions, and the id is read from the stream."""
    return None


def build_argv(
    profile: Dict[str, Any],
    prompt: str,
    cwd: Optional[str] = None,
    session: Optional[str] = None,
    new_session: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """The ``opencode run`` command line for one invocation of ``profile``.

    ``new_session`` is unused: opencode does not let the caller name a session.
    """
    argv = [binary(config if config is not None else profile.get("backend_config")), "run", "--format", "json"]
    if session:
        argv += ["--session", str(session)]
    model = str(profile.get("model") or "").strip()
    # opencode 2.x folded --variant into the model name.
    model_variant = str(option(profile, "model_variant") or "").strip()
    if model and model_variant and "#" not in model:
        model = model + "#" + model_variant
    if model:
        argv += ["-m", model]
    agent = str(option(profile, "agent") or "").strip()
    if agent:
        argv += ["--agent", agent]
    attach = str(option(profile, "attach") or "").strip()
    if attach:
        # --attach in opencode 1.x.
        argv += ["--server", attach]
    if option(profile, "auto", False):
        argv += ["--auto"]
    # No --dir: opencode 2.x removed it (and rejects the whole command line when it is
    # given) and works in the directory it is started in, which ``run_agent`` sets --
    # both the process directory and $PWD, which is what opencode actually reads.
    argv += [str(a) for a in (profile.get("extra_args") or [])]
    # The prompt is the positional message, after "--" so one that happens to start
    # with a dash is not parsed as an option.
    argv += ["--", prompt]
    return argv


def parse_events(raw: str) -> Dict[str, Any]:
    """Extract the answer, the session id and the usage from the stream.

    Written against no promised schema: every object is walked and the recognized
    fields are picked up, so an unfamiliar event shape costs accounting detail instead
    of the answer.
    """
    parsed = empty_parse()
    warnings: List[str] = parsed["warnings"]
    texts: List[str] = []

    for obj in iter_json_objects(raw):
        for node in walk(obj):
            if not isinstance(node, dict):
                continue

            session_id = node.get("sessionID") or node.get("session_id") or node.get("sessionId")
            if isinstance(session_id, str) and session_id and parsed["session_id"] is None:
                parsed["session_id"] = session_id

            if node.get("role") == "assistant":
                text = text_of(node.get("content") or node.get("parts") or node.get("text"))
                if text.strip():
                    texts.append(text)
            elif (
                node.get("type") == "text"
                and isinstance(node.get("text"), str)
                and (node.get("id") or node.get("messageID"))
            ):
                # A bare text part outside a message envelope; kept because opencode has
                # emitted the final answer this way. Only a *part* (it has an id):
                # opencode 2.x also nests a tool call's output as id-less
                # {"type": "text"} items, which are not something the model said.
                if node["text"].strip():
                    texts.append(node["text"])

            model = node.get("modelID") or node.get("model")
            if isinstance(model, str) and model and parsed["model"] is None:
                parsed["model"] = model

            tokens = node.get("tokens")
            if isinstance(tokens, dict):
                parsed["input_tokens"] = as_int(tokens.get("input")) or parsed["input_tokens"]
                parsed["output_tokens"] = as_int(tokens.get("output")) or parsed["output_tokens"]
            cost = node.get("cost")
            if cost is not None and parsed["cost"] is None:
                parsed["cost"] = as_float(cost)

            error = node.get("error")
            if error and parsed["error"] is None and not _is_tool_error(node, error):
                parsed["error"] = _error_text(error)

    if texts:
        # The last assistant message is the answer; earlier ones are the reasoning that
        # led to it and would add a second, stale patch to the extraction. An answer
        # also clears a recorded error: an agent that tripped over a tool call on the
        # way and then answered anyway has answered, and failing the attempt over the
        # detour would throw away a usable patch.
        parsed["text"] = texts[-1]
        parsed["error"] = None
    elif raw.strip() and parsed["error"] is None:
        # No recognizable event: better to hand the raw output to the extractor than to
        # discard an answer over a framing change.
        parsed["text"] = raw
        warnings.append("no assistant message was recognized; using the raw output")
    return parsed


# Fields that mark an event as belonging to a *tool call* rather than to the session.
# A failed tool call is the model's own business -- it is told about it and can recover
# -- while an API or authentication error ends the call.
_TOOL_EVENT_KEYS = ("tool", "toolName", "tool_name", "callID", "toolCallId", "tool_call_id")

# Tool failures phrased as a bare message, recognizable by what they are about.
_TOOL_ERROR_MARKERS = (
    "oldstring",
    "was called with invalid arguments",
    "schemaerror",
    "file has not been read yet",
    "no such tool",
)


def _is_tool_error(node: Dict[str, Any], error: Any) -> bool:
    """Whether an error event is a failed tool call rather than a failed call.

    The agent is asked to answer with a diff, not to use tools, but models reach for the
    edit and read tools anyway. Those failures are recoverable -- the agent is told and
    tries something else -- so treating them as fatal would abandon attempts that went
    on to produce a perfectly good answer.
    """
    if any(key in node for key in _TOOL_EVENT_KEYS):
        return True
    text = _error_text(error).lower()
    return any(marker in text for marker in _TOOL_ERROR_MARKERS)


def _error_text(error: Any) -> str:
    """A readable reason out of an opencode error event.

    The useful part is nested: an event is ``{"name": "APIError", "data": {"message":
    "Incorrect API key provided: ..."}}``, and reporting only the name tells the user
    that something went wrong without telling them the one thing they need -- which
    provider is not authenticated, or which model does not exist.
    """
    if isinstance(error, str):
        return error
    if not isinstance(error, dict):
        return str(error)

    name = str(error.get("name") or "").strip()
    detail = ""
    data = error.get("data")
    if isinstance(data, dict):
        for key in ("message", "detail", "error"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                detail = value.strip()
                break
    if not detail:
        for key in ("message", "detail", "type"):
            value = error.get(key)
            if isinstance(value, str) and value.strip():
                detail = value.strip()
                break
    if name and detail:
        return name + ": " + detail
    return detail or name or str(error)

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Everything about driving a coding agent that is not specific to *which* one.

The patch repair tool asks a command line coding agent to fix a patch that does not
compile. ``opencode`` and ``claude`` differ in three places -- the command line they
take, the shape of the event stream they emit, and how a session is named -- and in
nothing else. Everything else is the same for both and lives here:

* :class:`FieldSpec` -- one backend-specific setting, declared next to the flag it
  produces so the GUI can build its editor from the registry.
* :class:`Invocation` -- the outcome of one call, and what is known about it.
* :func:`run_agent` -- the actual subprocess: environment, timeout, no stdin.
* the tolerant JSON helpers both adapters parse their event stream with.

A *backend adapter* is a module registered in ``llm_backends/__init__.py`` providing
the rest. The contract, in full:

``NAME`` / ``LABEL`` / ``DESCRIPTION``
    Identity, and the text its selector shows.
``BINARY_ENV_VAR`` / ``DEFAULT_BINARY``
    Where the executable comes from when nothing is configured.
``FIELDS``
    The :class:`FieldSpec` list of the settings only this backend understands.
``MODELS_ARE_EXHAUSTIVE``
    Whether :func:`list_models` returns *every* model the backend accepts. When it
    does not, a model missing from the list says nothing and no warning is due.
``INSTALL_HINT`` / ``AUTH_HINT``
    What to tell the user when the binary cannot be run, and when the model could
    not be reached.
``binary()`` / ``version()`` / ``available()`` / ``list_models()``
    Probes. Each one is best effort with a short fixed timeout.
``build_argv(profile, prompt, cwd, session, new_session, config)``
    The command line for one call.
``parse_events(raw)``
    Session id, usage and above all the assistant's text, out of the event stream.
``new_session_id()``
    A name for the conversation this call starts, or None for a backend that names
    its own sessions.

This mirrors ``shared/llm_backends`` of the benchmark harness, deliberately: the two
solve the same problem, and keeping the shape identical means what is learned about
one holds for the other. It is simpler here in one important way -- the agent never
edits files. It is handed the patch, the source and the compiler's diagnostics, and
answers with a diff, so none of the workspace scoping and edit-approval machinery the
harness needs applies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import os
import subprocess
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

logger = logging.getLogger("PatchRepair").getChild("llm")

# Probes only ask a binary to describe itself; a slow answer is as useless as none.
PROBE_TIMEOUT = 15.0

# Connection keys that mean the same thing whichever agent is driving. A backend
# declaring a field of one of these names would silently shadow it.
RESERVED_KEYS = frozenset(
    {
        "name",
        "backend",
        "model",
        "prompts",
        "retries",
        "timeout",
        "extra_args",
        "env",
        "backend_options",
        "description",
    }
)

# Display variables are stripped from the inherited environment: an agent launched
# from the GUI must not try to open a window of its own.
GUI_DISPLAY_VARS = ("DISPLAY", "WAYLAND_DISPLAY")


@dataclass(frozen=True)
class FieldSpec:
    """One backend-specific setting, as the GUI should offer it.

    Declared next to the flag it produces, so a setting cannot reach the dialogs
    without an explanation of what it does.
    """

    key: str
    label: str
    hint: str = ""
    kind: str = "text"  # "text" | "choice" | "bool"
    choices: Tuple[str, ...] = ()
    default: Any = ""


def check_fields(backend: Any) -> None:
    """Raise if a backend declares a field that shadows a shared connection key."""
    clash = sorted({spec.key for spec in getattr(backend, "FIELDS", ())} & RESERVED_KEYS)
    if clash:
        raise ValueError(
            "backend '"
            + str(getattr(backend, "NAME", backend))
            + "' declares reserved field(s) "
            + ", ".join(clash)
            + "; those names belong to every connection and cannot mean something backend-specific"
        )


# ---- probes ------------------------------------------------------------------


def probe(argv: Sequence[str], timeout: float = PROBE_TIMEOUT) -> Optional[str]:
    """Run a self-describing command and return its stdout, or None.

    Every failure mode -- missing binary, non-zero exit, timeout -- collapses to None,
    because every caller wants the same thing from it: "this could not be asked", not
    the reason why.
    """
    try:
        completed = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def resolve_binary(env_var: str, configured: Any, default: str) -> str:
    """The executable to use: environment override, then configuration, then default.

    The environment wins so a one-off run can point at another install without editing
    (and committing) the configuration.
    """
    override = os.environ.get(env_var)
    if override:
        return override
    text = str(configured or "").strip()
    return text or default


# ---- the outcome of one invocation -------------------------------------------


@dataclass
class Invocation:
    """Outcome of one call to a coding agent."""

    backend: str = ""
    argv: List[str] = field(default_factory=list)
    continued_session: Optional[str] = None
    returncode: Optional[int] = None
    seconds: float = 0.0
    timed_out: bool = False
    # An error the agent reported about itself (unreachable model, bad credentials),
    # as opposed to a non-zero exit code, which can mean anything.
    error: Optional[str] = None
    session_id: Optional[str] = None
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cost: Optional[float] = None
    # What the repair loop is actually after: the assistant's final message, from
    # which the candidate patch is extracted.
    text: str = ""
    raw: str = ""
    stderr: str = ""
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Whether this call produced an answer worth looking at.

        A non-zero exit code with text is still worth parsing -- agents exit non-zero
        for reasons that have nothing to do with the answer -- but a timeout or an
        error the agent reported about itself is not.
        """
        return not self.timed_out and self.error is None and bool(self.text.strip())

    def failure_reason(self) -> str:
        if self.timed_out:
            return "the agent did not answer within the timeout"
        if self.error:
            return "the agent reported an error: " + self.error
        if not self.text.strip():
            return "the agent returned no text (exit code " + str(self.returncode) + ")"
        return ""


def run_agent(
    backend: Any,
    profile: Dict[str, Any],
    prompt: str,
    cwd: str,
    timeout: Optional[float] = None,
    env: Optional[Dict[str, str]] = None,
    session: Optional[str] = None,
    new_session: Optional[str] = None,
) -> Invocation:
    """Invoke ``backend`` once and record everything about it.

    ``session`` continues that conversation instead of starting a new one, which is how
    a follow-up turn (``--retries``) sees its own previous answer. ``new_session`` names
    the conversation this call starts, for a backend that lets the caller pick one;
    choosing it here rather than inside means a first call that failed before any event
    came back can still be continued.

    Never raises for a failed invocation: the outcome, including a timeout, is reported
    in the result, because a failed attempt is data the run reports rather than an error
    that aborts it.
    """
    new_session = None if session else new_session
    argv = [str(a) for a in backend.build_argv(profile, prompt, cwd, session=session, new_session=new_session)]
    result = Invocation(backend=str(getattr(backend, "NAME", "")), argv=list(argv), continued_session=session)

    profile_timeout = float(profile.get("timeout") or 0)
    effective_timeout = profile_timeout if profile_timeout > 0 else timeout

    process_env = os.environ.copy()
    for display_var in GUI_DISPLAY_VARS:
        process_env.pop(display_var, None)
    # ``cwd=`` changes the directory but not the inherited $PWD, and some agents
    # (opencode 2.x) take their project directory from $PWD -- so without this the
    # agent would work in whatever directory DiscoPoP was started from.
    process_env["PWD"] = str(cwd)
    for layer in (profile.get("env") or {}, env or {}):
        for key, value in layer.items():
            process_env[str(key)] = str(value)

    started = time.time()
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            # Nobody is there to type: a prompt for input must fail, not block forever.
            stdin=subprocess.DEVNULL,
            env=process_env,
            timeout=effective_timeout,
        )
        result.returncode = completed.returncode
        result.raw = completed.stdout or ""
        result.stderr = completed.stderr or ""
    except subprocess.TimeoutExpired as expired:
        result.timed_out = True
        result.raw = _as_text(expired.stdout)
        result.stderr = _as_text(expired.stderr)
    except OSError as error:
        result.error = str(error)
        result.seconds = time.time() - started
        return result
    result.seconds = time.time() - started

    if (
        result.returncode not in (0, None)
        and not result.timed_out
        and next(iter_json_objects(result.raw), None) is None
    ):
        # A failed exit with no event stream at all is the agent refusing the call --
        # an unknown flag, a removed subcommand -- and what it printed is its usage
        # text, not an answer. Handed to the extractor, every such call was recorded
        # as a model that answered without a patch, so a broken invocation read
        # exactly like a model that cannot fix patches.
        # The last line: usage text comes first and the reason after it
        # ("ERROR / Unrecognized flag: --dir in command opencode run").
        lines = [line.strip() for line in (result.raw + "\n" + result.stderr).splitlines() if line.strip()]
        reason = lines[-1] if lines else ""
        result.error = (
            "the agent exited with code "
            + str(result.returncode)
            + " without producing an event stream"
            + (": " + reason if reason else "")
        )
        return result

    try:
        parsed = backend.parse_events(result.raw)
    except Exception as error:  # a parser must never cost the answer
        logger.debug("Could not parse the event stream of " + result.backend + ": " + str(error))
        parsed = empty_parse()
        parsed["text"] = result.raw
        result.warnings.append("the event stream could not be parsed; using the raw output")

    result.text = str(parsed.get("text") or "")
    result.session_id = parsed.get("session_id") or session
    result.model = parsed.get("model")
    result.input_tokens = parsed.get("input_tokens")
    result.output_tokens = parsed.get("output_tokens")
    result.cost = parsed.get("cost")
    if parsed.get("error") and not result.error:
        result.error = str(parsed["error"])
    result.warnings.extend(str(w) for w in (parsed.get("warnings") or []))
    return result


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def new_uuid() -> str:
    return str(uuid.uuid4())


# ---- tolerant JSON parsing ----------------------------------------------------


def empty_parse() -> Dict[str, Any]:
    """The shape every adapter's ``parse_events`` returns."""
    return {
        "text": "",
        "session_id": None,
        "model": None,
        "input_tokens": None,
        "output_tokens": None,
        "cost": None,
        "error": None,
        "warnings": [],
    }


def iter_json_objects(text: str) -> Iterator[Any]:
    """Yield the JSON objects in ``text``, whether newline delimited or concatenated.

    Agents emit one object per event; being tolerant about how they are separated means
    a change in output framing degrades the accounting rather than breaking the run.
    """
    decoder = json.JSONDecoder()
    index, length = 0, len(text)
    while index < length:
        while index < length and text[index] in " \t\r\n,":
            index += 1
        if index >= length:
            return
        try:
            obj, end = decoder.raw_decode(text, index)
        except ValueError:
            # Skip to the next plausible object start; a truncated tail (killed
            # process) must not discard the events before it.
            nxt = text.find("{", index + 1)
            if nxt == -1:
                return
            index = nxt
            continue
        index = end
        if isinstance(obj, (dict, list)):
            yield obj


def walk(node: Any) -> Iterator[Dict[str, Any]]:
    """Depth-first walk over every dict inside ``node``."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def as_int(value: Any) -> Optional[int]:
    """``value`` as a non-negative int, or None if it is not one."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def as_float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def text_of(content: Any) -> str:
    """The text in an assistant message's ``content``, whatever shape it has.

    Both agents nest the answer differently and change it between versions, so this
    accepts a bare string, a list of blocks, or a dict with a ``text`` field.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return str(content.get("text") or "")
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in (None, "text"):
                part = block.get("text")
                if isinstance(part, str):
                    parts.append(part)
        return "".join(parts)
    return ""

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The toolkit-free logic of the LLM configuration dialogs (``qt_gui/llm_dialogs.py``).

Everything here works on plain dicts and strings over ``PatchRepair/llm_config.py`` and ``PatchRepair/llm_backends``,
so it is tested without Qt. Ported from the benchmark harness's ``gui/qt/llm_logic.py``, adapted to DiscoPoP's file
(``connections`` / ``backends``, backend option defaults under ``options``, no prompts or MCP sections). The rules:

* every backend-specific setting has **blank = inherit**: blank is stored as "not set", never as an empty value;
* the editor is filled from the connection *as written* (``stored_connection``), never from the resolved form
  (``llm_config.resolve_connection``), or a save would freeze the inherited values into the connection;
* saving a connection moves backend settings written at its top level into ``backend_options`` and keeps keys the
  dialog does not edit;
* the connections and the backends dialog edit the same file; each saves only its own section over what is on disk
  (``merge_section``), so saving one does not revert what the other saved.
"""

import copy
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from discopop_library.PatchRepair import llm_backends, llm_config

CONNECTIONS = "connections"
BACKENDS = "backends"

# what the connections dialog edits; every other key of a stored connection is kept as it is
CONNECTION_KEYS = ("description", "backend", "model", "timeout", "extra_args", "env", "backend_options")

BACKEND_TOOLTIP = (
    "Which command line coding agent is asked.\n\n"
    "The choice decides what the model list offers and which settings appear under the backend's own settings "
    "below; everything else here means the same whichever agent is used.\n\n"
    "Where each agent is installed, and what every connection through it defaults to, is configured under "
    "Settings > LLM backends."
)


UNSET_BACKEND_NOTE = "Not set in this connection: a run uses the first installed agent, shown here is the default."


def config_path(dot_dp: str) -> str:
    """The LLM configuration of the project (shared by patch repair and the suggestion check)."""
    return llm_config.default_config_path(os.path.join(dot_dp, "patch_repair"))


def read_connection_names(dot_dp: str) -> Tuple[List[str], Optional[str]]:
    """``(names, None)`` of the stored connections, or ``([], message)`` when the file cannot be read."""
    try:
        return llm_config.connection_names(llm_config.load_config(config_path(dot_dp))), None
    except ValueError as error:
        return [], str(error)


# ---- environment text -----------------------------------------------------------------------------------------


def parse_env(text: str) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    """``KEY=VALUE`` lines as ``(dict, None)``, or ``(None, message)`` for the first bad line."""
    env: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            return None, "Environment line is not KEY=VALUE:\n" + line
        key, value = line.split("=", 1)
        if not key.strip():
            return None, "Environment line has no name before '=':\n" + line
        env[key.strip()] = value.strip()
    return env, None


def format_env(env: Any) -> str:
    if not isinstance(env, dict):
        return ""
    return "".join(f"{key}={value}\n" for key, value in sorted(env.items()))


def format_args(args: Any) -> str:
    if not isinstance(args, list):
        return ""
    return " ".join(str(arg) for arg in args)


# ---- backend setting fields (blank = inherit) -----------------------------------------------------------------


def field_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def field_choices(spec: Any) -> Optional[Tuple[str, ...]]:
    """The values of a combo for ``spec`` (blank = inherit first), or None for a free-text field."""
    if spec.kind == "bool":
        return ("", "yes", "no")
    if spec.kind == "choice" and spec.choices:
        return ("",) + tuple(choice for choice in spec.choices if choice != "")
    return None


def field_values(specs: Iterable[Any], texts: Mapping[str, str]) -> Dict[str, Any]:
    """What was actually set: blanks left out, bool fields as booleans."""
    out: Dict[str, Any] = {}
    for spec in specs:
        text = (texts.get(spec.key) or "").strip()
        if text:
            out[spec.key] = (text == "yes") if spec.kind == "bool" else text
    return out


def field_hint(spec: Any, inherited: Mapping[str, Any]) -> str:
    """The field's own explanation plus the value a blank stands for."""
    hint = spec.hint or ""
    fallback = field_text(inherited.get(spec.key))
    if fallback:
        return f"{hint}; blank = {fallback}" if hint else f"blank = {fallback}"
    return f"{hint}; blank = unset" if hint else "blank = unset"


def backend_section(config: Mapping[str, Any], backend: str) -> Dict[str, Any]:
    section = (config.get(BACKENDS) or {}).get(backend)
    return dict(section) if isinstance(section, dict) else {}


def inherited_defaults(config: Mapping[str, Any], backend: str) -> Dict[str, Any]:
    """The value each field of ``backend`` has when a connection leaves it blank: the backend's ``options`` in the
    configuration, then the field's own default (the last two layers of ``llm_backends.resolve_options``)."""
    options = backend_section(config, backend).get("options")
    options = options if isinstance(options, dict) else {}
    return {spec.key: options.get(spec.key, spec.default) for spec in llm_backends.fields_of(backend)}


# ---- connections ----------------------------------------------------------------------------------------------


def connections_of(config: Mapping[str, Any]) -> Dict[str, Any]:
    connections = config.get(CONNECTIONS)
    return connections if isinstance(connections, dict) else {}


def stored_connection(config: Mapping[str, Any], name: Optional[str]) -> Dict[str, Any]:
    """The connection as written (nothing resolved, nothing filled in)."""
    if name is None:
        return {}
    stored = connections_of(config).get(name)
    return dict(stored) if isinstance(stored, dict) else {}


def connection_backend(connection: Mapping[str, Any]) -> str:
    """The backend the editor shows: the stored one if known, else the default."""
    name = str(connection.get("backend") or "")
    return name if name in llm_backends.available_backends() else llm_backends.DEFAULT_BACKEND


def parse_timeout(text: str) -> Tuple[Optional[float], Optional[str]]:
    """``(seconds, None)``; blank is ``(None, None)``: the run's agent timeout applies."""
    text = text.strip()
    if not text:
        return None, None
    try:
        value = float(text)
    except ValueError:
        return None, f"The timeout must be a number of seconds (got {text!r})."
    if value < 0:
        return None, "The timeout must not be negative."
    return value, None


def build_connection(
    texts: Mapping[str, str], backend: str, backend_options: Mapping[str, Any], env: Mapping[str, str]
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """The edited keys of a connection from the editor's texts; ``timeout`` is left out when blank."""
    timeout, error = parse_timeout(texts.get("timeout") or "")
    if error is not None:
        return None, error
    connection: Dict[str, Any] = {
        "description": (texts.get("description") or "").strip(),
        "model": (texts.get("model") or "").strip(),
        "extra_args": (texts.get("extra_args") or "").split(),
        "env": dict(env),
        "backend_options": dict(backend_options),
    }
    if backend:
        connection["backend"] = backend  # blank: not set, a run uses the first installed agent
    if timeout is not None:
        connection["timeout"] = int(timeout) if timeout == int(timeout) else timeout
    return connection, None


def store_connection(config: Dict[str, Any], name: str, connection: Mapping[str, Any]) -> Optional[str]:
    """Merge ``connection`` into ``config`` under ``name``; return the validation error (capitalized) or None.

    Keys this dialog does not edit are kept; edited keys missing from ``connection`` (a blank timeout) are removed;
    backend settings written at the top level (the old flat form) are dropped, they now live in ``backend_options``.
    """
    stored = stored_connection(config, name)
    for key in CONNECTION_KEYS:
        stored.pop(key, None)
    # every backend's flat fields, not just the chosen one's: switching agents would leave the old ones behind
    for other in llm_backends.available_backends():
        for spec in llm_backends.fields_of(other):
            stored.pop(spec.key, None)
    stored.update(connection)
    config.setdefault(CONNECTIONS, {})[name] = stored
    error = llm_config.validate_connection(config, name)
    return error[0].upper() + error[1:] if error else None


def new_connection(backend: str) -> Dict[str, Any]:
    return {"description": "", "backend": backend, "model": ""}


def copy_connection(config: Dict[str, Any], source: str, name: str) -> None:
    config.setdefault(CONNECTIONS, {})[name] = copy.deepcopy(stored_connection(config, source))


# ---- backends -------------------------------------------------------------------------------------------------


def build_backend_section(
    binary: str, args_text: str, env: Mapping[str, str], options: Mapping[str, Any]
) -> Dict[str, Any]:
    """The edited keys of a ``backends`` section; empty values are left out (blank = default)."""
    section: Dict[str, Any] = {}
    if binary.strip():
        section["binary"] = binary.strip()
    if args_text.split():
        section["extra_args"] = args_text.split()
    if env:
        section["env"] = dict(env)
    if options:
        section["options"] = dict(options)
    return section


def store_backend(config: Dict[str, Any], name: str, section: Mapping[str, Any]) -> Optional[str]:
    """Write the section, keeping keys the dialog does not edit; a backend configured with nothing is removed rather
    than written empty. Returns the validation error (capitalized) or None."""
    merged = backend_section(config, name)
    for key in ("binary", "extra_args", "env", "options"):
        merged.pop(key, None)
    merged.update(section)
    backends = config.setdefault(BACKENDS, {})
    if merged:
        backends[name] = merged
    else:
        backends.pop(name, None)
    error = llm_config.validate_backend(config, name)
    return error[0].upper() + error[1:] if error else None


def binary_probe(backend_name: str, binary_text: str) -> Tuple[str, Optional[str]]:
    """``(executable, version or None)`` of the configured binary. Runs the binary: call it off the UI thread."""
    backend = llm_backends.get(backend_name)
    section = {"binary": binary_text.strip()}
    return str(backend.binary(section)), backend.version(section)


def binary_status(
    backend_name: str, resolved: str, version: Optional[str], environ: Optional[Mapping[str, str]] = None
) -> str:
    """The line under the executable of a backend: found / not found, and whether the environment overrides it."""
    environ = os.environ if environ is None else environ
    backend = llm_backends.get(backend_name)
    env_var = str(getattr(backend, "BINARY_ENV_VAR", "") or "")
    prefix = f"${env_var} overrides this: " if env_var and environ.get(env_var) else ""
    if version:
        return f"{prefix}found: {resolved} ({version})"
    return f"{prefix}not found: {resolved} could not be run"


def backend_hint(config: Mapping[str, Any], name: str, version: Optional[str]) -> str:
    """The availability line under the Backend field of a connection (``version`` from a probe; None = not found)."""
    backend = llm_backends.get(name)
    binary = backend.binary(backend_section(config, name))
    if version:
        return f"{binary} ({version})"
    install = str(getattr(backend, "INSTALL_HINT", "") or "")
    text = f"NOT FOUND: {binary} could not be run. Set its path under Settings > LLM backends."
    return text + " " + install if install else text


def model_note(name: str) -> str:
    """What the model list is: everything the backend accepts, or only suggestions."""
    try:
        exhaustive = bool(getattr(llm_backends.get(name), "MODELS_ARE_EXHAUSTIVE", False))
    except KeyError:
        exhaustive = False
    suffix = "; blank = the backend's default model"
    if exhaustive:
        return "the models this backend lists, as it spells them" + suffix
    return "suggestions only: the backend accepts more than it lists" + suffix


# ---- saving -------------------------------------------------------------------------------------------------------


def merge_section(on_disk: Mapping[str, Any], edited: Mapping[str, Any], section: str) -> Dict[str, Any]:
    """``on_disk`` with ``section`` replaced by the edited one: what a dialog that owns ``section`` writes."""
    merged = dict(on_disk)
    merged[section] = dict(edited.get(section) or {})
    return merged

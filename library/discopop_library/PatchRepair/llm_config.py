# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The LLM connections a patch repair run can be driven with.

Two kinds of thing are configured here, in one JSON file:

* **connections** -- which model to ask, through which *backend* (the coding agent
  that talks to it, see ``llm_backends/``), with which defaults for the number of
  independent attempts, the follow-up turns allowed inside an attempt, and the
  per-call timeout.
* **backends** -- how to reach each coding agent on *this machine*, and what every
  connection through it should default to: where its executable lives, arguments and
  environment added to each of its invocations, and defaults for the settings only
  that agent understands.

They are separate sections because they answer different questions. A connection is
part of the experiment ("ask this model, this way") and means the same on any machine;
a backend section is part of the installation ("here is where that agent is") and does
not. Splitting them keeps one connection from having to repeat an install path, and
keeps that path out of every connection when the file is copied elsewhere.

**No credentials are stored here.** The backend already owns provider authentication,
and DiscoPoP never sees an API key.

A connection is split in two for the same reason. The **shared** settings -- model,
prompts, retries, timeout, extra arguments, environment -- mean the same thing
whichever agent is driving, so they stay at the top level and a connection can be
pointed at another backend without being rewritten. Everything only one agent
understands lives under ``backend_options``, declared by that backend's ``FIELDS`` so
the GUI builds its editor from the registry rather than from a hardcoded row per flag.

This mirrors ``shared/llm_config.py`` of the benchmark harness.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

from discopop_library.PatchRepair import llm_backends

logger = logging.getLogger("PatchRepair").getChild("llm_config")

# Overridable so one run can point at another configuration without editing the one in
# the project.
CONFIG_ENV_VAR = "DISCOPOP_PATCH_REPAIR_LLM_CONFIG"
CONFIG_FILE_NAME = "llm_config.json"

CONFIG_VERSION = 1

# Used when the configuration names no connection at all: the first installed agent,
# with the backend's own defaults. A machine with exactly one agent installed -- the
# common case -- therefore needs no configuration whatsoever.
IMPLICIT_CONNECTION_NAME = "default"


def default_config_path(patch_repair_path: str) -> str:
    override = os.environ.get(CONFIG_ENV_VAR)
    if override:
        return override
    return os.path.join(patch_repair_path, CONFIG_FILE_NAME)


def empty_config() -> Dict[str, Any]:
    return {"version": CONFIG_VERSION, "connections": {}, "backends": {}}


def load_config(path: str) -> Dict[str, Any]:
    """Read the configuration, or return an empty one when there is none.

    A missing file is not an error: a run that names a backend and a model on the
    command line needs no configuration, and demanding one would put a file between the
    user and the simplest possible invocation.
    """
    if not os.path.exists(path):
        return empty_config()
    try:
        with open(path, "r") as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("Could not read the LLM configuration " + path + ": " + str(error))
    if not isinstance(config, dict):
        raise ValueError("The LLM configuration " + path + " must contain a JSON object.")
    config.setdefault("version", CONFIG_VERSION)
    config.setdefault("connections", {})
    config.setdefault("backends", {})
    return config


def save_config(path: str, config: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, sort_keys=True, indent=4)


def connection_names(config: Dict[str, Any]) -> List[str]:
    return sorted(config.get("connections") or {})


def backend_defaults(config: Dict[str, Any], backend_name: str) -> Dict[str, Any]:
    """The ``backends`` section for one agent, or an empty one."""
    section = (config.get("backends") or {}).get(backend_name)
    return dict(section) if isinstance(section, dict) else {}


def resolve_connection(
    config: Dict[str, Any],
    name: Optional[str] = None,
    backend_override: Optional[str] = None,
    model_override: Optional[str] = None,
) -> Dict[str, Any]:
    """The connection to drive a run with, fully resolved.

    ``name`` selects a stored connection; without one, the single stored connection is
    used when there is exactly one, and otherwise an implicit connection (through
    ``backend_override``, or the first installed agent). Several stored connections
    and neither a name nor a backend override is an error. ``backend_override`` and ``model_override`` come from the
    command line and win over whatever is stored, so a one-off run never has to edit
    the file.

    The result carries the backend's install settings under ``backend_config`` and its
    declared options, resolved through all four layers, under ``backend_options``.
    """
    connections = config.get("connections") or {}

    if name:
        if name not in connections:
            raise ValueError(
                "Unknown LLM connection: "
                + name
                + ". Known connections: "
                + (", ".join(connection_names(config)) or "(none)")
            )
        profile = dict(connections[name])
        profile.setdefault("name", name)
    elif len(connections) == 1:
        only_name = next(iter(connections))
        profile = dict(connections[only_name])
        profile.setdefault("name", only_name)
    else:
        # With a backend named on the command line, a run that selects no connection is
        # a one-off: it asks that backend directly instead of refusing because several
        # connections are stored (the GUI's "choose backend and model" mode does this).
        if connections and not backend_override:
            raise ValueError(
                "The LLM configuration defines several connections; select one with "
                "--connection. Known connections: " + ", ".join(connection_names(config))
            )
        profile = {"name": IMPLICIT_CONNECTION_NAME}

    if backend_override:
        profile["backend"] = backend_override
    if model_override:
        profile["model"] = model_override

    if not profile.get("backend"):
        installed = llm_backends.first_installed_backend()
        if installed is None:
            raise ValueError(
                "No LLM agent found. Install one of "
                + ", ".join(llm_backends.available_backends())
                + ", or name one with --backend.\n"
                + "\n".join(
                    "  " + name + ": " + str(getattr(llm_backends.get(name), "INSTALL_HINT", ""))
                    for name in llm_backends.available_backends()
                )
            )
        profile["backend"] = installed

    unknown = llm_backends.unknown_backends([profile["backend"]])
    if unknown:
        raise ValueError(
            "Unknown backend: " + unknown[0] + ". Known backends: " + ", ".join(llm_backends.available_backends())
        )

    defaults = backend_defaults(config, str(profile["backend"]))
    profile["backend_config"] = defaults
    profile["backend_options"] = llm_backends.resolve_options(profile, defaults.get("options") or {})

    # Install-wide extras apply to every connection through that agent, and the
    # connection's own come after so they can add to, not be replaced by, the defaults.
    profile["extra_args"] = list(defaults.get("extra_args") or []) + list(profile.get("extra_args") or [])
    merged_env = dict(defaults.get("env") or {})
    merged_env.update(profile.get("env") or {})
    profile["env"] = merged_env

    return profile


def describe_connection(profile: Dict[str, Any]) -> str:
    """One line naming what a run will actually ask."""
    backend = llm_backends.backend_of(profile)
    model = str(profile.get("model") or "").strip() or "(backend default)"
    return str(profile.get("name") or IMPLICIT_CONNECTION_NAME) + ": " + backend + " / " + model


def check_connection(profile: Dict[str, Any]) -> List[str]:
    """Warnings about a connection that is resolvable but probably will not work.

    Warnings rather than errors throughout: the model list depends on which providers
    are authenticated, and refusing to run because a model was not listed would be
    worse than letting the provider say so.
    """
    warnings: List[str] = []
    module = llm_backends.for_profile(profile)
    if not module.available():
        warnings.append(
            "The '"
            + llm_backends.backend_of(profile)
            + "' binary could not be run. "
            + str(getattr(module, "INSTALL_HINT", ""))
        )
        return warnings
    model = str(profile.get("model") or "").strip()
    if model and getattr(module, "MODELS_ARE_EXHAUSTIVE", False):
        known = module.list_models()
        if known and model not in known:
            warnings.append(
                "The model '"
                + model
                + "' is not among the models "
                + llm_backends.backend_of(profile)
                + " lists. "
                + str(getattr(module, "AUTH_HINT", ""))
            )
    return warnings


# ---- validation ----------------------------------------------------------------
#
# Checked when the GUI saves the file, so a typo is reported where it was made and not
# by the first run that resolves the connection. Only what can be judged without
# running anything: whether a backend is installed, or a model reachable, is a probe
# and reported by check_connection.


def _string_list_problem(value: Any) -> Optional[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return "must be a list of strings"
    return None


def _env_problem(value: Any) -> Optional[str]:
    if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
        return "must be an object of strings"
    return None


def _options_problem(backend_name: str, options: Any) -> Optional[str]:
    """Why ``options`` cannot be the backend-specific settings of ``backend_name``, or None."""
    if not isinstance(options, dict):
        return "must be an object"
    for spec in llm_backends.fields_of(backend_name):
        if spec.key not in options:
            continue
        value = options[spec.key]
        if spec.kind == "bool":
            if not isinstance(value, bool):
                return "sets '" + spec.label + "' to " + repr(value) + ", which is not true or false"
        elif spec.kind == "choice" and spec.choices:
            if str(value) not in spec.choices:
                return (
                    "sets '"
                    + spec.label
                    + "' to "
                    + repr(value)
                    + ", which "
                    + backend_name
                    + " does not accept. One of: "
                    + ", ".join(repr(choice) for choice in spec.choices)
                )
        elif not isinstance(value, str):
            return "sets '" + spec.label + "' to " + repr(value) + ", which is not text"
    return None


def validate_connection(config: Dict[str, Any], name: str) -> Optional[str]:
    """Why the stored connection ``name`` cannot be used, or None if it can.

    An empty backend is allowed (the first installed agent), and so is an empty model
    (the backend's default): both are what a connection says when it leaves the choice
    to the machine it runs on.
    """
    connections = config.get("connections")
    if not isinstance(connections, dict) or name not in connections:
        return "no LLM connection named '" + name + "' is configured"
    connection = connections[name]
    who = "connection '" + name + "'"
    if not isinstance(connection, dict):
        return who + " is not an object"
    backend_name = str(connection.get("backend") or "")
    if backend_name and llm_backends.unknown_backends([backend_name]):
        return (
            who
            + " uses the unknown backend '"
            + backend_name
            + "'. Known backends: "
            + ", ".join(llm_backends.available_backends())
        )
    for key in ("description", "model"):
        if key in connection and not isinstance(connection[key], str):
            return who + ": '" + key + "' must be text"
    if "timeout" in connection:
        timeout = connection["timeout"]
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0:
            return who + ": 'timeout' must be a number of seconds, at least 0 (got " + repr(timeout) + ")"
    if "extra_args" in connection:
        problem = _string_list_problem(connection["extra_args"])
        if problem:
            return who + ": 'extra_args' " + problem
    if "env" in connection:
        problem = _env_problem(connection["env"])
        if problem:
            return who + ": 'env' " + problem
    if "backend_options" in connection:
        problem = _options_problem(llm_backends.backend_of(connection), connection["backend_options"])
        if problem:
            return who + ": 'backend_options' " + problem
    return None


def validate_backend(config: Dict[str, Any], name: str) -> Optional[str]:
    """Why the ``backends`` section of ``name`` cannot be used, or None if it can (or there is none)."""
    backends = config.get("backends") or {}
    if not isinstance(backends, dict) or name not in backends:
        return None
    who = "backend '" + name + "'"
    if llm_backends.unknown_backends([name]):
        return who + " is not known. Known backends: " + ", ".join(llm_backends.available_backends())
    section = backends[name]
    if not isinstance(section, dict):
        return who + " is not an object"
    if "binary" in section and not isinstance(section["binary"], str):
        return who + ": 'binary' must be text"
    if "extra_args" in section:
        problem = _string_list_problem(section["extra_args"])
        if problem:
            return who + ": 'extra_args' " + problem
    if "env" in section:
        problem = _env_problem(section["env"])
        if problem:
            return who + ": 'env' " + problem
    if "options" in section:
        problem = _options_problem(name, section["options"])
        if problem:
            return who + ": 'options' " + problem
    return None


def validate_config(config: Dict[str, Any]) -> List[str]:
    """Every problem of the configuration, as messages; empty means it can be saved."""
    problems: List[str] = []
    for key in ("connections", "backends"):
        if not isinstance(config.get(key, {}), dict):
            problems.append("'" + key + "' must be an object")
    if problems:
        return problems
    for name in sorted(config.get("backends") or {}):
        error = validate_backend(config, name)
        if error is not None:
            problems.append(error)
    for name in connection_names(config):
        error = validate_connection(config, name)
        if error is not None:
            problems.append(error)
    return problems

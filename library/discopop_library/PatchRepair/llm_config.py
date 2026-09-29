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
    used when there is exactly one, and otherwise an implicit connection through the
    first installed agent. ``backend_override`` and ``model_override`` come from the
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
        if connections:
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

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""What the "LLM Agent" box of the Patch Repair and the Suggestion Check tabs shows, as data.

Both tools read the same LLM configuration (``<.discopop>/patch_repair/llm_config.json``,
``PatchRepair/llm_config.py``): the stored connections offered by the connection selector, what a selected one resolves
to, and the install section of a backend (its executable), which the backend's version and model list are queried
with. Toolkit independent.
"""

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

# the first entry of the connection selector: no stored connection, the backend and the model are chosen in the panel
NO_CONNECTION = "(choose backend and model below)"


def llm_config_path(dot_dp: str) -> str:
    """The LLM configuration patch repair and the suggestion check share (``patch_repair/llm_config.json``)."""
    from discopop_library.PatchRepair import llm_config

    return llm_config.default_config_path(os.path.join(dot_dp, "patch_repair"))


def load_connections(dot_dp: str) -> Tuple[List[str], str]:
    """(the names of the stored connections, "" or why the configuration cannot be read)."""
    from discopop_library.PatchRepair import llm_config

    try:
        config = llm_config.load_config(llm_config_path(dot_dp))
    except ValueError as error:
        return [], str(error)
    return llm_config.connection_names(config), ""


def backend_section(dot_dp: str, backend: str) -> Dict[str, Any]:
    """The install section of ``backend`` (Settings > LLM backends: its executable, ...), which its version and
    model list are queried with; empty when there is none or the configuration cannot be read (the connection
    selector reports that)."""
    from discopop_library.PatchRepair import llm_config

    try:
        config = llm_config.load_config(llm_config_path(dot_dp))
    except ValueError:
        return {}
    return llm_config.backend_defaults(config, backend)


def connection_choices(names: Sequence[str]) -> List[str]:
    """The entries of the connection selector: choosing in the panel first, then the stored connections."""
    return [NO_CONNECTION] + [str(n) for n in names]


def manual_choice_note(names: Sequence[str], shared_with: str = "patch repair") -> str:
    """What choosing the backend and the model in the panel means with these stored connections; ``shared_with``
    names the other tool that reads the configuration."""
    if len(names) == 1:
        return (
            "The backend and the model below override those of the only stored connection, "
            + str(names[0])
            + "; its other settings apply, an empty model is its model."
        )
    return "Stored connections are shared with " + shared_with + " (patch_repair/llm_config.json)."


@dataclass(frozen=True)
class ConnectionInfo:
    """What a stored connection resolves to, for the read-only backend and model fields."""

    backend: str = ""
    model: str = ""
    description: str = ""
    error: str = ""


def resolve_connection(dot_dp: str, name: str) -> ConnectionInfo:
    """The backend, model and description of the stored connection ``name``, or why it cannot be resolved."""
    from discopop_library.PatchRepair import llm_backends, llm_config

    try:
        config = llm_config.load_config(llm_config_path(dot_dp))
        profile = llm_config.resolve_connection(config, name=name)
    except ValueError as error:
        return ConnectionInfo(error=str(error))
    return ConnectionInfo(
        llm_backends.backend_of(profile),
        str(profile.get("model") or "").strip(),
        llm_config.describe_connection(profile),
    )


def backend_description(version: str, description: str) -> str:
    """The line under the backend selector: its version and the first line of its description."""
    return (version + " -- " if version else "") + description.split("\n")[0]

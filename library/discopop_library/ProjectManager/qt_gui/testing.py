# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Helpers for the widget tests of the Qt GUI (imported by the tests only)."""

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from discopop_library.PatchRepair import llm_backends
from discopop_library.PatchRepair.llm_backends import FieldSpec
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments


def make_arguments(project_root: Path) -> ProjectManagerArguments:
    """The arguments of ``discopop_project_manager --gui --gui-toolkit qt`` for a project in ``project_root``."""
    (project_root / ".discopop" / "project" / "configs").mkdir(parents=True, exist_ok=True)
    return ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(project_root),
        full_execute=False,
        list=False,
        execute_configurations="",
        execute_inplace=False,
        skip_cleanup=False,
        generate_report=False,
        show_report=False,
        initialize_directory=False,
        apply_suggestions=None,
        reset=False,
        reset_execution_results=False,
        gui=True,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
        gui_toolkit="qt",
    )


# ---- fake LLM backends (settings dialogs, panels) ----

ALPHA_FIELDS = (
    FieldSpec("agent", "Agent", "agent to drive", default=""),
    FieldSpec("effort", "Effort", "how hard", kind="choice", choices=("", "low", "high"), default=""),
    FieldSpec("auto", "Approve tools", "pass --auto", kind="bool", default=False),
)
BETA_FIELDS = (FieldSpec("system", "System prompt", "", default="be brief"),)


def fake_backend(
    name: str,
    fields: Any = (),
    version: Optional[str] = "v1.0",
    models: Optional[List[str]] = None,
    exhaustive: bool = True,
    gate: Optional[threading.Event] = None,
) -> Any:
    """A backend module as the registry holds it; records the configuration sections it was probed with."""
    probed: List[Dict[str, Any]] = []

    def binary(config: Optional[Dict[str, Any]] = None) -> str:
        return str((config or {}).get("binary") or name)

    def probe_version(config: Optional[Dict[str, Any]] = None) -> Optional[str]:
        probed.append(dict(config or {}))
        if gate is not None:
            gate.wait(10)
        return version

    return SimpleNamespace(
        NAME=name,
        DESCRIPTION=f"The {name} agent.",
        DEFAULT_BINARY=name,
        BINARY_ENV_VAR=f"FAKE_{name.upper()}",
        INSTALL_HINT=f"install {name}",
        MODELS_ARE_EXHAUSTIVE=exhaustive,
        FIELDS=tuple(fields),
        binary=binary,
        version=probe_version,
        available=lambda config=None: version is not None,
        list_models=lambda config=None: list(models if models is not None else [name + "/m1", name + "/m2"]),
        probed=probed,
    )


def install_fake_backends(monkeypatch: pytest.MonkeyPatch, **backends: Any) -> Dict[str, Any]:
    """Replace the registry of LLM backends by ``backends`` (default: "alpha" with three fields, "beta" with one and
    a non-exhaustive model list), so no test runs a real agent."""
    registry = backends or {
        "alpha": fake_backend("alpha", ALPHA_FIELDS),
        "beta": fake_backend("beta", BETA_FIELDS, exhaustive=False),
    }
    monkeypatch.setattr(llm_backends, "BACKENDS", registry)
    monkeypatch.setattr(llm_backends, "DEFAULT_BACKEND", next(iter(registry)))
    monkeypatch.setattr(llm_backends, "first_installed_backend", lambda: next(iter(registry)))
    for name in registry:
        monkeypatch.delenv(f"FAKE_{name.upper()}", raising=False)
    return registry

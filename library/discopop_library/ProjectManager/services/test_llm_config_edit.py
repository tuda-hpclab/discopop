# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import Any, Dict

import pytest

from discopop_library.PatchRepair.llm_backends import FieldSpec
from discopop_library.ProjectManager.services import llm_config_edit as edit

SPECS = (
    FieldSpec("agent", "Agent"),
    FieldSpec("effort", "Effort", kind="choice", choices=("", "low", "high")),
    FieldSpec("auto", "Auto", kind="bool", default=False),
)


def test_extra_args_respect_quotes_and_round_trip() -> None:
    args = edit.parse_extra_args("--flag 'a b' x")
    assert args == ["--flag", "a b", "x"]
    assert edit.parse_extra_args(edit.format_extra_args(args)) == args
    assert edit.parse_extra_args("   ") == []
    with pytest.raises(ValueError):
        edit.parse_extra_args("--flag 'unbalanced")


def test_env_lines_are_parsed_and_formatted() -> None:
    assert edit.parse_env("# comment\n\nA=1\n B = x=y \n") == {"A": "1", "B": "x=y"}
    assert edit.format_env({"B": "2", "A": "1"}) == "A=1\nB=2\n"
    with pytest.raises(ValueError):
        edit.parse_env("NOEQUALS")
    with pytest.raises(ValueError):
        edit.parse_env("=value")


def test_options_drop_empty_values_and_type_booleans() -> None:
    values = {"agent": "  ", "effort": "high", "auto": "yes"}
    assert edit.options_from_form(SPECS, values) == {"effort": "high", "auto": True}
    assert edit.options_from_form(SPECS, {"auto": "no"}) == {"auto": False}
    assert edit.options_from_form(SPECS, {}) == {}


def test_options_keep_undeclared_keys() -> None:
    stored: Dict[str, Any] = {"agent": "a", "retired": 3}
    assert edit.undeclared_options(SPECS, stored) == {"retired": 3}
    assert edit.options_from_form(SPECS, {"agent": "b"}, {"retired": 3}) == {"agent": "b", "retired": 3}


def test_options_to_form_shows_booleans_as_words_and_unset_as_empty() -> None:
    texts = edit.options_to_form(SPECS, {"auto": False, "effort": "low"})
    assert texts == {"agent": "", "effort": "low", "auto": "no"}


def test_connection_round_trip_and_unedited_keys_are_kept() -> None:
    base: Dict[str, Any] = {"backend": "claude", "model": "m", "future_key": 7, "agent": "legacy"}
    form = edit.connection_to_form(base, SPECS, {"agent": "legacy"})
    assert form.backend == "claude" and form.options["agent"] == "legacy"
    form.prompts = "3"
    form.timeout = "60"
    form.extra_args = "--x 'a b'"
    form.env = "K=V"
    form.description = ""
    stored = edit.connection_from_form(form, SPECS, base)
    assert stored == {
        "backend": "claude",
        "model": "m",
        "future_key": 7,
        "prompts": 3,
        "timeout": 60,
        "extra_args": ["--x", "a b"],
        "env": {"K": "V"},
        "backend_options": {"agent": "legacy"},
    }


def test_connection_drops_emptied_values() -> None:
    base: Dict[str, Any] = {"backend": "claude", "model": "m", "retries": 2, "env": {"A": "1"}}
    form = edit.connection_to_form(base, SPECS, {})
    form.model = ""
    form.retries = ""
    form.env = ""
    assert edit.connection_from_form(form, SPECS, base) == {"backend": "claude"}


@pytest.mark.parametrize(
    "field_name, value",
    [("prompts", "0"), ("prompts", "x"), ("retries", "-1"), ("timeout", "0"), ("timeout", "soon"), ("env", "bad")],
)
def test_connection_rejects_invalid_values(field_name: str, value: str) -> None:
    form = edit.ConnectionForm(backend="claude")
    setattr(form, field_name, value)
    with pytest.raises(ValueError):
        edit.connection_from_form(form, SPECS)


def test_backend_section_round_trip_and_empty_section() -> None:
    section: Dict[str, Any] = {
        "binary": "/opt/agent",
        "extra_args": ["-v"],
        "env": {"A": "1"},
        "options": {"auto": True},
    }
    form = edit.backend_to_form(section, SPECS)
    assert form.binary == "/opt/agent" and form.options["auto"] == "yes"
    assert edit.backend_from_form(form, SPECS, section) == section
    assert edit.backend_from_form(edit.BackendForm(), SPECS, section) == {}


def test_backend_section_keeps_undeclared_options() -> None:
    section: Dict[str, Any] = {"options": {"retired": 1}}
    form = edit.backend_to_form(section, SPECS)
    form.options["agent"] = "x"
    assert edit.backend_from_form(form, SPECS, section) == {"options": {"retired": 1, "agent": "x"}}


def test_connection_names_are_validated() -> None:
    assert edit.validate_connection_name("fast", ["slow"]) is None
    assert edit.validate_connection_name("  ", []) is not None
    assert edit.validate_connection_name("slow", ["slow"]) is not None
    assert edit.validate_connection_name("backend", []) is not None

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for the validation of the LLM configuration (what the GUI refuses to save) and its round trip."""

from pathlib import Path
from typing import Any, Dict

import pytest

from discopop_library.PatchRepair import llm_config


def _config(**sections: Any) -> Dict[str, Any]:
    config = llm_config.empty_config()
    config.update(sections)
    return config


def test_an_empty_configuration_is_valid() -> None:
    assert llm_config.validate_config(llm_config.empty_config()) == []


def test_a_complete_connection_and_backend_are_valid() -> None:
    config = _config(
        connections={
            "fast": {
                "description": "the cheap one",
                "backend": "opencode",
                "model": "openai/gpt-5.4-mini",
                "timeout": 120,
                "extra_args": ["--print-logs"],
                "env": {"A": "1"},
                "backend_options": {"agent": "build", "auto": False},
            }
        },
        backends={
            "claude": {"binary": "/opt/claude", "extra_args": [], "env": {}, "options": {"effort": "high"}},
        },
    )
    assert llm_config.validate_config(config) == []


def test_blank_backend_and_model_are_allowed() -> None:
    # blank backend: the first installed agent; blank model: the backend's default
    config = _config(connections={"any": {"backend": "", "model": ""}})
    assert llm_config.validate_connection(config, "any") is None


@pytest.mark.parametrize(
    "connection, fragment",
    [
        ({"backend": "nonsense"}, "unknown backend 'nonsense'"),
        ({"model": 5}, "'model' must be text"),
        ({"timeout": -1}, "'timeout'"),
        ({"timeout": "60"}, "'timeout'"),
        ({"timeout": True}, "'timeout'"),
        ({"extra_args": "--a --b"}, "'extra_args' must be a list of strings"),
        ({"extra_args": [1]}, "'extra_args' must be a list of strings"),
        ({"env": ["A=1"]}, "'env' must be an object of strings"),
        ({"env": {"A": 1}}, "'env' must be an object of strings"),
        ({"backend": "claude", "backend_options": {"effort": "extreme"}}, "does not accept"),
        ({"backend": "opencode", "backend_options": {"auto": "yes"}}, "not true or false"),
        ({"backend": "opencode", "backend_options": {"agent": 3}}, "not text"),
        ({"backend_options": []}, "'backend_options' must be an object"),
    ],
)
def test_invalid_connections_are_named(connection: Dict[str, Any], fragment: str) -> None:
    config = _config(connections={"c": connection})
    error = llm_config.validate_connection(config, "c")
    assert error is not None and fragment in error and "connection 'c'" in error
    assert llm_config.validate_config(config) == [error]


def test_a_missing_or_malformed_connection() -> None:
    assert "no LLM connection named 'x'" in str(llm_config.validate_connection(llm_config.empty_config(), "x"))
    assert "is not an object" in str(llm_config.validate_connection(_config(connections={"x": []}), "x"))


def test_options_of_a_backend_the_connection_does_not_use_are_checked_against_its_own_backend() -> None:
    # "effort" is claude's choice field; opencode declares no such field, so any value is kept as is
    config = _config(connections={"c": {"backend": "opencode", "backend_options": {"effort": "extreme"}}})
    assert llm_config.validate_connection(config, "c") is None


@pytest.mark.parametrize(
    "section, fragment",
    [
        ({"binary": 3}, "'binary' must be text"),
        ({"extra_args": "x"}, "'extra_args' must be a list of strings"),
        ({"env": {"A": None}}, "'env' must be an object of strings"),
        ({"options": {"effort": "extreme"}}, "does not accept"),
        ({"options": "high"}, "'options' must be an object"),
        ("claude", "is not an object"),
    ],
)
def test_invalid_backend_sections_are_named(section: Any, fragment: str) -> None:
    config = _config(backends={"claude": section})
    error = llm_config.validate_backend(config, "claude")
    assert error is not None and fragment in error and "backend 'claude'" in error


def test_an_unknown_backend_section_and_a_missing_one() -> None:
    assert "is not known" in str(llm_config.validate_backend(_config(backends={"gpt": {}}), "gpt"))
    assert llm_config.validate_backend(llm_config.empty_config(), "claude") is None


def test_sections_that_are_not_objects() -> None:
    assert llm_config.validate_config(_config(connections=[], backends="x")) == [
        "'connections' must be an object",
        "'backends' must be an object",
    ]


def test_all_problems_are_reported_backends_first() -> None:
    config = _config(
        connections={"b": {"timeout": -2}, "a": {"backend": "nonsense"}},
        backends={"opencode": {"binary": 1}},
    )
    problems = llm_config.validate_config(config)
    assert len(problems) == 3
    assert problems[0].startswith("backend 'opencode'")
    assert problems[1].startswith("connection 'a'") and problems[2].startswith("connection 'b'")


def test_backend_options_saved_in_the_backends_section_reach_the_resolved_connection(tmp_path: Path) -> None:
    path = str(tmp_path / "llm_config.json")
    config = _config(
        connections={"c": {"backend": "claude", "model": "opus", "timeout": 30}},
        backends={"claude": {"options": {"effort": "high"}, "extra_args": ["--x"], "env": {"A": "1"}}},
    )
    assert llm_config.validate_config(config) == []
    llm_config.save_config(path, config)
    profile = llm_config.resolve_connection(llm_config.load_config(path), "c")
    assert profile["backend_options"]["effort"] == "high"
    assert profile["extra_args"] == ["--x"]
    assert profile["env"] == {"A": "1"}
    assert profile["timeout"] == 30


# ---- which connection a run uses -----------------------------------------------------------------------------

_TWO = {
    "connections": {
        "a": {"backend": "opencode", "model": "m/a", "timeout": 5, "env": {"A": "1"}},
        "b": {"backend": "claude", "model": "opus"},
    },
    "backends": {"claude": {"binary": "/opt/claude", "options": {"effort": "high"}}},
}


def test_several_connections_and_a_backend_override_ask_that_backend_directly() -> None:
    profile = llm_config.resolve_connection(_config(**_TWO), backend_override="claude", model_override="sonnet")
    assert profile["name"] == llm_config.IMPLICIT_CONNECTION_NAME
    assert profile["backend"] == "claude" and profile["model"] == "sonnet"
    assert "timeout" not in profile and profile["env"] == {}
    # the install section of the backend still applies
    assert profile["backend_config"]["binary"] == "/opt/claude"
    assert profile["backend_options"]["effort"] == "high"
    no_model = llm_config.resolve_connection(_config(**_TWO), backend_override="opencode")
    assert not no_model.get("model")


def test_several_connections_without_a_name_or_backend_are_refused() -> None:
    with pytest.raises(ValueError, match="several connections"):
        llm_config.resolve_connection(_config(**_TWO))
    with pytest.raises(ValueError, match="several connections"):
        llm_config.resolve_connection(_config(**_TWO), model_override="x")


def test_a_single_connection_is_used_with_the_overrides_applied() -> None:
    config = _config(connections={"only": {"backend": "opencode", "model": "m", "timeout": 7}})
    profile = llm_config.resolve_connection(config, backend_override="claude")
    assert profile["name"] == "only" and profile["backend"] == "claude"
    assert profile["model"] == "m" and profile["timeout"] == 7

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of the toolkit-free logic of the LLM configuration dialogs, over two fake backends (no agent is run)."""

from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from discopop_library.PatchRepair import llm_config
from discopop_library.ProjectManager.qt_gui import llm_logic
from discopop_library.ProjectManager.qt_gui.testing import ALPHA_FIELDS, BETA_FIELDS, install_fake_backends


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    return install_fake_backends(monkeypatch)


def _spec(key: str) -> Any:
    return next(spec for spec in ALPHA_FIELDS + BETA_FIELDS if spec.key == key)


# ---- environment, arguments ----------------------------------------------------------------------------------


def test_env_round_trip_skips_blank_and_comment_lines() -> None:
    env, error = llm_logic.parse_env("B=2\n\n# a comment\n A = 1 \nC=x=y\n")
    assert error is None and env == {"A": "1", "B": "2", "C": "x=y"}
    assert llm_logic.format_env(env) == "A=1\nB=2\nC=x=y\n"
    assert llm_logic.format_env(None) == "" and llm_logic.format_env(["A=1"]) == ""


@pytest.mark.parametrize("text, fragment", [("JUSTANAME", "not KEY=VALUE"), ("=value", "no name")])
def test_bad_env_lines_are_named(text: str, fragment: str) -> None:
    env, error = llm_logic.parse_env("A=1\n" + text)
    assert env is None and error is not None and fragment in error and text in error


def test_format_args() -> None:
    assert llm_logic.format_args(["--a", "b"]) == "--a b"
    assert llm_logic.format_args("--a") == ""


# ---- fields ---------------------------------------------------------------------------------------------------


def test_field_texts_and_choices() -> None:
    assert llm_logic.field_text(None) == "" and llm_logic.field_text("") == ""
    assert llm_logic.field_text(True) == "yes" and llm_logic.field_text(False) == "no"
    assert llm_logic.field_text(3) == "3"
    assert llm_logic.field_choices(_spec("auto")) == ("", "yes", "no")
    # the blank (= inherit) comes first and only once, even when the backend lists it among its choices
    assert llm_logic.field_choices(_spec("effort")) == ("", "low", "high")
    assert llm_logic.field_choices(_spec("agent")) is None


def test_field_values_leave_blanks_out_and_make_booleans() -> None:
    values = llm_logic.field_values(ALPHA_FIELDS, {"agent": "  build ", "effort": "", "auto": "no"})
    assert values == {"agent": "build", "auto": False}
    assert llm_logic.field_values(ALPHA_FIELDS, {"auto": "yes"}) == {"auto": True}


def test_field_hint_names_what_blank_stands_for() -> None:
    assert llm_logic.field_hint(_spec("agent"), {"agent": "plan"}) == "agent to drive; blank = plan"
    assert llm_logic.field_hint(_spec("agent"), {"agent": ""}) == "agent to drive; blank = unset"
    assert llm_logic.field_hint(_spec("system"), {"system": "be brief"}) == "blank = be brief"
    assert llm_logic.field_hint(_spec("auto"), {"auto": False}) == "pass --auto; blank = no"


def test_inherited_defaults_come_from_the_backend_options_then_the_field() -> None:
    config = {"backends": {"alpha": {"options": {"effort": "high"}}}}
    assert llm_logic.inherited_defaults(config, "alpha") == {"agent": "", "effort": "high", "auto": False}
    assert llm_logic.inherited_defaults({"backends": {"alpha": "broken"}}, "alpha")["effort"] == ""
    assert llm_logic.inherited_defaults({}, "unknown") == {}


# ---- connections ----------------------------------------------------------------------------------------------


def test_stored_connection_is_the_connection_as_written() -> None:
    config = {"connections": {"c": {"backend": "alpha", "model": "m"}}}
    stored = llm_logic.stored_connection(config, "c")
    assert stored == {"backend": "alpha", "model": "m"}
    stored["model"] = "changed"
    assert config["connections"]["c"]["model"] == "m"  # a copy
    assert llm_logic.stored_connection(config, None) == {}
    assert llm_logic.stored_connection(config, "missing") == {}


def test_connection_backend_falls_back_to_the_default() -> None:
    assert llm_logic.connection_backend({"backend": "beta"}) == "beta"
    assert llm_logic.connection_backend({"backend": "gone"}) == "alpha"
    assert llm_logic.connection_backend({}) == "alpha"


@pytest.mark.parametrize(
    "text, value, error",
    [("", None, None), (" 60 ", 60.0, None), ("1.5", 1.5, None), ("x", None, "number"), ("-1", None, "negative")],
)
def test_parse_timeout(text: str, value: Optional[float], error: Optional[str]) -> None:
    parsed, problem = llm_logic.parse_timeout(text)
    assert parsed == value
    assert (problem is None) if error is None else (problem is not None and error in problem)


def test_build_connection_leaves_a_blank_timeout_out() -> None:
    texts = {"description": " d ", "model": " m ", "timeout": "", "extra_args": "--a  --b"}
    connection, error = llm_logic.build_connection(texts, "alpha", {"agent": "x"}, {"A": "1"})
    assert error is None
    assert connection == {
        "description": "d",
        "backend": "alpha",
        "model": "m",
        "extra_args": ["--a", "--b"],
        "env": {"A": "1"},
        "backend_options": {"agent": "x"},
    }
    connection, _ = llm_logic.build_connection(dict(texts, timeout="90"), "alpha", {}, {})
    assert connection is not None and connection["timeout"] == 90 and isinstance(connection["timeout"], int)
    connection, error = llm_logic.build_connection(dict(texts, timeout="soon"), "alpha", {}, {})
    assert connection is None and error is not None


def test_store_connection_keeps_foreign_keys_drops_flat_backend_keys_and_a_cleared_timeout() -> None:
    config: Dict[str, Any] = {
        "connections": {"c": {"backend": "beta", "timeout": 30, "system": "old flat", "agent": "x", "note": "kept"}}
    }
    connection, _ = llm_logic.build_connection({"model": "m"}, "alpha", {"effort": "low"}, {})
    assert connection is not None
    assert llm_logic.store_connection(config, "c", connection) is None
    assert config["connections"]["c"] == {
        "description": "",
        "backend": "alpha",
        "model": "m",
        "extra_args": [],
        "env": {},
        "backend_options": {"effort": "low"},
        "note": "kept",
    }


def test_store_connection_returns_the_validation_error_capitalized() -> None:
    config: Dict[str, Any] = {"connections": {}}
    connection, _ = llm_logic.build_connection({}, "alpha", {"effort": "extreme"}, {})
    assert connection is not None
    error = llm_logic.store_connection(config, "c", connection)
    assert error is not None and error.startswith("Connection 'c'") and "does not accept" in error


def test_new_and_copied_connections() -> None:
    config: Dict[str, Any] = {}
    config.setdefault("connections", {})["a"] = llm_logic.new_connection("beta")
    assert llm_config.validate_connection(config, "a") is None
    config["connections"]["a"]["env"] = {"A": "1"}
    llm_logic.copy_connection(config, "a", "b")
    assert config["connections"]["b"] == config["connections"]["a"]
    config["connections"]["b"]["env"]["A"] = "2"  # not shared
    assert config["connections"]["a"]["env"] == {"A": "1"}


# ---- backends -------------------------------------------------------------------------------------------------


def test_build_backend_section_leaves_empty_values_out() -> None:
    assert llm_logic.build_backend_section(" ", "", {}, {}) == {}
    assert llm_logic.build_backend_section(" /bin/a ", "-x -y", {"A": "1"}, {"agent": "b"}) == {
        "binary": "/bin/a",
        "extra_args": ["-x", "-y"],
        "env": {"A": "1"},
        "options": {"agent": "b"},
    }


def test_store_backend_writes_options_where_resolve_connection_reads_them() -> None:
    config = llm_config.empty_config()
    config["connections"]["c"] = {"backend": "alpha"}
    section = llm_logic.build_backend_section("", "", {}, {"effort": "high"})
    assert llm_logic.store_backend(config, "alpha", section) is None
    assert llm_config.resolve_connection(config, "c")["backend_options"]["effort"] == "high"


def test_store_backend_removes_an_empty_section_and_keeps_foreign_keys() -> None:
    config: Dict[str, Any] = {"backends": {"alpha": {"binary": "/x"}, "beta": {"binary": "/y", "note": 1}}}
    assert llm_logic.store_backend(config, "alpha", {}) is None
    assert "alpha" not in config["backends"]
    assert llm_logic.store_backend(config, "beta", {}) is None
    assert config["backends"]["beta"] == {"note": 1}


def test_store_backend_reports_invalid_options() -> None:
    config: Dict[str, Any] = {}
    error = llm_logic.store_backend(config, "alpha", {"options": {"effort": "extreme"}})
    assert error is not None and error.startswith("Backend 'alpha'")


def test_binary_probe_and_status(monkeypatch: pytest.MonkeyPatch, fakes: Dict[str, Any]) -> None:
    assert llm_logic.binary_probe("alpha", " /opt/alpha ") == ("/opt/alpha", "v1.0")
    assert fakes["alpha"].probed[-1] == {"binary": "/opt/alpha"}
    assert llm_logic.binary_status("alpha", "/opt/alpha", "v1.0", {}) == "found: /opt/alpha (v1.0)"
    assert llm_logic.binary_status("alpha", "alpha", None, {}) == "not found: alpha could not be run"
    status = llm_logic.binary_status("alpha", "/env/alpha", "v2", {"FAKE_ALPHA": "/env/alpha"})
    assert status == "$FAKE_ALPHA overrides this: found: /env/alpha (v2)"


def test_backend_hint_and_model_note() -> None:
    config = {"backends": {"alpha": {"binary": "/opt/alpha"}}}
    assert llm_logic.backend_hint(config, "alpha", "v1.0") == "/opt/alpha (v1.0)"
    hint = llm_logic.backend_hint(config, "alpha", None)
    assert hint.startswith("NOT FOUND: /opt/alpha") and "LLM backends" in hint and "install alpha" in hint
    assert "lists" in llm_logic.model_note("alpha") and "suggestions only" in llm_logic.model_note("beta")
    assert "suggestions only" in llm_logic.model_note("unknown")


# ---- files ----------------------------------------------------------------------------------------------------


def test_merge_section_replaces_only_the_dialogs_section() -> None:
    on_disk = {"version": 1, "connections": {"a": {}}, "backends": {"alpha": {"binary": "/new"}}, "extra": 1}
    edited = {"connections": {"b": {}}, "backends": {"alpha": {"binary": "/stale"}}}
    merged = llm_logic.merge_section(on_disk, edited, "connections")
    assert merged == {"version": 1, "connections": {"b": {}}, "backends": {"alpha": {"binary": "/new"}}, "extra": 1}


def test_config_path_and_connection_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(llm_config.CONFIG_ENV_VAR, raising=False)
    dot_dp = str(tmp_path / ".discopop")
    path = llm_logic.config_path(dot_dp)
    assert path == str(tmp_path / ".discopop" / "patch_repair" / "llm_config.json")
    assert llm_logic.read_connection_names(dot_dp) == ([], None)
    llm_config.save_config(path, {"connections": {"b": {}, "a": {}}})
    assert llm_logic.read_connection_names(dot_dp) == (["a", "b"], None)
    Path(path).write_text("{broken")
    names, error = llm_logic.read_connection_names(dot_dp)
    assert names == [] and error is not None and "Could not read" in error
    monkeypatch.setenv(llm_config.CONFIG_ENV_VAR, str(tmp_path / "elsewhere.json"))
    assert llm_logic.config_path(dot_dp) == str(tmp_path / "elsewhere.json")


def test_a_blank_backend_is_not_written() -> None:
    connection, error = llm_logic.build_connection({"model": "m"}, "", {}, {})
    assert error is None and connection is not None and "backend" not in connection
    config = {"connections": {"c": {"backend": "beta"}}}
    assert llm_logic.store_connection(config, "c", connection) is None
    assert "backend" not in config["connections"]["c"]

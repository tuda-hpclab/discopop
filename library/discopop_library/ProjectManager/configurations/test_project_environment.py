# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of the project wide environment (project_environment.json and the variables of a run)."""

import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from discopop_library.ProjectManager.configurations.project_environment import (
    PROJECT_ENVIRONMENT_FILE,
    ProjectEnvironment,
    ProjectEnvironmentError,
    build_environment,
    load_project_environment,
    ignored_settings_warning,
    migrate_settings_files,
    normalize_scope,
    resolve_project_variables,
    resolve_scope,
    save_project_environment,
    scope_variable_warning,
    scripts_using_scope_variable,
    validate_project_environment,
    write_default_project_environment,
)


def _write_json(path: Path, content: Any) -> None:
    path.write_text(json.dumps(content))


# ---- load / save


def test_load_default_when_missing(tmp_path: Path) -> None:
    assert load_project_environment(str(tmp_path)) == ProjectEnvironment(instrumentation_scope=".")


def test_save_load_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    save_project_environment(str(tmp_path), str(root), ProjectEnvironment(instrumentation_scope="src/"))
    assert json.loads((tmp_path / PROJECT_ENVIRONMENT_FILE).read_text()) == {"DP_PROJECT_ROOT_DIR": "src"}
    assert load_project_environment(str(tmp_path)).instrumentation_scope == "src"


def test_load_empty_scope_is_default(tmp_path: Path) -> None:
    _write_json(tmp_path / PROJECT_ENVIRONMENT_FILE, {"DP_PROJECT_ROOT_DIR": "  "})
    assert load_project_environment(str(tmp_path)).instrumentation_scope == "."


def test_load_object_without_scope_is_default(tmp_path: Path) -> None:
    _write_json(tmp_path / PROJECT_ENVIRONMENT_FILE, {})
    assert load_project_environment(str(tmp_path)).instrumentation_scope == "."


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[1, 2]",
        '"src"',
        '{"DP_PROJECT_ROOT_DIR": 3}',
        '{"OTHER": "x"}',
        '{"DP_PROJECT_ROOT_DIR": "a", "X": 1}',
    ],
    ids=["invalid_json", "list", "string", "non_string_scope", "unknown_key", "unknown_key_next_to_scope"],
)
def test_load_invalid_file_raises(tmp_path: Path, content: str) -> None:
    (tmp_path / PROJECT_ENVIRONMENT_FILE).write_text(content)
    with pytest.raises(ProjectEnvironmentError):
        load_project_environment(str(tmp_path))


def test_write_default_does_not_overwrite(tmp_path: Path) -> None:
    write_default_project_environment(str(tmp_path))
    assert json.loads((tmp_path / PROJECT_ENVIRONMENT_FILE).read_text()) == {"DP_PROJECT_ROOT_DIR": "."}
    _write_json(tmp_path / PROJECT_ENVIRONMENT_FILE, {"DP_PROJECT_ROOT_DIR": "src"})
    write_default_project_environment(str(tmp_path))
    assert json.loads((tmp_path / PROJECT_ENVIRONMENT_FILE).read_text()) == {"DP_PROJECT_ROOT_DIR": "src"}


# ---- normalize_scope


@pytest.mark.parametrize(
    "scope, expected",
    [
        ("src", "src"),
        ("src/", "src"),
        ("src/../lib/./", "lib"),
        ("", "."),
        ("   ", "."),
        (".", "."),
        ("src/sub/..", "src"),
    ],
)
def test_normalize_scope_relative(tmp_path: Path, scope: str, expected: str) -> None:
    assert normalize_scope(str(tmp_path), scope) == expected


def test_normalize_scope_absolute_inside_root_becomes_relative(tmp_path: Path) -> None:
    assert normalize_scope(str(tmp_path), str(tmp_path / "src") + "/") == "src"
    assert normalize_scope(str(tmp_path), str(tmp_path)) == "."


def test_normalize_scope_absolute_outside_root_stays_absolute(tmp_path: Path) -> None:
    root = tmp_path / "project"
    other = tmp_path / "other" / "lib"
    assert normalize_scope(str(root), str(other) + "/") == str(other)


def test_normalize_scope_sibling_with_common_prefix_is_outside(tmp_path: Path) -> None:
    root = tmp_path / "src"
    assert normalize_scope(str(root), str(tmp_path / "src_old")) == str(tmp_path / "src_old")


def test_normalize_scope_dotdot_leaving_root_is_absolute(tmp_path: Path) -> None:
    root = tmp_path / "project"
    assert normalize_scope(str(root), "../lib") == str(tmp_path / "lib")


# ---- validate_project_environment


def test_validate_existing_subdir_has_no_warnings(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert validate_project_environment(str(tmp_path), ProjectEnvironment("src")) == []
    assert validate_project_environment(str(tmp_path), ProjectEnvironment(".")) == []


def test_validate_not_existing_warns(tmp_path: Path) -> None:
    warnings = validate_project_environment(str(tmp_path), ProjectEnvironment("missing"))
    assert len(warnings) == 1
    assert "not an existing directory" in warnings[0]
    assert str(tmp_path / "missing") in warnings[0]


def test_validate_outside_root_warns(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "shared"
    outside.mkdir()
    warnings = validate_project_environment(str(root), ProjectEnvironment(str(outside)))
    assert len(warnings) == 1
    assert "outside the project root" in warnings[0]


def test_validate_outside_root_not_existing_warns_twice(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    warnings = validate_project_environment(str(root), ProjectEnvironment(str(tmp_path / "nowhere")))
    assert len(warnings) == 2


# ---- resolve_scope / resolve_project_variables


def test_resolve_scope_relative_is_rebased_into_run_root(tmp_path: Path) -> None:
    project = tmp_path / "project"
    run_root = tmp_path / "copy"
    assert resolve_scope(ProjectEnvironment("src"), str(project), str(run_root)) == str(run_root / "src") + "/"


def test_resolve_scope_absolute_inside_project_is_rebased(tmp_path: Path) -> None:
    project = tmp_path / "project"
    run_root = tmp_path / "copy"
    environment = ProjectEnvironment(str(project / "src"))
    assert resolve_scope(environment, str(project), str(run_root)) == str(run_root / "src") + "/"


def test_resolve_scope_absolute_outside_is_kept(tmp_path: Path) -> None:
    project = tmp_path / "project"
    run_root = tmp_path / "copy"
    environment = ProjectEnvironment(str(tmp_path / "shared" / "lib"))
    assert resolve_scope(environment, str(project), str(run_root)) == str(tmp_path / "shared" / "lib") + "/"


def test_resolve_scope_default_is_run_root_with_slash(tmp_path: Path) -> None:
    assert resolve_scope(ProjectEnvironment("."), str(tmp_path), str(tmp_path / "copy")) == str(tmp_path / "copy") + "/"
    assert resolve_scope(ProjectEnvironment("."), str(tmp_path), str(tmp_path)) == str(tmp_path) + "/"


def test_resolve_scope_has_trailing_slash_exactly_once(tmp_path: Path) -> None:
    value = resolve_scope(ProjectEnvironment("src/"), str(tmp_path), str(tmp_path))
    assert value.endswith("/") and not value.endswith("//")


def test_resolve_project_variables(tmp_path: Path) -> None:
    variables = resolve_project_variables(ProjectEnvironment("src"), str(tmp_path), str(tmp_path / "copy"))
    assert variables == {
        "DP_RUN_ROOT_DIR": str(tmp_path / "copy"),
        "DOT_DISCOPOP": str(tmp_path / "copy" / ".discopop"),
        "DP_PROJECT_ROOT_DIR": str(tmp_path / "copy" / "src") + "/",
    }


def test_resolve_project_variables_makes_relative_run_root_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    variables = resolve_project_variables(ProjectEnvironment("."), str(tmp_path), "rel")
    assert variables["DOT_DISCOPOP"] == str(tmp_path / "rel" / ".discopop")
    assert os.path.isabs(variables["DP_RUN_ROOT_DIR"])
    assert os.path.isabs(variables["DP_PROJECT_ROOT_DIR"])


# ---- build_environment


def test_build_environment_precedence(tmp_path: Path) -> None:
    base = {"A": "base", "B": "base", "DP_PROJECT_ROOT_DIR": "/inherited/", "DOT_DISCOPOP": "relative/.discopop"}
    settings = {"B": "settings", "C": "settings"}
    result = build_environment(base, settings, ProjectEnvironment("src"), str(tmp_path), str(tmp_path))
    assert result["A"] == "base"
    assert result["B"] == "settings"
    assert result["C"] == "settings"
    assert result["DP_PROJECT_ROOT_DIR"] == str(tmp_path / "src") + "/"
    assert result["DOT_DISCOPOP"] == str(tmp_path / ".discopop")
    assert result["DP_RUN_ROOT_DIR"] == str(tmp_path)


def test_build_environment_does_not_modify_inputs(tmp_path: Path) -> None:
    base: Dict[str, str] = {"A": "1"}
    settings: Dict[str, str] = {"B": "2"}
    build_environment(base, settings, ProjectEnvironment(), str(tmp_path), str(tmp_path))
    assert base == {"A": "1"}
    assert settings == {"B": "2"}


@pytest.mark.parametrize("key", ["DP_PROJECT_ROOT_DIR", "DOT_DISCOPOP", "DP_RUN_ROOT_DIR"])
def test_build_environment_overrides_reserved_key_of_settings(tmp_path: Path, key: str) -> None:
    result = build_environment({}, {"CC": "gcc", key: "x"}, ProjectEnvironment("src"), str(tmp_path), str(tmp_path))
    assert result["CC"] == "gcc"
    assert result[key] != "x"
    assert result["DP_PROJECT_ROOT_DIR"] == str(tmp_path / "src") + "/"
    assert result["DOT_DISCOPOP"] == str(tmp_path / ".discopop")
    assert result["DP_RUN_ROOT_DIR"] == str(tmp_path)


# ---- ignored_settings_warning


def test_ignored_settings_warning_none_without_reserved_keys() -> None:
    assert ignored_settings_warning({"CC": "gcc"}, "seq_settings.json") is None


@pytest.mark.parametrize("key", ["DP_PROJECT_ROOT_DIR", "DOT_DISCOPOP", "DP_RUN_ROOT_DIR"])
def test_ignored_settings_warning_names_key_and_file(key: str) -> None:
    warning = ignored_settings_warning({"CC": "gcc", key: "x"}, "dp_settings.json")
    assert warning is not None
    assert key in warning
    assert "dp_settings.json" in warning
    assert "CC" not in warning


def test_ignored_settings_warning_names_all_keys() -> None:
    warning = ignored_settings_warning({"DOT_DISCOPOP": "a", "DP_RUN_ROOT_DIR": "b"}, "x.json")
    assert warning is not None
    assert "DOT_DISCOPOP" in warning and "DP_RUN_ROOT_DIR" in warning


# ---- scripts_using_scope_variable / scope_variable_warning


def _script(path: Path, text: str) -> str:
    path.write_text(text)
    return str(path)


def test_scripts_using_scope_variable(tmp_path: Path) -> None:
    using = _script(tmp_path / "a.sh", 'cmake -S "$DP_PROJECT_ROOT_DIR"\n')
    other = _script(tmp_path / "b.sh", "echo hi $DP_RUN_ROOT_DIR\n")
    missing = str(tmp_path / "missing.sh")
    assert scripts_using_scope_variable([using, other, missing]) == [using]
    assert scripts_using_scope_variable([]) == []


def test_scripts_using_scope_variable_tolerates_binary_content(tmp_path: Path) -> None:
    path = tmp_path / "bin.sh"
    path.write_bytes(b"\xff\xfe DP_PROJECT_ROOT_DIR \x80")
    assert scripts_using_scope_variable([str(path)]) == [str(path)]


def _variables(root: Path, scope: str) -> Dict[str, str]:
    return resolve_project_variables(ProjectEnvironment(scope), str(root), str(root))


def test_scope_variable_warning_none_for_default_scope(tmp_path: Path) -> None:
    script = _script(tmp_path / "a.sh", "echo $DP_PROJECT_ROOT_DIR\n")
    assert scope_variable_warning(script, _variables(tmp_path, ".")) is None


def test_scope_variable_warning_none_if_script_does_not_use_it(tmp_path: Path) -> None:
    script = _script(tmp_path / "a.sh", "echo $DP_RUN_ROOT_DIR\n")
    assert scope_variable_warning(script, _variables(tmp_path, "src")) is None


def test_scope_variable_warning_for_narrowed_scope(tmp_path: Path) -> None:
    script = _script(tmp_path / "a.sh", "echo $DP_PROJECT_ROOT_DIR\n")
    warning = scope_variable_warning(script, _variables(tmp_path, "src"))
    assert warning is not None
    assert "a.sh" in warning
    assert "DP_RUN_ROOT_DIR" in warning
    assert str(tmp_path / "src") in warning


# ---- migrate_settings_files


def test_migrate_removes_reserved_keys_and_names_them(tmp_path: Path) -> None:
    _write_json(tmp_path / "seq_settings.json", {"CC": "clang", "DP_PROJECT_ROOT_DIR": "/old/src/"})

    messages = migrate_settings_files(str(tmp_path))

    assert json.loads((tmp_path / "seq_settings.json").read_text()) == {"CC": "clang"}
    assert len(messages) == 1
    assert "DP_PROJECT_ROOT_DIR=/old/src/" in messages[0]
    assert "seq_settings.json" in messages[0]


def test_migrate_never_writes_project_environment(tmp_path: Path) -> None:
    _write_json(tmp_path / "seq_settings.json", {"DP_PROJECT_ROOT_DIR": "/old/src/"})
    migrate_settings_files(str(tmp_path))
    assert not (tmp_path / PROJECT_ENVIRONMENT_FILE).exists()


def test_migrate_does_not_touch_existing_project_environment(tmp_path: Path) -> None:
    _write_json(tmp_path / PROJECT_ENVIRONMENT_FILE, {"DP_PROJECT_ROOT_DIR": "lib"})
    _write_json(tmp_path / "seq_settings.json", {"DP_PROJECT_ROOT_DIR": "/x/src/"})
    migrate_settings_files(str(tmp_path))
    assert json.loads((tmp_path / PROJECT_ENVIRONMENT_FILE).read_text()) == {"DP_PROJECT_ROOT_DIR": "lib"}


def test_migrate_strips_reserved_keys_from_all_settings_files(tmp_path: Path) -> None:
    names = ("seq_settings.json", "dp_settings.json", "hd_settings.json", "par_settings.json")
    for name in names:
        _write_json(
            tmp_path / name, {"KEEP": name, "DOT_DISCOPOP": "x", "DP_RUN_ROOT_DIR": "y", "DP_PROJECT_ROOT_DIR": "z"}
        )

    messages = migrate_settings_files(str(tmp_path))

    for name in names:
        assert json.loads((tmp_path / name).read_text()) == {"KEEP": name}
        assert not (tmp_path / (name + ".tmp")).exists()
    assert len(messages) == 4
    for message in messages:
        assert "DOT_DISCOPOP=x" in message and "DP_RUN_ROOT_DIR=y" in message and "DP_PROJECT_ROOT_DIR=z" in message


def test_migrate_noop_returns_empty_list(tmp_path: Path) -> None:
    _write_json(tmp_path / "seq_settings.json", {"CC": "gcc"})
    (tmp_path / "dp_settings.json").write_text("{broken")
    _write_json(tmp_path / "hd_settings.json", ["list"])
    assert migrate_settings_files(str(tmp_path)) == []
    assert json.loads((tmp_path / "seq_settings.json").read_text()) == {"CC": "gcc"}
    assert (tmp_path / "dp_settings.json").read_text() == "{broken"


def test_migrate_without_settings_files_is_noop(tmp_path: Path) -> None:
    assert migrate_settings_files(str(tmp_path)) == []

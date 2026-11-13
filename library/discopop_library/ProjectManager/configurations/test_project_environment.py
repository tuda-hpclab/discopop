# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of the project wide environment: the project directories and the variables of a run."""

import json
import os
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

from discopop_library.ProjectManager.configurations.project_environment import (
    INSTRUMENTED_DIRECTORIES_FILE,
    OBSOLETE_PROJECT_ENVIRONMENT_FILE,
    ProjectDirectories,
    build_environment,
    describe_project_variables,
    ignored_settings_warning,
    instrumented_directories,
    load_project_directories,
    migrate_settings_files,
    project_directories_of,
    record_instrumented_directories,
    resolve_project_variables,
    stale_directories_message,
    update_project_directories,
)
from discopop_library.ProjectManager.services.excluded_directories import save_excluded_directories
from discopop_library.ProjectManager.services.included_directories import save_included_directories


def _write_json(path: Path, content: Any) -> None:
    path.write_text(json.dumps(content))


@pytest.fixture
def project(tmp_path: Path) -> Tuple[Path, Path, Path]:
    """(project root, .discopop/project, a directory outside the project)."""
    root = tmp_path / "project"
    project_dir = root / ".discopop" / "project"
    project_dir.mkdir(parents=True)
    outside = tmp_path / "shared"
    outside.mkdir()
    return root, project_dir, outside


# ---- the stored lists


def test_nothing_stored_means_no_directories(project: Tuple[Path, Path, Path]) -> None:
    _root, project_dir, _outside = project
    assert load_project_directories(str(project_dir)) == ProjectDirectories()


def test_load_both_lists(project: Tuple[Path, Path, Path]) -> None:
    root, project_dir, outside = project
    save_excluded_directories(str(project_dir), ["build/_deps"])
    save_included_directories(str(project_dir), str(root), [str(outside)])
    assert load_project_directories(str(project_dir)) == ProjectDirectories((str(outside),), ("build/_deps",))


def test_command_line_overrides_replace_a_list(project: Tuple[Path, Path, Path]) -> None:
    root, project_dir, outside = project
    save_excluded_directories(str(project_dir), ["build/_deps"])
    save_included_directories(str(project_dir), str(root), [str(outside)])
    args = (str(project_dir), str(root))
    assert project_directories_of(*args, None, None) == ProjectDirectories((str(outside),), ("build/_deps",))
    assert project_directories_of(*args, "", "third_party:./lib/") == ProjectDirectories((), ("lib", "third_party"))
    # an override is normalized like a stored list: relative or inside entries of the include list are dropped
    assert project_directories_of(*args, f"rel:{root / 'src'}:{outside}/", None).included == (str(outside),)


# ---- the variables of a run


def test_resolve_project_variables_without_lists(tmp_path: Path) -> None:
    assert resolve_project_variables(ProjectDirectories(), str(tmp_path / "copy")) == {
        "DP_PROJECT_ROOT_DIR": str(tmp_path / "copy"),
        "DOT_DISCOPOP": str(tmp_path / "copy" / ".discopop"),
    }


def test_resolve_project_variables_with_lists(tmp_path: Path) -> None:
    directories = ProjectDirectories(("/opt/shared", "/srv/lib"), ("build/_deps", "third_party"))
    variables = resolve_project_variables(directories, str(tmp_path / "copy"))
    assert variables["DP_PROJECT_INCLUDE_DIRS"] == "/opt/shared:/srv/lib"
    # the excluded directories become absolute paths in the run root (the copy)
    copy = tmp_path / "copy"
    assert variables["DP_PROJECT_EXCLUDE_DIRS"] == f"{copy}/build/_deps:{copy}/third_party"


def test_resolve_project_variables_makes_a_relative_run_root_absolute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    variables = resolve_project_variables(ProjectDirectories(), "copy")
    assert variables["DP_PROJECT_ROOT_DIR"] == str(tmp_path / "copy")
    assert variables["DOT_DISCOPOP"] == str(tmp_path / "copy" / ".discopop")


def test_build_environment_layers(tmp_path: Path) -> None:
    base = {"PATH": "/bin", "DP_PROJECT_ROOT_DIR": "/elsewhere", "CC": "gcc"}
    settings: Dict[str, str] = {"CC": "clang", "DP_PROJECT_EXCLUDE_DIRS": "/opt/vendor"}
    directories = ProjectDirectories(("/opt/shared",), ("build/_deps",))
    environment = build_environment(base, settings, directories, str(tmp_path))
    assert environment["PATH"] == "/bin" and environment["CC"] == "clang"
    assert environment["DP_PROJECT_ROOT_DIR"] == str(tmp_path)  # inherited value overridden
    assert environment["DP_PROJECT_INCLUDE_DIRS"] == "/opt/shared"
    # entries of a settings file are kept in front of the stored ones
    assert environment["DP_PROJECT_EXCLUDE_DIRS"] == f"/opt/vendor:{tmp_path}/build/_deps"
    assert base["DP_PROJECT_ROOT_DIR"] == "/elsewhere" and "DP_PROJECT_INCLUDE_DIRS" not in settings


@pytest.mark.parametrize("key", ["DP_PROJECT_ROOT_DIR", "DOT_DISCOPOP"])
def test_build_environment_overrides_a_reserved_key_of_the_settings(tmp_path: Path, key: str) -> None:
    environment = build_environment({}, {key: "/somewhere/else"}, ProjectDirectories(), str(tmp_path))
    assert environment[key] != "/somewhere/else"


def test_describe_project_variables_names_all_four() -> None:
    line = describe_project_variables({"DP_PROJECT_ROOT_DIR": "/p", "DP_PROJECT_INCLUDE_DIRS": "/s"})
    assert (
        line == "Environment: DP_PROJECT_ROOT_DIR=/p DOT_DISCOPOP= DP_PROJECT_INCLUDE_DIRS=/s DP_PROJECT_EXCLUDE_DIRS="
    )


def test_ignored_settings_warning() -> None:
    assert ignored_settings_warning({"CC": "clang", "DP_PROJECT_EXCLUDE_DIRS": "x"}, "seq_settings.json") is None
    warning = ignored_settings_warning({"DOT_DISCOPOP": "x", "DP_PROJECT_ROOT_DIR": "y"}, "dp_settings.json")
    assert warning is not None
    assert "dp_settings.json" in warning and "DOT_DISCOPOP" in warning and "DP_PROJECT_ROOT_DIR" in warning


# ---- migration of the settings files


def test_migrate_removes_reserved_keys_and_names_them(tmp_path: Path) -> None:
    _write_json(tmp_path / "seq_settings.json", {"CC": "clang", "DP_PROJECT_ROOT_DIR": "/old/src/"})
    messages = migrate_settings_files(str(tmp_path))
    assert json.loads((tmp_path / "seq_settings.json").read_text()) == {"CC": "clang"}
    assert len(messages) == 1 and "DP_PROJECT_ROOT_DIR=/old/src/" in messages[0] and "seq_settings.json" in messages[0]


def test_migrate_strips_reserved_keys_from_all_settings_files(tmp_path: Path) -> None:
    names = ("seq_settings.json", "dp_settings.json", "hd_settings.json", "par_settings.json")
    for name in names:
        _write_json(tmp_path / name, {"KEEP": name, "DOT_DISCOPOP": "x", "DP_PROJECT_ROOT_DIR": "z"})
    messages = migrate_settings_files(str(tmp_path))
    for name in names:
        assert json.loads((tmp_path / name).read_text()) == {"KEEP": name}
        assert not (tmp_path / (name + ".tmp")).exists()
    assert len(messages) == 4


def test_migrate_noop_returns_empty_list(tmp_path: Path) -> None:
    _write_json(tmp_path / "seq_settings.json", {"CC": "gcc", "DP_PROJECT_EXCLUDE_DIRS": "build"})
    (tmp_path / "dp_settings.json").write_text("{broken")
    _write_json(tmp_path / "hd_settings.json", ["list"])
    assert migrate_settings_files(str(tmp_path)) == []
    assert (tmp_path / "dp_settings.json").read_text() == "{broken"


def test_migrate_names_the_obsolete_scope_file(tmp_path: Path) -> None:
    _write_json(tmp_path / OBSOLETE_PROJECT_ENVIRONMENT_FILE, {"DP_PROJECT_ROOT_DIR": "src"})
    messages = migrate_settings_files(str(tmp_path))
    assert len(messages) == 1 and "no longer read" in messages[0]
    assert (tmp_path / OBSOLETE_PROJECT_ENVIRONMENT_FILE).exists()  # the user decides what to do with it


# ---- the record of the instrumented data


def test_record_and_read_per_mode(tmp_path: Path) -> None:
    assert instrumented_directories(str(tmp_path), "dp") is None
    record_instrumented_directories(str(tmp_path), "dp", ProjectDirectories(("/s",), ("b",)))
    record_instrumented_directories(str(tmp_path), "hd", ProjectDirectories())
    assert instrumented_directories(str(tmp_path), "dp") == ProjectDirectories(("/s",), ("b",))
    assert instrumented_directories(str(tmp_path), "hd") == ProjectDirectories()


@pytest.mark.parametrize("content", ['{"dp": "src"}', "[1]", "{broken", '{"dp": {"included": [1], "excluded": []}}'])
def test_unusable_records_are_unknown(tmp_path: Path, content: str) -> None:
    (tmp_path / INSTRUMENTED_DIRECTORIES_FILE).write_text(content)
    assert instrumented_directories(str(tmp_path), "dp") is None


def test_record_overwrites_an_unusable_file(tmp_path: Path) -> None:
    (tmp_path / INSTRUMENTED_DIRECTORIES_FILE).write_text("{broken")
    record_instrumented_directories(str(tmp_path), "dp", ProjectDirectories())
    assert instrumented_directories(str(tmp_path), "dp") == ProjectDirectories()


def test_stale_message(project: Tuple[Path, Path, Path]) -> None:
    root, project_dir, outside = project
    dot_dp = str(root / ".discopop")
    assert stale_directories_message(dot_dp, "dp", str(project_dir)) is None  # nothing recorded
    record_instrumented_directories(dot_dp, "dp", ProjectDirectories((), ("build/_deps",)))
    save_excluded_directories(str(project_dir), ["build/_deps"])
    assert stale_directories_message(dot_dp, "dp", str(project_dir)) is None
    save_included_directories(str(project_dir), str(root), [str(outside)])
    message = stale_directories_message(dot_dp, "dp", str(project_dir))
    assert message is not None and "profiling" in message and str(outside) in message and "dp mode" in message
    assert stale_directories_message(dot_dp, "hd", str(project_dir)) is None  # nothing recorded for hd


# ---- updating the lists (MCP server)


def test_update_writes_only_changed_lists(project: Tuple[Path, Path, Path]) -> None:
    root, project_dir, outside = project
    (root / "build" / "_deps").mkdir(parents=True)
    directories, warnings = update_project_directories(str(project_dir), str(root), [str(outside)], ["build/_deps"])
    assert directories == ProjectDirectories((str(outside),), ("build/_deps",)) and warnings == []
    included_file = project_dir / "included_directories.json"
    os.utime(included_file, (1000.0, 1000.0))
    update_project_directories(str(project_dir), str(root), [str(outside) + "/"], None)
    assert included_file.stat().st_mtime == 1000.0  # unchanged: not written


def test_update_drops_unusable_entries_with_warnings(project: Tuple[Path, Path, Path]) -> None:
    root, project_dir, _outside = project
    directories, warnings = update_project_directories(
        str(project_dir), str(root), ["relative", str(root / "src"), "/does/not/exist"], ["/abs", "../up", "later"]
    )
    assert directories == ProjectDirectories((), ("later",))
    assert len(warnings) == 6
    assert any("does not exist (yet)" in warning and "later" in warning for warning in warnings)

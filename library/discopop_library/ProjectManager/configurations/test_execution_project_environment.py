# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""``execute_configuration``: the project environment of a run and the checks of instrumented runs."""

import json
import os
import shutil
import stat
from pathlib import Path
from typing import Dict, Optional, Tuple

import pytest

from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.configurations.execution import execute_configuration

ENV_SCRIPT = "#!/bin/bash\nenv | grep -E '^(DP_RUN_ROOT_DIR|DOT_DISCOPOP|DP_PROJECT_ROOT_DIR)='\n"


def _write_project(
    project_root: Path, script: str, settings_name: str = "seq_settings.json", settings: Optional[Dict[str, str]] = None
) -> None:
    config_dir = project_root / ".discopop" / "project" / "configs"
    (config_dir / "tiny").mkdir(parents=True)
    (config_dir / settings_name).write_text(json.dumps({"CC": "clang"} if settings is None else settings))
    for name in ("compile.sh", "execute.sh"):
        path = config_dir / "tiny" / name
        path.write_text(script)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)


def _set_scope(project_root: Path, scope: object) -> None:
    config_dir = project_root / ".discopop" / "project" / "configs"
    (config_dir / "project_environment.json").write_text(json.dumps({"DP_PROJECT_ROOT_DIR": scope}))


def _arguments(project_root: Path, dp_project_root_dir: Optional[str] = None) -> ProjectManagerArguments:
    return ProjectManagerArguments(
        log_level="WARNING",
        write_log=False,
        project_root=str(project_root),
        full_execute=False,
        list=False,
        execute_configurations="tiny",
        execute_inplace=False,
        skip_cleanup=True,
        generate_report=False,
        show_report=False,
        initialize_directory=True,
        apply_suggestions=None,
        reset=False,
        reset_execution_results=False,
        gui=False,
        label_prefix="",
        timeout_execution=None,
        timeout_compilation=None,
        timeout_validation=None,
        dp_project_root_dir=dp_project_root_dir,
    )


def _run(
    arguments: ProjectManagerArguments,
    run_root: Path,
    script_name: str = "execute.sh",
    settings_name: str = "seq_settings.json",
) -> Tuple[int, float, str, str]:
    config_path = os.path.join(arguments.project_config_dir, "tiny")
    result = execute_configuration(
        arguments,
        str(run_root),
        config_path,
        os.path.join(arguments.project_config_dir, settings_name),
        os.path.join(config_path, script_name),
        1,
        None,
    )
    assert result is not None
    return result


def _variables(stdout: str) -> Dict[str, str]:
    return dict(line.split("=", 1) for line in stdout.splitlines() if "=" in line)


# ---- the environment of a script


def test_script_sees_the_project_variables(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, ENV_SCRIPT)
    _set_scope(root, "src")

    code, _, stdout, stderr = _run(_arguments(root), root)

    assert code == 0, stderr
    assert _variables(stdout) == {
        "DP_RUN_ROOT_DIR": str(root),
        "DOT_DISCOPOP": str(root / ".discopop"),
        "DP_PROJECT_ROOT_DIR": str(root / "src") + "/",
    }


def test_script_sees_the_variables_of_the_copy(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, ENV_SCRIPT)
    _set_scope(root, "src")
    copy = tmp_path / "copies" / "project"
    shutil.copytree(root, copy)

    code, _, stdout, stderr = _run(_arguments(root), copy)

    assert code == 0, stderr
    assert _variables(stdout) == {
        "DP_RUN_ROOT_DIR": str(copy),
        "DOT_DISCOPOP": str(copy / ".discopop"),
        "DP_PROJECT_ROOT_DIR": str(copy / "src") + "/",
    }


def test_default_scope_is_the_run_root(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, ENV_SCRIPT)

    code, _, stdout, stderr = _run(_arguments(root), root)

    assert code == 0, stderr
    assert _variables(stdout)["DP_PROJECT_ROOT_DIR"] == str(root) + "/"


def test_inherited_variables_are_overridden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "project"
    _write_project(root, ENV_SCRIPT)
    monkeypatch.setenv("DOT_DISCOPOP", "relative/.discopop")
    monkeypatch.setenv("DP_PROJECT_ROOT_DIR", "/elsewhere/")

    code, _, stdout, stderr = _run(_arguments(root), root)

    assert code == 0, stderr
    variables = _variables(stdout)
    assert variables["DOT_DISCOPOP"] == str(root / ".discopop")
    assert variables["DP_PROJECT_ROOT_DIR"] == str(root) + "/"


def test_command_line_scope_overrides_the_stored_one(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, ENV_SCRIPT)
    _set_scope(root, "src")

    code, _, stdout, stderr = _run(_arguments(root, dp_project_root_dir="lib"), root)

    assert code == 0, stderr
    assert _variables(stdout)["DP_PROJECT_ROOT_DIR"] == str(root / "lib") + "/"


def test_command_line_scope_is_moved_into_the_copy(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, ENV_SCRIPT)
    copy = tmp_path / "copy"
    shutil.copytree(root, copy)

    code, _, stdout, stderr = _run(_arguments(root, dp_project_root_dir=str(root / "lib")), copy)

    assert code == 0, stderr
    assert _variables(stdout)["DP_PROJECT_ROOT_DIR"] == str(copy / "lib") + "/"


def test_command_line_scope_makes_an_invalid_stored_file_irrelevant(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, ENV_SCRIPT)
    _set_scope(root, 3)

    code, _, _, stderr = _run(_arguments(root, dp_project_root_dir="lib"), root)

    assert code == 0, stderr


def test_invalid_project_environment_fails_the_run(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, ENV_SCRIPT)
    _set_scope(root, 3)

    code, elapsed, stdout, stderr = _run(_arguments(root), root)

    assert code == 1
    assert elapsed == 0.0
    assert stdout == ""
    assert stderr.startswith("DiscoPoP ERROR: ")
    assert "project_environment.json" in stderr
    assert not (root / ".discopop" / "project" / "execution_results.json").exists()


@pytest.mark.parametrize("key", ["DP_PROJECT_ROOT_DIR", "DOT_DISCOPOP", "DP_RUN_ROOT_DIR"])
def test_reserved_variable_in_settings_is_overridden_with_a_warning(tmp_path: Path, key: str) -> None:
    root = tmp_path / "project"
    _write_project(root, ENV_SCRIPT, settings={"CC": "clang", key: "/x/"})

    code, _, stdout, stderr = _run(_arguments(root), root)

    assert code == 0, stderr
    assert _variables(stdout) == {
        "DP_RUN_ROOT_DIR": str(root),
        "DOT_DISCOPOP": str(root / ".discopop"),
        "DP_PROJECT_ROOT_DIR": str(root) + "/",
    }
    assert "DiscoPoP WARNING: seq_settings.json sets " + key in stderr


def test_no_scope_variable_warning_with_the_default_scope(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, '#!/bin/bash\necho "$DP_PROJECT_ROOT_DIR"\n')

    code, _, _, stderr = _run(_arguments(root), root)

    assert code == 0, stderr
    assert "DiscoPoP" not in stderr


def test_scope_variable_warning_with_a_narrowed_scope(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, '#!/bin/bash\necho "$DP_PROJECT_ROOT_DIR"\n')
    _set_scope(root, "src")

    code, _, _, stderr = _run(_arguments(root), root)

    assert code == 0, stderr
    assert "DiscoPoP WARNING" in stderr
    assert "DP_RUN_ROOT_DIR" in stderr


def test_no_scope_variable_warning_if_the_script_does_not_use_it(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, "#!/bin/bash\necho hi\n")
    _set_scope(root, "src")

    code, _, _, stderr = _run(_arguments(root), root)

    assert code == 0
    assert "DiscoPoP" not in stderr


def test_seq_run_is_not_checked(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, "#!/bin/bash\nmkdir -p sub/.discopop\ntouch sub/.discopop/FileMapping.txt\necho done\n")

    for script in ("compile.sh", "execute.sh"):
        code, _, stdout, stderr = _run(_arguments(root), root, script_name=script)
        assert code == 0, stderr
        assert "DiscoPoP" not in stderr
        assert stdout.strip() == "done"


# ---- checks of instrumented compiles and runs


def test_dp_compile_with_a_stray_dot_discopop_fails(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(
        root,
        "#!/bin/bash\nmkdir -p sub/.discopop\ntouch sub/.discopop/FileMapping.txt\n",
        settings_name="dp_settings.json",
    )

    code, _, _, stderr = _run(_arguments(root), root, "compile.sh", "dp_settings.json")

    assert code != 0
    assert "ERROR" in stderr
    assert str(root / "sub" / ".discopop") in stderr


def test_dp_compile_in_a_copy_with_a_stray_dot_discopop_fails(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(
        root,
        "#!/bin/bash\nmkdir -p sub/.discopop\ntouch sub/.discopop/FileMapping.txt\n",
        settings_name="dp_settings.json",
    )
    copy = tmp_path / "copy"
    shutil.copytree(root, copy)

    code, _, _, stderr = _run(_arguments(root), copy, "compile.sh", "dp_settings.json")

    assert code != 0
    assert str(copy / "sub" / ".discopop") in stderr


def test_dp_compile_without_stray_dirs_succeeds_with_a_warning_without_file_mapping(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, "#!/bin/bash\ntrue\n", settings_name="dp_settings.json")

    code, _, _, stderr = _run(_arguments(root), root, "compile.sh", "dp_settings.json")

    assert code == 0
    assert "WARNING" in stderr
    assert "FileMapping.txt" in stderr


def test_dp_compile_registering_a_file_in_scope_succeeds_without_message(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(
        root,
        '#!/bin/bash\nmkdir -p "$DOT_DISCOPOP"\necho "1 $DP_PROJECT_ROOT_DIR"a.c > "$DOT_DISCOPOP/FileMapping.txt"\n',
        settings_name="dp_settings.json",
    )

    code, _, _, stderr = _run(_arguments(root), root, "compile.sh", "dp_settings.json")

    assert code == 0, stderr
    assert "DiscoPoP" not in stderr


def test_dp_compile_with_a_mapping_outside_the_scope_warns(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(
        root,
        '#!/bin/bash\nmkdir -p "$DOT_DISCOPOP"\necho "1 /elsewhere/a.c" > "$DOT_DISCOPOP/FileMapping.txt"\n',
        settings_name="dp_settings.json",
    )

    code, _, _, stderr = _run(_arguments(root), root, "compile.sh", "dp_settings.json")

    assert code == 0, stderr
    assert "DiscoPoP WARNING: No instrumented file lies below the instrumentation scope" in stderr


def test_dp_execute_without_results_fails(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, "#!/bin/bash\ntrue\n", settings_name="dp_settings.json")

    code, _, _, stderr = _run(_arguments(root), root, "execute.sh", "dp_settings.json")

    assert code != 0
    assert "dynamic_dependencies.txt" in stderr


def test_dp_execute_with_results_succeeds(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(
        root,
        '#!/bin/bash\nmkdir -p "$DOT_DISCOPOP/profiler"\n'
        'echo dep > "$DOT_DISCOPOP/profiler/dynamic_dependencies.txt"\n',
        settings_name="dp_settings.json",
    )

    code, _, _, stderr = _run(_arguments(root), root, "execute.sh", "dp_settings.json")

    assert code == 0, stderr
    assert "DiscoPoP" not in stderr


def test_dp_execute_with_results_in_the_copy_succeeds(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(
        root,
        '#!/bin/bash\nmkdir -p "$DOT_DISCOPOP/profiler"\n'
        'echo dep > "$DOT_DISCOPOP/profiler/dynamic_dependencies.txt"\n',
        settings_name="dp_settings.json",
    )
    copy = tmp_path / "copy"
    shutil.copytree(root, copy)

    code, _, _, stderr = _run(_arguments(root), copy, "execute.sh", "dp_settings.json")

    assert code == 0, stderr
    assert (copy / ".discopop" / "profiler" / "dynamic_dependencies.txt").is_file()
    assert not (root / ".discopop" / "profiler").exists()


def test_failed_script_keeps_its_code_and_is_not_checked(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, "#!/bin/bash\nexit 3\n", settings_name="dp_settings.json")

    code, _, _, stderr = _run(_arguments(root), root, "execute.sh", "dp_settings.json")

    assert code == 3
    assert "dynamic_dependencies.txt" not in stderr


def test_hd_execute_without_results_fails_and_with_results_succeeds(tmp_path: Path) -> None:
    root = tmp_path / "project"
    _write_project(root, "#!/bin/bash\ntrue\n", settings_name="hd_settings.json")
    code, _, _, stderr = _run(_arguments(root), root, "execute.sh", "hd_settings.json")
    assert code != 0
    assert "hotspot_detection" in stderr

    script = root / ".discopop" / "project" / "configs" / "tiny" / "execute.sh"
    script.write_text(
        '#!/bin/bash\nmkdir -p "$DOT_DISCOPOP/hotspot_detection/private"\n'
        'echo 1 > "$DOT_DISCOPOP/hotspot_detection/private/hotspot_result_0.txt"\n'
    )
    code, _, _, stderr = _run(_arguments(root), root, "execute.sh", "hd_settings.json")
    assert code == 0, stderr

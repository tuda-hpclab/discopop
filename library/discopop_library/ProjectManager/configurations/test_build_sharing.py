# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of sharing a build between configurations."""

import json
from pathlib import Path

import pytest

from discopop_library.ProjectManager.configurations.build_sharing import (
    BuildSharingError,
    build_inputs_for,
    build_owner_of,
    detach_members,
    members_of,
    own_build_files,
    repoint_members,
    set_build_from,
    stale_declaration_problems,
)


@pytest.fixture
def configs(tmp_path: Path) -> str:
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "execute.sh").write_text("#!/bin/bash\n")
        (tmp_path / name / "execution_time.json").write_text("{}")
    return str(tmp_path)


def test_a_configuration_builds_for_itself_by_default(configs: str) -> None:
    assert build_owner_of(configs, "a") == "a"
    assert not build_inputs_for(configs, "a").shared


def test_a_member_builds_from_its_owner(configs: str) -> None:
    set_build_from(configs, "b", "a")
    inputs = build_inputs_for(configs, "b")
    assert (inputs.build_config, inputs.run_config, inputs.shared) == ("a", "b", True)
    assert members_of(configs, "a") == ["b"]
    set_build_from(configs, "b", None)
    assert build_owner_of(configs, "b") == "b"


@pytest.mark.parametrize("member,owner", [("a", "a"), ("a", "missing"), ("missing", "a")])
def test_invalid_declarations_are_refused(configs: str, member: str, owner: str) -> None:
    with pytest.raises(BuildSharingError):
        set_build_from(configs, member, owner)


def test_builds_are_not_chained(configs: str) -> None:
    set_build_from(configs, "b", "a")
    with pytest.raises(BuildSharingError, match="not chained"):
        set_build_from(configs, "c", "b")
    with pytest.raises(BuildSharingError, match="owner of b"):
        set_build_from(configs, "a", "c")


def test_a_member_cannot_have_files_that_change_the_build(configs: str) -> None:
    (Path(configs) / "b" / "compile.sh").write_text("#!/bin/bash\n")
    assert own_build_files(configs, "b") == ["compile.sh"]
    with pytest.raises(BuildSharingError, match="compile.sh"):
        set_build_from(configs, "b", "a")


@pytest.mark.parametrize("where", ["a/compile_validate.sh", "compile_validate.sh"])
def test_an_owner_with_a_validation_compile_script_cannot_be_shared(configs: str, where: str) -> None:
    (Path(configs) / where).write_text("#!/bin/bash\n")
    with pytest.raises(BuildSharingError, match="validation compile script"):
        set_build_from(configs, "b", "a")


def test_a_declaration_that_cannot_be_followed_is_ignored(configs: str) -> None:
    (Path(configs) / "b" / "build_from.json").write_text(json.dumps({"build_from": "gone"}))
    assert build_owner_of(configs, "b") == "b"
    (Path(configs) / "b" / "build_from.json").write_text("not json")
    assert build_owner_of(configs, "b") == "b"


def test_later_changes_are_reported(configs: str) -> None:
    set_build_from(configs, "b", "a")
    assert stale_declaration_problems(configs, "b") == []
    (Path(configs) / "b" / "compile.sh").write_text("#!/bin/bash\n")
    (Path(configs) / "compile_validate.sh").write_text("#!/bin/bash\n")
    assert len(stale_declaration_problems(configs, "b")) == 2


def test_members_follow_a_rename_and_can_be_detached(configs: str) -> None:
    set_build_from(configs, "b", "a")
    set_build_from(configs, "c", "a")
    (Path(configs) / "a").rename(Path(configs) / "z")
    assert repoint_members(configs, "a", "z") == ["b", "c"]
    assert build_owner_of(configs, "b") == "z"
    assert detach_members(configs, "z") == ["b", "c"]
    assert members_of(configs, "z") == []

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Which suggestions patch files outside the project: classification and the refusal of the applicator."""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Dict, Iterator, List

import pytest

from discopop_library.PatchApplicator.PatchApplicationResult import PatchApplicationResult
from discopop_library.PatchApplicator.PatchApplicatorArguments import PatchApplicatorArguments
from discopop_library.PatchApplicator.apply import apply_patches
from discopop_library.PatchApplicator.outside_project import (
    describe_outside_targets,
    find_outside_project_targets,
    is_outside_project,
    log_skipped_outside_suggestions,
    project_root_of,
    split_by_outside_project,
)

ORIGINAL = "int main() {\n  int i = 0;\n  return i;\n}\n"
PATCHED = "int main() {\n  int i = 1;\n  return i;\n}\n"


def write_project(project: Path, mapping: Dict[int, Path], suggestions: Dict[str, List[int]]) -> Path:
    """``project/.discopop`` with a file mapping and an (empty) patch for every file of every suggestion."""
    dot = project / ".discopop"
    (dot / "patch_generator").mkdir(parents=True, exist_ok=True)
    with open(dot / "FileMapping.txt", "w") as f:
        for file_id, path in mapping.items():
            f.write(f"{file_id}\t{path}\n")
    for suggestion_id, file_ids in suggestions.items():
        (dot / "patch_generator" / suggestion_id).mkdir()
        for file_id in file_ids:
            (dot / "patch_generator" / suggestion_id / f"{file_id}.patch").write_text("")
    return dot


def test_the_project_is_the_directory_of_the_dot_discopop(tmp_path: Path) -> None:
    assert project_root_of(str(tmp_path / "proj" / ".discopop")) == str(tmp_path / "proj")


def test_targets_below_the_project_are_inside_and_others_outside(tmp_path: Path) -> None:
    root = str(tmp_path / "proj")
    assert not is_outside_project(str(tmp_path / "proj" / "src" / "a.c"), root)
    assert is_outside_project(str(tmp_path / "shared" / "a.c"), root)
    # a directory that merely starts with the name of the project is not part of it
    assert is_outside_project(str(tmp_path / "proj2" / "a.c"), root)
    # ".." does not lead out of sight
    assert is_outside_project(str(tmp_path / "proj" / ".." / "shared" / "a.c"), root)


def test_a_project_reached_through_a_symbolic_link_is_the_same_project(tmp_path: Path) -> None:
    real = tmp_path / "real" / "proj"
    real.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real")
    # the file mapping names the project by its real path, the .discopop was reached through the link
    assert not is_outside_project(str(real / "a.c"), str(link / "proj"))
    # and the other way round
    assert not is_outside_project(str(link / "proj" / "a.c"), str(real))
    assert is_outside_project(str(tmp_path / "other" / "a.c"), str(link / "proj"))


def test_the_outside_suggestions_and_their_targets_are_found(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    inside = project / "a.c"
    outside_a = tmp_path / "shared" / "a.c"
    outside_b = tmp_path / "shared" / "b.c"
    dot = write_project(
        project,
        {1: inside, 2: outside_a, 3: outside_b},
        {"1": [1], "2": [2], "3": [1, 2, 3], "4": [1]},
    )
    assert find_outside_project_targets(str(dot)) == {"2": [str(outside_a)], "3": [str(outside_a), str(outside_b)]}
    # restricted to some ids, given as numbers or strings
    assert find_outside_project_targets(str(dot), [1, "2", 4]) == {"2": [str(outside_a)]}
    assert find_outside_project_targets(str(dot), ["99"]) == {}


def test_without_patches_or_a_file_mapping_nothing_is_outside(tmp_path: Path) -> None:
    assert find_outside_project_targets(str(tmp_path / "proj" / ".discopop")) == {}
    dot = write_project(tmp_path / "proj", {}, {"1": [1]})
    assert find_outside_project_targets(str(dot)) == {}


def test_split_keeps_the_order_of_the_inside_suggestions(tmp_path: Path) -> None:
    dot = write_project(tmp_path / "proj", {1: tmp_path / "proj" / "a.c", 2: tmp_path / "x.c"}, {"1": [1], "2": [2]})
    inside, outside = split_by_outside_project(str(dot), ["2", "1", "7"])
    assert inside == ["1", "7"] and list(outside) == ["2"]
    assert describe_outside_targets(outside) == "suggestion 2: " + str(tmp_path / "x.c")


def test_skipping_is_logged_with_the_suggestions_and_files(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("outside-test")
    with caplog.at_level(logging.WARNING, logger="outside-test"):
        log_skipped_outside_suggestions(logger, "Autotuner", {})
        assert not caplog.records
        log_skipped_outside_suggestions(logger, "Autotuner", {"5": ["/shared/a.c"]})
    assert len(caplog.records) == 1
    assert "Autotuner" in caplog.text and "suggestion 5: /shared/a.c" in caplog.text


# ── the patch applicator ─────────────────────────────────────────────────────


def _arguments(allow_outside_project: bool = False) -> PatchApplicatorArguments:
    return PatchApplicatorArguments(
        verbose=False,
        apply=[],
        rollback=[],
        clear=False,
        load=False,
        list=False,
        log_level="WARNING",
        write_log=False,
        allow_outside_project=allow_outside_project,
    )


@pytest.fixture
def outside_setup(tmp_path: Path) -> Iterator[Dict[str, object]]:
    """Suggestion 1 patches a file in the project, suggestion 2 a file outside of it; cwd is the .discopop directory."""
    project = tmp_path / "proj"
    project.mkdir()
    inside = project / "main.c"
    outside = tmp_path / "shared" / "main.c"
    outside.parent.mkdir()
    dot = write_project(project, {1: inside, 2: outside}, {"1": [1], "2": [2]})
    modified = tmp_path / "modified.c"
    modified.write_text(PATCHED)
    for source, file_id, suggestion_id in ((inside, 1, "1"), (outside, 2, "2")):
        source.write_text(ORIGINAL)
        diff = subprocess.run(["diff", "-Naru", str(source), str(modified)], stdout=subprocess.PIPE).stdout
        (dot / "patch_generator" / suggestion_id / f"{file_id}.patch").write_bytes(diff)
    (dot / "line_mapping.json").write_text(json.dumps({"1": {"1": 1, "2": 2, "3": 3, "4": 4}, "2": {"1": 1}}))
    applied_file = dot / "applied_suggestions.json"
    applied_file.write_text(json.dumps({"applied": []}))
    previous = os.getcwd()
    os.chdir(dot)
    try:
        yield {"dot": dot, "inside": inside, "outside": outside, "applied_file": applied_file}
    finally:
        os.chdir(previous)


def _apply(setup: Dict[str, object], ids: List[str], allow: bool) -> PatchApplicationResult:
    dot = setup["dot"]
    assert isinstance(dot, Path)
    mapping = {1: setup["inside"], 2: setup["outside"]}
    return apply_patches(
        ids,
        mapping,  # type: ignore[arg-type]
        _arguments(allow),
        str(setup["applied_file"]),
        str(dot / "patch_generator"),
    )


def test_the_applicator_refuses_a_suggestion_with_outside_targets(outside_setup: Dict[str, object]) -> None:
    result = _apply(outside_setup, ["2"], allow=False)
    assert result.refused == ["2"] and result.applied == []
    assert result.failure and result.nothing_in_code and result.retval == 1
    assert "outside the project" in result.summary() and "2" in result.summary()
    # nothing was patched, and the refusal is not recorded as an application
    assert Path(str(outside_setup["outside"])).read_text() == ORIGINAL
    assert json.loads(Path(str(outside_setup["applied_file"])).read_text()) == {"applied": []}


def test_the_applicator_applies_the_inside_suggestions_next_to_a_refused_one(outside_setup: Dict[str, object]) -> None:
    result = _apply(outside_setup, ["1", "2"], allow=False)
    assert result.applied == ["1"] and result.refused == ["2"] and result.retval == 2
    assert Path(str(outside_setup["inside"])).read_text() == PATCHED
    assert Path(str(outside_setup["outside"])).read_text() == ORIGINAL


def test_the_permission_lets_the_applicator_patch_outside_targets(outside_setup: Dict[str, object]) -> None:
    result = _apply(outside_setup, ["2"], allow=True)
    assert result.applied == ["2"] and result.refused == [] and result.complete
    assert Path(str(outside_setup["outside"])).read_text() == PATCHED


def test_the_refusal_survives_the_result_file(tmp_path: Path) -> None:
    from discopop_library.PatchApplicator.PatchApplicationResult import (
        read_application_result,
        write_application_result,
    )

    write_application_result(str(tmp_path), PatchApplicationResult(requested=["2"], refused=["2"]))
    loaded = read_application_result(str(tmp_path))
    assert loaded is not None and loaded.refused == ["2"] and loaded.failure

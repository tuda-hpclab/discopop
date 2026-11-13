# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The text and the check behind the confirmation for applying suggestions outside the project."""

from pathlib import Path

from discopop_library.ProjectManager.services.outside_patches import confirmation_text, outside_project_suggestions


def test_only_the_suggestions_outside_the_project_are_found(tmp_path: Path) -> None:
    dot = tmp_path / "proj" / ".discopop"
    for suggestion_id, file_id in (("1", 1), ("2", 2)):
        (dot / "patch_generator" / suggestion_id).mkdir(parents=True)
        (dot / "patch_generator" / suggestion_id / f"{file_id}.patch").write_text("")
    (dot / "FileMapping.txt").write_text(f"1\t{tmp_path}/proj/a.c\n2\t{tmp_path}/shared/a.c\n")
    assert outside_project_suggestions(str(dot), ["1"]) == {}
    assert outside_project_suggestions(str(dot), ["1", "2"]) == {"2": [f"{tmp_path}/shared/a.c"]}


def test_the_confirmation_warns_and_lists_the_files() -> None:
    text = confirmation_text({"2": ["/shared/a.c"], "10": ["/shared/a.c", "/shared/b.c"]})
    assert "2, 10" in text
    assert "/shared/a.c" in text and "/shared/b.c" in text
    assert "OUTSIDE the project" in text
    assert "modified in place" in text and "other projects" in text and "restored" in text


def test_a_long_list_of_files_is_shortened() -> None:
    text = confirmation_text({"1": [f"/shared/f{n}.c" for n in range(30)]})
    assert "/shared/f0.c" in text and "/shared/f29.c" not in text and "and 18 more" in text

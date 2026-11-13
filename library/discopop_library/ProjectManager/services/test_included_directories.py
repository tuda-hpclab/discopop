# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from pathlib import Path

from discopop_library.ProjectManager.services import included_directories as inc


def test_normalize() -> None:
    assert inc.normalize("/opt/shared/./lib/") == "/opt/shared/lib"
    assert inc.normalize("relative") is None
    assert inc.normalize("  ") is None
    assert inc.normalize("~/x") == str(Path.home() / "x")


def test_minimal_drops_nested_duplicates_and_inside_entries(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    entries = ["/opt/a/b", "/opt/a", "/opt/a/", str(root / "src"), "/srv"]
    assert inc.minimal(entries, str(root)) == ["/opt/a", "/srv"]
    assert inc.minimal(entries) == sorted({"/opt/a", "/srv", str(root / "src")})


def test_inside_project_through_a_symbolic_link(tmp_path: Path) -> None:
    real = tmp_path / "storage" / "project"
    (real / "src").mkdir(parents=True)
    link = tmp_path / "home_project"
    link.symlink_to(real)
    assert inc.inside_project(str(link), str(real / "src"))
    assert inc.inside_project(str(real), str(link / "src"))
    assert not inc.inside_project(str(real), str(tmp_path / "storage" / "project2"))


def test_save_and_load(tmp_path: Path) -> None:
    project_dir = tmp_path / "project" / ".discopop" / "project"
    assert inc.load_included_directories(str(project_dir)) == []
    stored = inc.save_included_directories(str(project_dir), str(tmp_path / "project"), ["/b", "/a", "/a/x"])
    assert stored == ["/a", "/b"]
    assert inc.load_included_directories(str(project_dir)) == stored


def test_unreadable_file_is_an_empty_list(tmp_path: Path) -> None:
    (tmp_path / inc.INCLUDED_DIRECTORIES_FILE).write_text("{broken")
    assert inc.load_included_directories(str(tmp_path)) == []
    (tmp_path / inc.INCLUDED_DIRECTORIES_FILE).write_text('{"included_directories": "x"}')
    assert inc.load_included_directories(str(tmp_path)) == []


def test_environment_value_keeps_entries_of_the_settings() -> None:
    assert inc.environment_value(["/a", "/b"]) == "/a:/b"
    assert inc.environment_value(["/a"], "/x::/a") == "/x:/a"


def test_problems(tmp_path: Path) -> None:
    root = tmp_path / "project"
    (root / "src").mkdir(parents=True)
    shared = tmp_path / "shared"
    shared.mkdir()
    assert inc.problems(str(root), str(shared)) == []
    assert inc.problems(str(root), "relative") == ["Give an absolute path."]
    assert "inside the project" in inc.problems(str(root), str(root / "src"))[0]
    assert "not an existing directory" in inc.problems(str(root), str(tmp_path / "missing"))[0]

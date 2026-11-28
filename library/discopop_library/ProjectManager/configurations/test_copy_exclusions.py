# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
import shutil
from pathlib import Path
from typing import Set

from discopop_library.ProjectManager.configurations.copy_exclusions import (
    CopyExclusions,
    in_source_build_files,
    is_build_directory,
    without_left_out,
)


def _write(path: Path, text: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _cmake_cache(build_dir: Path, home: Path) -> None:
    _write(build_dir / "CMakeCache.txt", "# cache\nCMAKE_HOME_DIRECTORY:INTERNAL=" + str(home) + "\nOTHER:BOOL=ON\n")
    _write(build_dir / "CMakeFiles" / "cmake.check_cache", "")


def _copy(root: Path, destination: Path, **kwargs: object) -> CopyExclusions:
    exclusions = CopyExclusions(str(root), **kwargs)  # type: ignore[arg-type]
    shutil.copytree(root, destination, ignore=exclusions.ignore())
    return exclusions


def _files(root: Path) -> Set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def test_out_of_source_cmake_build_directory_is_left_out(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "CMakeLists.txt")
    _write(project / "src" / "main.cpp")
    _cmake_cache(project / "build", project)
    _write(project / "build" / "prog", "binary")

    exclusions = _copy(project, tmp_path / "copy")

    assert _files(tmp_path / "copy") == {"CMakeLists.txt", "src/main.cpp"}
    assert exclusions.build_directories == ["build"]
    report = exclusions.report()
    assert report is not None and "build" in report


def test_nested_build_directory_is_found(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "CMakeLists.txt")
    _cmake_cache(project / "out" / "release", project)
    _write(project / "out" / "notes.txt")

    exclusions = _copy(project, tmp_path / "copy")

    assert _files(tmp_path / "copy") == {"CMakeLists.txt", "out/notes.txt"}
    assert exclusions.build_directories == ["out/release"]


def test_in_source_cmake_build_keeps_the_sources(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "CMakeLists.txt")
    _write(project / "main.cpp")
    _write(project / "Makefile", "generated")
    _cmake_cache(project, project)

    exclusions = _copy(project, tmp_path / "copy")

    assert _files(tmp_path / "copy") == {"CMakeLists.txt", "main.cpp", "Makefile"}
    assert sorted(exclusions.build_directories) == ["CMakeCache.txt", "CMakeFiles"]


def test_in_source_cmake_build_in_a_subdirectory_keeps_its_sources(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "src" / "CMakeLists.txt")
    _write(project / "src" / "main.cpp")
    _cmake_cache(project / "src", project / "src")

    _copy(project, tmp_path / "copy")

    assert _files(tmp_path / "copy") == {"src/CMakeLists.txt", "src/main.cpp"}


def test_unreadable_cmake_home_counts_as_in_source(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "build" / "CMakeCache.txt", "no home directory recorded\n")
    _write(project / "build" / "generated.cpp")

    assert not is_build_directory(str(project / "build"))
    assert in_source_build_files(str(project / "build"), ["CMakeCache.txt", "generated.cpp"]) == ["CMakeCache.txt"]


def test_meson_build_directory_is_left_out(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "meson.build")
    _write(project / "builddir" / "meson-private" / "coredata.dat")
    _write(project / "builddir" / "build.ninja")

    _copy(project, tmp_path / "copy")

    assert _files(tmp_path / "copy") == {"meson.build"}


def test_autotools_out_of_source_build_is_left_out_in_source_is_kept(tmp_path: Path) -> None:
    project = tmp_path / "project"
    # in-source: configure and config.status side by side, the Makefile next to the sources
    _write(project / "configure", "#!/bin/sh")
    _write(project / "config.status")
    _write(project / "Makefile")
    _write(project / "main.c")
    # out of source
    _write(project / "_build" / "config.status")
    _write(project / "_build" / "config.log")
    _write(project / "_build" / "Makefile")
    # a file that is merely named config.status (no config.log): kept
    _write(project / "doc" / "config.status")

    _copy(project, tmp_path / "copy")

    assert _files(tmp_path / "copy") == {"configure", "config.status", "Makefile", "main.c", "doc/config.status"}


def test_listed_paths_and_dot_discopop_data_are_left_out(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "main.cpp")
    _write(project / "data" / "big.bin")
    _write(project / "docs" / "a.txt")
    _write(project / ".discopop" / "profiler" / "dynamic_dependencies.txt")
    _write(project / ".discopop" / "FileMapping.txt")

    exclusions = _copy(project, tmp_path / "copy", listed=["data", "docs/a.txt", "missing"], dot_discopop=["profiler"])

    assert _files(tmp_path / "copy") == {"main.cpp", ".discopop/FileMapping.txt"}
    assert sorted(exclusions.listed_left_out) == ["data", "docs/a.txt"]
    report = exclusions.report()
    assert report is not None and "copy_exclude.json" in report


def test_nothing_left_out_gives_no_report(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "main.cpp")
    _write(project / "build" / "prog")  # a build directory without any marker is copied

    exclusions = _copy(project, tmp_path / "copy")

    assert _files(tmp_path / "copy") == {"main.cpp", "build/prog"}
    assert exclusions.report() is None


def test_a_link_to_a_build_directory_is_left_out(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "main.cpp")
    outside = tmp_path / "outside_build"
    _cmake_cache(outside, project)
    os.symlink(outside, project / "build")

    _copy(project, tmp_path / "copy")

    assert not os.path.lexists(tmp_path / "copy" / "build")


def test_entries_of_left_out_paths_do_not_count(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "CMakeLists.txt")
    _write(project / "main.cpp")
    _cmake_cache(project / "build", project)  # out of source: whole directory
    _cmake_cache(project / "lib", project / "lib")  # in source: only the cache files
    _write(project / "lib" / "lib.cpp")
    _write(project / "mbuild" / "meson-private" / "coredata.dat")
    _write(project / "data" / "input.bin")
    entries = {str(p.relative_to(project)).replace(os.sep, "/"): "x" for p in project.rglob("*") if p.is_file()}

    kept = without_left_out(str(project), entries, listed=["data"])

    assert set(kept) == {"CMakeLists.txt", "main.cpp", "lib/lib.cpp"}
    assert without_left_out(str(project), {"main.cpp": "x"}) == {"main.cpp": "x"}


def test_copy_and_entry_filter_agree(tmp_path: Path) -> None:
    project = tmp_path / "project"
    _write(project / "src" / "main.cpp")
    _cmake_cache(project / "out" / "release", project)
    _cmake_cache(project / "src", project / "src")
    _write(project / "_build" / "config.status")
    _write(project / "_build" / "config.log")
    _cmake_cache(project / "out" / "release" / "nested", project)  # inside a left out directory
    _write(project / "mb" / "meson-private" / "coredata.dat")
    entries = {str(p.relative_to(project)).replace(os.sep, "/"): "x" for p in project.rglob("*") if p.is_file()}

    _copy(project, tmp_path / "copy")

    assert set(without_left_out(str(project), entries)) == _files(tmp_path / "copy")


def test_a_moved_tree_keeps_its_sources(tmp_path: Path) -> None:
    # copied by hand: the cache names a source directory that does not exist any more
    project = tmp_path / "project"
    _write(project / "sub" / "a.c")
    _cmake_cache(project / "sub", tmp_path / "old" / "sub")

    exclusions = _copy(project, tmp_path / "copy")

    assert _files(tmp_path / "copy") == {"sub/a.c"}
    assert sorted(exclusions.build_directories) == ["sub/CMakeCache.txt", "sub/CMakeFiles"]
    assert set(without_left_out(str(project), {"sub/a.c": "x", "sub/CMakeCache.txt": "x"})) == {"sub/a.c"}

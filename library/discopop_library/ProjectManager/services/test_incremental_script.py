# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


import pytest

from discopop_library.ProjectManager.services.incremental_script import EMPTY_TEMPLATE, propose_incremental_script


def body(proposal: str) -> str:
    """The proposal without the shebang and the comment lines."""
    return "\n".join(line for line in proposal.splitlines() if line and not line.startswith("#"))


def test_cmake_keeps_the_build_and_drops_the_configure_step() -> None:
    script = (
        "#!/bin/bash\nset -e\nmkdir -p build\n"
        'cmake -S . -B build -DCMAKE_CXX_COMPILER="$CXX" -DCMAKE_BUILD_TYPE=Release\n'
        "cmake --build build -j 4\n"
    )
    proposal = propose_incremental_script(script)
    assert proposal is not None and proposal.startswith("#!/bin/bash\n")
    assert "Derived from compile.sh" in proposal
    assert body(proposal) == "set -e\ncmake --build build -j 4"


def test_an_and_chained_cmake_line_is_split() -> None:
    proposal = propose_incremental_script("cmake -S . -B build -DX=1 && cmake --build build -j\n")
    assert proposal is not None and body(proposal) == "cmake --build build -j"


def test_the_cd_into_the_build_directory_is_kept_without_the_configure_step() -> None:
    proposal = propose_incremental_script("rm -rf build && mkdir build && cd build && cmake .. && make -j\n")
    assert proposal is not None and body(proposal) == "cd build && make -j"


def test_a_superbuild_keeps_the_outer_build_and_hints_at_the_inner_project() -> None:
    proposal = propose_incremental_script("cmake -S . -B build -DX=1\ncmake --build build -j\n")
    assert proposal is not None
    assert body(proposal) == "cmake --build build -j"
    assert "superbuild" in proposal and "inner project" in proposal


def test_make_clean_is_dropped_and_make_stays() -> None:
    proposal = propose_incremental_script('#!/bin/sh\nexport CFLAGS="-O2 -g"\nmake clean && make CC="$CC" -j\n')
    assert proposal is not None
    assert proposal.startswith("#!/bin/sh\n")
    assert body(proposal) == 'export CFLAGS="-O2 -g"\nmake CC="$CC" -j'


def test_a_standalone_make_clean_or_distclean_is_not_a_build_line() -> None:
    assert propose_incremental_script("make clean\nmake distclean\n") is None


def test_autotools_keeps_make_only() -> None:
    proposal = propose_incremental_script('autoreconf -i\n./configure CC="$CC" --prefix=/tmp/x\nmake -j\n')
    assert proposal is not None and body(proposal) == "make -j"


def test_meson_keeps_ninja_only() -> None:
    proposal = propose_incremental_script("meson setup build\nninja -C build\n")
    assert proposal is not None and body(proposal) == "ninja -C build"


def test_a_line_continuation_is_joined() -> None:
    proposal = propose_incremental_script("cmake -S . \\\n  -B build\ncmake --build build \\\n  -j\n")
    assert proposal is not None and body(proposal) == "cmake --build build -j"


def test_an_unknown_script_gets_no_proposal() -> None:
    assert propose_incremental_script("#!/bin/bash\n$CXX $CXXFLAGS -o prog main.cpp\n") is None
    assert propose_incremental_script("") is None


def test_a_script_with_control_structures_gets_no_proposal() -> None:
    assert propose_incremental_script("if [ ! -d build ]; then\n  cmake -S . -B build\nfi\nmake -j\n") is None


def test_the_empty_template_is_a_script_that_asks_for_a_build_command() -> None:
    assert EMPTY_TEMPLATE.startswith("#!/bin/bash\n") and "only rebuild" in EMPTY_TEMPLATE


@pytest.mark.parametrize("command", ["ninja -t clean", "make -C build clean"])
def test_clean_commands_are_dropped(command: str) -> None:
    assert propose_incremental_script(command + "\n") is None

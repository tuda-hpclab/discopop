# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The OpenMP flags of the compiler wrappers: kept with one warning per build, removed with ``DP_STRIP_OPENMP=1``.

The wrappers are run with stub compilers (``clang-22`` / ``clang++-22`` that write their command line to a file), so
the tests need no LLVM and check exactly what the wrappers would hand to clang.
"""

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytest

REPOSITORY = Path(__file__).resolve().parents[2]
PROFILER_SCRIPTS = REPOSITORY / "profiler" / "scripts"
HOTSPOT_SCRIPTS = REPOSITORY / "hotspot_detection" / "scripts"

# wrappers that call the compiler once and do nothing else (so the stub compiler is all they need)
SIMPLE_WRAPPERS = [
    PROFILER_SCRIPTS / "LINKER_wrapper.sh",
    HOTSPOT_SCRIPTS / "CC_wrapper.sh",
    HOTSPOT_SCRIPTS / "CXX_wrapper.sh",
    HOTSPOT_SCRIPTS / "LINKER_wrapper.sh",
]

STUB = """#!/bin/bash
printf '%s\\n' "$@" >> "$DP_STUB_LOG"
exit 0
"""


def _wrapper_id(path: Path) -> str:
    return f"{path.parent.parent.name}/{path.name}"


@pytest.fixture()
def stub_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("clang-22", "clang++-22"):
        stub = bin_dir / name
        stub.write_text(STUB)
        stub.chmod(0o755)
    return bin_dir


def run_wrapper(
    wrapper: Path, arguments: List[str], tmp_path: Path, stub_bin: Path, extra_env: Optional[Dict[str, str]] = None
) -> Tuple[List[str], str]:
    """Runs ``wrapper`` in ``tmp_path`` (which holds a ``.discopop``) and returns the arguments the compiler got and
    the wrapper's stderr."""
    (tmp_path / ".discopop").mkdir(exist_ok=True)
    log = tmp_path / "compiler_calls.txt"
    log.unlink(missing_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DP_", "DOT_DISCOPOP"))}
    env["PATH"] = f"{stub_bin}{os.pathsep}{env['PATH']}"
    env["DP_STUB_LOG"] = str(log)
    env.update(extra_env or {})
    result = subprocess.run(
        ["bash", str(wrapper), *arguments], cwd=tmp_path, env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return (log.read_text().splitlines() if log.exists() else []), result.stderr


def test_both_copies_of_dp_openmp_agree() -> None:
    assert (PROFILER_SCRIPTS / "dp_openmp.sh").read_text() == (HOTSPOT_SCRIPTS / "dp_openmp.sh").read_text()


@pytest.mark.parametrize("wrapper", SIMPLE_WRAPPERS, ids=_wrapper_id)
class TestWrappers:
    def test_flags_are_kept_with_a_warning_by_default(self, wrapper: Path, tmp_path: Path, stub_bin: Path) -> None:
        compiler_args, stderr = run_wrapper(wrapper, ["-fopenmp", "-c", "a.cpp"], tmp_path, stub_bin)
        assert "-fopenmp" in compiler_args
        assert "WARNING" in stderr and "OpenMP" in stderr
        # the three ways to remove the flags are named
        assert "DP_STRIP_OPENMP=1" in stderr
        assert "--strip-openmp" in stderr
        assert "Project Setup" in stderr
        seen = json.loads((tmp_path / ".discopop" / "openmp_flags_seen.json").read_text())
        assert seen == {"flags": "-fopenmp", "stripped": False}

    def test_the_warning_is_printed_once_per_build(self, wrapper: Path, tmp_path: Path, stub_bin: Path) -> None:
        _, first = run_wrapper(wrapper, ["-fopenmp", "-c", "a.cpp"], tmp_path, stub_bin)
        compiler_args, second = run_wrapper(wrapper, ["-fopenmp", "-c", "b.cpp"], tmp_path, stub_bin)
        assert "WARNING" in first
        assert "WARNING" not in second
        assert "-fopenmp" in compiler_args  # still kept

    def test_flags_are_removed_on_request(self, wrapper: Path, tmp_path: Path, stub_bin: Path) -> None:
        compiler_args, stderr = run_wrapper(
            wrapper,
            [
                "-fopenmp",
                "-fopenmp=libomp",
                "-fopenmp-simd",
                "-Xclang",
                "-fopenmp",
                "-Xpreprocessor",
                "-fopenmp",
                "-lomp",
                "-lgomp",
                "-O2",
                "-c",
                "a.cpp",
            ],
            tmp_path,
            stub_bin,
            {"DP_STRIP_OPENMP": "1"},
        )
        for flag in ("-fopenmp", "-fopenmp=libomp", "-fopenmp-simd", "-lomp", "-lgomp", "-Xpreprocessor"):
            assert flag not in compiler_args, compiler_args
        # what is left of the arguments (the wrapper's own flags follow; they may contain -Xclang)
        assert compiler_args[:3] == ["-O2", "-c", "a.cpp"], compiler_args
        assert "WARNING" not in stderr and "NOTE" in stderr
        seen = json.loads((tmp_path / ".discopop" / "openmp_flags_seen.json").read_text())
        assert seen["stripped"] is True

    def test_other_x_arguments_are_kept(self, wrapper: Path, tmp_path: Path, stub_bin: Path) -> None:
        compiler_args, stderr = run_wrapper(
            wrapper, ["-Xclang", "-ast-dump", "-c", "a.cpp"], tmp_path, stub_bin, {"DP_STRIP_OPENMP": "1"}
        )
        assert compiler_args[:2] == ["-Xclang", "-ast-dump"]
        assert stderr.count("DiscoPoP") == 0
        assert not (tmp_path / ".discopop" / "openmp_flags_seen.json").exists()

    def test_no_openmp_means_no_message(self, wrapper: Path, tmp_path: Path, stub_bin: Path) -> None:
        _, stderr = run_wrapper(wrapper, ["-O2", "-c", "a.cpp"], tmp_path, stub_bin)
        assert "OpenMP" not in stderr
        assert not (tmp_path / ".discopop" / "openmp_flags_seen.json").exists()

    def test_quiet_records_without_printing(self, wrapper: Path, tmp_path: Path, stub_bin: Path) -> None:
        _, stderr = run_wrapper(wrapper, ["-fopenmp", "-c", "a.cpp"], tmp_path, stub_bin, {"DP_OPENMP_QUIET": "1"})
        assert "OpenMP" not in stderr
        assert (tmp_path / ".discopop" / "openmp_flags_seen.json").exists()

    def test_simd_alone_is_no_reason_to_warn(self, wrapper: Path, tmp_path: Path, stub_bin: Path) -> None:
        compiler_args, stderr = run_wrapper(wrapper, ["-fopenmp-simd", "-c", "a.cpp"], tmp_path, stub_bin)
        assert "-fopenmp-simd" in compiler_args
        assert "OpenMP" not in stderr

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""``discopop_cxx`` with ``-fopenmp``: the flag is kept with a warning that names how to remove it, and removed with
``DP_STRIP_OPENMP=1`` (the program then no longer sees ``_OPENMP``; the instrumented program is the sequential one).

The warning and the stripping are the compiler wrapper's (``profiler/scripts/dp_openmp.sh``); the wrapper is also
tested with stub compilers in ``test/scripts/test_dp_openmp.py``."""

import json
import os
import pathlib
import shutil
import subprocess
from typing import Dict, Optional

import pytest

pytestmark = pytest.mark.skipif(shutil.which("discopop_cxx") is None, reason="discopop_cxx not found")

MAIN_CPP = """#include <cstdio>

int main() {
#ifdef _OPENMP
  std::puts("compiled with OpenMP");
#else
  std::puts("compiled without OpenMP");
#endif
  return 0;
}
"""


def _build_and_run(root: pathlib.Path, extra_env: Optional[Dict[str, str]] = None) -> "tuple[str, str]":
    """Compiles with -fopenmp in ``root`` (which holds a .discopop), returns the stderr of the compilation and the
    output of the program."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DP_", "DOT_DISCOPOP"))}
    env.update(extra_env or {})
    (root / "main.cpp").write_text(MAIN_CPP)
    (root / ".discopop").mkdir(exist_ok=True)
    compiled = subprocess.run(
        ["discopop_cxx", "-fopenmp", "main.cpp", "-o", "prog"], cwd=root, env=env, capture_output=True, text=True
    )
    assert compiled.returncode == 0, compiled.stderr
    ran = subprocess.run(["./prog"], cwd=root, env=env, capture_output=True, text=True, timeout=600)
    assert ran.returncode == 0, ran.stderr
    return compiled.stderr, ran.stdout


def test_the_flag_is_kept_with_a_warning_by_default(tmp_path: pathlib.Path) -> None:
    stderr, output = _build_and_run(tmp_path)
    assert output.splitlines()[0] == "compiled with OpenMP"
    assert "WARNING: the compiler call contains OpenMP flags (-fopenmp); they are kept." in stderr
    assert "DP_STRIP_OPENMP=1" in stderr and "--strip-openmp" in stderr and "Project Setup" in stderr
    seen = json.loads((tmp_path / ".discopop" / "openmp_flags_seen.json").read_text())
    assert seen == {"flags": "-fopenmp", "stripped": False}


def test_the_flag_is_removed_on_request(tmp_path: pathlib.Path) -> None:
    stderr, output = _build_and_run(tmp_path, {"DP_STRIP_OPENMP": "1"})
    assert output.splitlines()[0] == "compiled without OpenMP"
    assert "NOTE: removed the OpenMP flags (-fopenmp)" in stderr
    assert "WARNING: the compiler call contains OpenMP flags" not in stderr

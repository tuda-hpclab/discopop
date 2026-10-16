# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The services must stay usable without a GUI toolkit."""

import pkgutil
import subprocess
import sys

import discopop_library.ProjectManager.services as services


def test_importing_every_service_does_not_import_tkinter() -> None:
    modules = [m.name for m in pkgutil.iter_modules(services.__path__, services.__name__ + ".") if not m.ispkg]
    assert modules, "no service modules found"
    # a fresh interpreter: in a test session another test may have imported tkinter already
    # that runs the same sources as this session (the installed copy may be older), hence the path
    code = (
        "import importlib, sys\n"
        + f"sys.path[:0] = {sys.path!r}\n"
        + "".join(f"importlib.import_module({name!r})\n" for name in modules)
        + "bad = [m for m in sys.modules if m == 'tkinter' or m.startswith('tkinter.')]\n"
        + "assert not bad, bad\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

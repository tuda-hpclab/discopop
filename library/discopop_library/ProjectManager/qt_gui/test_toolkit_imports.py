# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Which toolkit each part of the Project Manager may import.

The services and the charts serve both GUIs and the command line, so they import no toolkit; the Qt GUI does not
fall back on Tk; the command line does not load a toolkit it never shows.
"""

import pkgutil
import subprocess
import sys
from typing import List

import discopop_library.ProjectManager.plots as plots
import discopop_library.ProjectManager.qt_gui as qt_gui
import discopop_library.ProjectManager.services as services


def _modules(package: object) -> List[str]:
    path = getattr(package, "__path__")
    name = getattr(package, "__name__")
    found = [
        m.name
        for m in pkgutil.iter_modules(path, name + ".")
        if not m.ispkg and ".test_" not in m.name and not m.name.endswith(".conftest")
    ]
    assert found, "no modules found in " + name
    return found


def _imported_after(statements: str) -> List[str]:
    """The top-level modules a fresh interpreter has imported after running ``statements``."""
    # a fresh interpreter: in a test session another test may have imported a toolkit already; it runs the same
    # sources as this session (the installed copy may be older), hence the path
    code = (
        "import sys\n"
        + f"sys.path[:0] = {sys.path!r}\n"
        + statements
        + "print(' '.join(sorted({m.split('.')[0] for m in sys.modules})))\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.split()


def _import_all(modules: List[str]) -> str:
    return "import importlib\n" + "".join(f"importlib.import_module({name!r})\n" for name in modules)


def test_services_and_charts_import_no_toolkit() -> None:
    imported = _imported_after(_import_all(_modules(services) + _modules(plots)))
    assert "tkinter" not in imported and "PySide6" not in imported


def test_the_qt_gui_does_not_import_tkinter() -> None:
    imported = _imported_after(_import_all(_modules(qt_gui)))
    assert "PySide6" in imported and "tkinter" not in imported


def test_the_command_line_loads_no_toolkit() -> None:
    imported = _imported_after(
        "import discopop_library.ProjectManager.__main__\nimport discopop_library.ProjectManager.ProjectManager\n"
    )
    assert "tkinter" not in imported and "PySide6" not in imported


def test_every_qt_module_can_be_imported_first() -> None:
    # an import cycle (a panel importing the main window, which imports the panels) only shows when the panel is
    # the first module imported
    import discopop_library.ProjectManager.qt_gui.panels as panels

    for module in _modules(qt_gui) + _modules(panels):
        _imported_after(f"import {module}\n")

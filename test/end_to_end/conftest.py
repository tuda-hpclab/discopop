"""Run the end-to-end tests under ``pytest``.

The tests call ``discopop_cc``, ``discopop_cxx`` and ``discopop_explorer`` by name. They are found next to the
running interpreter, so the venv does not have to be activated. Without the installed profiler the tests are skipped.
"""

import os
import shutil
import sys

import pytest

os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")

_REQUIRED_TOOLS = ["discopop_cc", "discopop_cxx", "discopop_explorer", "make"]


def pytest_collection_modifyitems(config, items):  # type: ignore
    missing = [tool for tool in _REQUIRED_TOOLS if shutil.which(tool) is None]
    if not missing:
        return
    skip = pytest.mark.skip(reason="end-to-end tests need " + ", ".join(missing) + " (install the profiler)")
    root = os.path.dirname(__file__)
    for item in items:
        if str(item.path).startswith(root + os.sep):
            item.add_marker(skip)

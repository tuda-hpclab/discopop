"""Run the end-to-end tests under ``pytest``.

The tests call ``discopop_cc``, ``discopop_cxx`` and ``discopop_explorer`` by name. They are found next to the
running interpreter, so the venv does not have to be activated. Without the installed profiler the tests are skipped.
All tests below this directory get the marker ``e2e``: ``pytest -m "not e2e"`` runs the unit tests only.
"""

import os
import shutil
import sys

import pytest

os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")

_REQUIRED_TOOLS = ["discopop_cc", "discopop_cxx", "discopop_explorer", "make"]


def pytest_collection_modifyitems(config, items):  # type: ignore
    root = os.path.dirname(__file__) + os.sep
    # the MCP server tests skip the profiler dependent tests themselves, the others need no profiler
    profiler_independent = os.path.join(root, "mcp_server") + os.sep
    missing = [tool for tool in _REQUIRED_TOOLS if shutil.which(tool) is None]
    skip = pytest.mark.skip(reason="end-to-end tests need " + ", ".join(missing) + " (install the profiler)")
    for item in items:
        path = str(item.path)
        if not path.startswith(root):
            continue
        item.add_marker(pytest.mark.e2e)
        if item.cls is not None:
            # with pytest-xdist (--dist loadgroup) the tests of a class share one worker, so its program is built once
            item.add_marker(pytest.mark.xdist_group(item.cls.__module__ + "." + item.cls.__qualname__))
        if missing and not path.startswith(profiler_independent):
            item.add_marker(skip)

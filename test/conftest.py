"""Run the test suites below ``test/`` that need the installed profiler under ``pytest``.

The tests call ``discopop_cc``, ``discopop_cxx`` and ``discopop_explorer`` by name. They are found next to the
running interpreter, so the venv does not have to be activated. Without the installed profiler these tests are
skipped. They get a marker per suite, so ``pytest -m "not e2e and not profiler"`` runs the unit tests only:

- ``e2e``: ``test/end_to_end`` (the MCP server tests there skip their profiler dependent tests themselves) and the
  opt-in ``test/wip_end_to_end``
- ``profiler``: ``test/profiler`` (dependency detection) and ``test/instrumentation`` (inserted callbacks)
"""

import os
import shutil
import sys

import pytest

os.environ["PATH"] = os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")

_HERE = os.path.dirname(__file__)
# directory below test/ -> marker of its tests
_SUITES = {"end_to_end": "e2e", "wip_end_to_end": "e2e", "profiler": "profiler", "instrumentation": "profiler"}
_PROFILER_INDEPENDENT = [os.path.join(_HERE, "end_to_end", "mcp_server") + os.sep]
_REQUIRED_TOOLS = ["discopop_cc", "discopop_cxx", "discopop_explorer", "make"]


def pytest_collection_modifyitems(config, items):  # type: ignore
    missing = [tool for tool in _REQUIRED_TOOLS if shutil.which(tool) is None]
    skip = pytest.mark.skip(reason="the test needs " + ", ".join(missing) + " (install the profiler)")
    for item in items:
        path = str(item.path)
        suite = next((s for s in _SUITES if path.startswith(os.path.join(_HERE, s) + os.sep)), None)
        if suite is None:
            continue
        item.add_marker(getattr(pytest.mark, _SUITES[suite]))
        if item.cls is not None:
            # with pytest-xdist (--dist loadgroup) the tests of a class share one worker, so its program is built once
            item.add_marker(pytest.mark.xdist_group(item.cls.__module__ + "." + item.cls.__qualname__))
        if missing and not any(path.startswith(p) for p in _PROFILER_INDEPENDENT):
            item.add_marker(skip)

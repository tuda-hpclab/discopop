# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import subprocess
from typing import Any, Optional

import pytest

from discopop_library.ProjectManager.gui.plots import demangle


@pytest.fixture(autouse=True)
def clear_cache() -> Any:
    demangle._cache.clear()
    yield
    demangle._cache.clear()


def test_non_mangled_names_pass_through_without_a_subprocess(monkeypatch: Any) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("no demangler should be spawned for a plain name")

    monkeypatch.setattr(demangle, "_find_demangler", fail)
    assert demangle.demangle("main") == "main"
    assert demangle.demangle("compute_something") == "compute_something"
    assert demangle.demangle("") == ""


def test_falls_back_to_the_mangled_name_without_a_demangler(monkeypatch: Any) -> None:
    monkeypatch.setattr(demangle, "_find_demangler", lambda: None)
    assert demangle.demangle("_Z5heavyi") == "_Z5heavyi"


def test_missing_demangler_is_not_looked_up_repeatedly(monkeypatch: Any) -> None:
    calls = []

    def counting_lookup() -> Optional[str]:
        calls.append(1)
        return None

    monkeypatch.setattr(demangle, "_find_demangler", counting_lookup)
    demangle.demangle("_Z5heavyi")
    demangle.demangle("_Z5heavyi")
    assert len(calls) == 1  # the identity mapping is cached


def test_subprocess_failure_falls_back(monkeypatch: Any) -> None:
    monkeypatch.setattr(demangle, "_find_demangler", lambda: "/nonexistent/c++filt")

    def raise_oserror(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("boom")

    monkeypatch.setattr(subprocess, "run", raise_oserror)
    assert demangle.demangle("_Z5heavyi") == "_Z5heavyi"


def test_prefetch_batches_pending_names(monkeypatch: Any) -> None:
    """One subprocess call, whatever the number of names."""
    invocations = []

    class Result:
        stdout = "heavy(int)\nlight()\n"

    def fake_run(cmd: Any, **kwargs: Any) -> Any:
        invocations.append(kwargs.get("input", ""))
        return Result()

    monkeypatch.setattr(demangle, "_find_demangler", lambda: "c++filt")
    monkeypatch.setattr(subprocess, "run", fake_run)

    # "main" is not mangled, so it must not reach the demangler
    demangle.prefetch(["_Z5heavyi", "_Z5lightv", "main", "_Z5heavyi"])
    assert len(invocations) == 1
    assert invocations[0].splitlines() == ["_Z5heavyi", "_Z5lightv"]
    assert demangle.demangle("_Z5heavyi") == "heavy(int)"
    assert demangle.demangle("_Z5lightv") == "light()"

    # everything is cached now, so a second prefetch spawns nothing
    demangle.prefetch(["_Z5heavyi", "_Z5lightv"])
    assert len(invocations) == 1


def test_short_demangler_output_falls_back_per_name(monkeypatch: Any) -> None:
    """A truncated or blank reply must not silently blank out a name."""

    class Result:
        stdout = "heavy(int)\n\n"

    monkeypatch.setattr(demangle, "_find_demangler", lambda: "c++filt")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Result())
    demangle.prefetch(["_Z5heavyi", "_Z5lightv", "_Z5thirdv"])
    assert demangle.demangle("_Z5heavyi") == "heavy(int)"
    assert demangle.demangle("_Z5lightv") == "_Z5lightv"  # blank line
    assert demangle.demangle("_Z5thirdv") == "_Z5thirdv"  # missing line


@pytest.mark.skipif(demangle._find_demangler() is None, reason="no c++filt / llvm-cxxfilt on PATH")
def test_real_demangler_if_available() -> None:
    assert demangle.demangle("_Z5heavyi") == "heavy(int)"
    assert demangle.demangle("main") == "main"

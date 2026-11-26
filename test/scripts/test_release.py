# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of scripts/dev/release.py: the version checks of the CI and the release plan of the workflow "Release"."""

import importlib.util
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Dict, List, Set

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "release.py"


@pytest.fixture(scope="module")
def release() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# a consistent pre-release of all packages: (directory, name, version, requirements on DiscoPoP packages)
CONSISTENT = {
    "hotspot_detection": ("discopop-hotspot-detection", "0.0.1a4", []),
    "profiler": ("discopop-profiler", "0.0.1a7", []),
    "library": ("discopop-library", "0.0.1a12", ["discopop-hotspot-detection>=0.0.1a4"]),
    "explorer": ("discopop-explorer", "0.0.1a4", ["discopop-library>=0.0.1a12"]),
    "GUI": ("discopop-gui", "0.0.1a4", []),
    "mcp_server": ("discopop_mcp_server", "0.0.1a10", ["discopop-library>=0.0.1a12", "discopop-explorer>=0.0.1a4"]),
    ".": (
        "discopop",
        "5.0.3a3",
        [
            "discopop-profiler>=0.0.1a7",
            "discopop-library>=0.0.1a12",
            "discopop-gui>=0.0.1a4",
            "discopop-explorer>=0.0.1a4",
            "discopop-mcp-server>=0.0.1a10",
            "discopop-hotspot-detection>=0.0.1a4",
        ],
    ),
}


def write_repository(root: Path, packages: Dict[str, tuple]) -> Path:
    for directory, (name, version, requirements) in packages.items():
        path = root / directory
        path.mkdir(parents=True, exist_ok=True)
        (path / "VERSION").write_text(version + "\n")
        dependencies = ", ".join(json.dumps(r) for r in requirements + ["numpy>=1.0"])
        (path / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\ndynamic = ["version"]\ndependencies = [{dependencies}]\n'
        )
    return root


def changed(**changes: tuple) -> Dict[str, tuple]:
    packages = dict(CONSISTENT)
    packages.update(changes)
    return packages


def test_the_repository_is_consistent(release: ModuleType) -> None:
    assert release.check(release.REPOSITORY_ROOT) == []


def test_the_order_publishes_dependencies_first(release: ModuleType) -> None:
    order = [p.key for p in release.PACKAGES]
    for package in release.PACKAGES:
        for requirement in release.requirements(release.REPOSITORY_ROOT, package):
            dependency = release.by_name(requirement.name)
            assert order.index(dependency.key) < order.index(package.key), f"{package.name} needs {dependency.name}"
    assert order[-1] == release.META_KEY


def test_a_consistent_pre_release_passes(release: ModuleType, tmp_path: Path) -> None:
    assert release.check(write_repository(tmp_path, CONSISTENT)) == []


def test_a_minimum_beyond_the_version_of_the_checkout_fails(release: ModuleType, tmp_path: Path) -> None:
    packages = changed(explorer=("discopop-explorer", "0.0.1a4", ["discopop-library>=0.0.1a13"]))
    problems = release.check(write_repository(tmp_path, packages))
    assert len(problems) == 1 and "excludes discopop-library 0.0.1a12" in problems[0]


def test_an_invalid_version_fails(release: ModuleType, tmp_path: Path) -> None:
    packages = changed(GUI=("discopop-gui", "next", []))
    assert any("'next' is no valid version" in p for p in release.check(write_repository(tmp_path, packages)))


def test_the_root_package_must_require_every_package(release: ModuleType, tmp_path: Path) -> None:
    name, version, requirements = CONSISTENT["."]
    packages = changed(**{".": (name, version, [r for r in requirements if "gui" not in r])})
    problems = release.check(write_repository(tmp_path, packages))
    assert problems == ["pyproject.toml: discopop does not require discopop-gui"]


def test_a_final_release_must_not_name_pre_releases(release: ModuleType, tmp_path: Path) -> None:
    # a stable discopop whose minimums still name alphas would give its users alphas of the packages
    name, _, requirements = CONSISTENT["."]
    problems = release.check(write_repository(tmp_path, changed(**{".": (name, "5.0.3", requirements)})))
    assert len(problems) == 6 and all(
        "names a pre-release, but discopop 5.0.3 is a final release" in p for p in problems
    )


def test_a_consistent_final_release_passes(release: ModuleType, tmp_path: Path) -> None:
    final = {
        d: (n, "0.1.0" if d != "." else "5.0.3", [r.split(">=")[0] + ">=0.1.0" for r in rs])
        for d, (n, v, rs) in CONSISTENT.items()
    }
    assert release.check(write_repository(tmp_path, final)) == []


def published(versions: Dict[str, List[str]]):
    def lookup(name: str) -> Set[str]:
        return set(versions.get(name, []))

    return lookup


def test_the_plan_publishes_the_versions_missing_on_pypi(release: ModuleType, tmp_path: Path) -> None:
    root = write_repository(tmp_path, CONSISTENT)
    on_pypi = {
        "discopop-profiler": ["0.0.1a6", "0.0.1a7"],  # published already
        "discopop-gui": ["0.0.1a3"],
        "discopop_mcp_server": ["0.0.1a10"],  # the name on PyPI as the package declares it
    }
    plan = release.plan(root, published(on_pypi))
    assert list(plan) == [p.key for p in release.PACKAGES]
    assert plan == {
        "hotspot_detection": "0.0.1a4",
        "profiler": None,
        "library": "0.0.1a12",
        "explorer": "0.0.1a4",
        "gui": "0.0.1a4",
        "mcp_server": None,
        "discopop": "5.0.3a3",
    }


def test_the_plan_compares_normalized_versions(release: ModuleType, tmp_path: Path) -> None:
    root = write_repository(tmp_path, changed(GUI=("discopop-gui", "0.0.1.a4", [])))
    assert release.plan(root, published({"discopop-gui": ["0.0.1a4"]}))["gui"] is None


def test_the_plan_is_written_for_the_workflow(release: ModuleType, tmp_path: Path, monkeypatch, capsys) -> None:
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    release.write_github_output({"library": "0.0.1a12", "gui": None})
    lines = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert json.loads(lines["plan"]) == {"library": True, "gui": False}
    assert json.loads(lines["versions"]) == {"library": "0.0.1a12"}
    assert lines["any"] == "true"


def test_main_fails_on_problems_before_asking_pypi(release: ModuleType, tmp_path: Path, monkeypatch) -> None:
    root = write_repository(tmp_path, changed(GUI=("discopop-gui", "next", [])))
    monkeypatch.setattr(release, "published_versions", lambda name: pytest.fail("PyPI asked"))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    assert release.main(["plan", "--root", str(root)]) == 1
    assert os.environ.get("GITHUB_OUTPUT") is None

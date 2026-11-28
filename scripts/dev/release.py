#!/usr/bin/env python3
# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Versions of the DiscoPoP packages: checks for the CI and the release plan of the workflow "Release".

A release is a change of ``VERSION`` files merged into master: the workflow publishes every package whose version is
not on PyPI yet (``plan``), in ``PACKAGES`` order (dependencies first, the root package ``discopop`` last).

``check`` (offline, a step of the CI job ``static_checks``) fails if

- a ``VERSION`` is no valid version (PEP 440)
- a requirement on another DiscoPoP package excludes that package's ``VERSION`` in the checkout, e.g. a minimum
  raised beyond it: the packages of one checkout must install together
- the root package does not require every other package
- a package with a final version requires a DiscoPoP package with a specifier naming a pre-release (e.g.
  ``>=0.0.1a11``): pip then installs pre-releases of it for users of the stable release, too

``plan`` (queries PyPI) prints the packages to publish and, in GitHub Actions, writes them to ``$GITHUB_OUTPUT``
(``plan``: a JSON object ``{key: true|false}``, ``versions``: ``{key: version}``, ``any``: ``true|false``).

Usage: ``python3 scripts/dev/release.py check|plan [--root DIR]``. Needs ``packaging``.
"""

import argparse
import json
import os
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Set

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

PYPI_URL = "https://pypi.org/pypi/{name}/json"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Package:
    key: str  # used in the workflow (outputs, step conditions)
    name: str  # on PyPI
    directory: str  # relative to the repository root, holds pyproject.toml and VERSION
    tag_prefix: str  # the tag of a release is tag_prefix + version


# in publishing order: every package after the DiscoPoP packages it requires
PACKAGES = (
    Package("hotspot_detection", "discopop-hotspot-detection", "hotspot_detection", "hotspot_detection_v"),
    Package("profiler", "discopop-profiler", "profiler", "profiler_v"),
    Package("gui", "discopop-gui", "GUI", "gui_v"),
    Package("library", "discopop-library", "library", "library_v"),
    Package("explorer", "discopop-explorer", "explorer", "explorer_v"),
    Package("mcp_server", "discopop_mcp_server", "mcp_server", "mcp_server_v"),
    Package("discopop", "discopop", ".", "v"),
)
META_KEY = "discopop"


def read_version(root: Path, package: Package) -> str:
    return (root / package.directory / "VERSION").read_text().strip()


def requirements(root: Path, package: Package) -> List[Requirement]:
    """The requirements of ``package`` on other DiscoPoP packages, optional dependencies included."""
    with open(root / package.directory / "pyproject.toml", "rb") as f:
        project = tomllib.load(f)["project"]
    texts = list(project.get("dependencies", []))
    for extra in project.get("optional-dependencies", {}).values():
        texts += extra
    names = {canonicalize_name(p.name) for p in PACKAGES}
    return [r for r in map(Requirement, texts) if canonicalize_name(r.name) in names]


def by_name(name: str) -> Package:
    return next(p for p in PACKAGES if canonicalize_name(p.name) == canonicalize_name(name))


def check(root: Path) -> List[str]:
    """The problems of the versions and requirements in the checkout at ``root``."""
    problems: List[str] = []
    versions: Dict[str, Version] = {}
    for package in PACKAGES:
        text = read_version(root, package)
        try:
            versions[package.key] = Version(text)
        except InvalidVersion:
            problems.append(f"{package.directory}/VERSION: {text!r} is no valid version (PEP 440)")
    for package in PACKAGES:
        required: Set[str] = set()
        for requirement in requirements(root, package):
            dependency = by_name(requirement.name)
            required.add(dependency.key)
            version = versions.get(dependency.key)
            if version is None:
                continue
            where = f"{package.directory}/pyproject.toml: {requirement}"
            if not requirement.specifier.contains(version, prereleases=True):
                problems.append(f"{where} excludes {dependency.name} {version} of {dependency.directory}/VERSION")
            own = versions.get(package.key)
            if own is not None and not own.is_prerelease and requirement.specifier.prereleases:
                problems.append(
                    f"{where} names a pre-release, but {package.name} {own} is a final release: pip would install "
                    f"pre-releases of {dependency.name} for users of the stable release"
                )
        if package.key == META_KEY:
            for missing in sorted({p.key for p in PACKAGES if p.key != META_KEY} - required):
                problems.append(f"pyproject.toml: {package.name} does not require {by_key(missing).name}")
    return problems


def by_key(key: str) -> Package:
    return next(p for p in PACKAGES if p.key == key)


def published_versions(name: str) -> Set[str]:
    """The versions of ``name`` on PyPI (yanked ones included: PyPI never accepts a version twice)."""
    try:
        with urllib.request.urlopen(PYPI_URL.format(name=name), timeout=30) as response:
            return set(json.load(response).get("releases", {}))
    except urllib.error.HTTPError as e:
        if e.code == 404:  # a project that was never published
            return set()
        raise


def plan(root: Path, published: Callable[[str], Set[str]] = published_versions) -> Dict[str, Optional[str]]:
    """``{key: version to publish, or None}`` for every package, in ``PACKAGES`` order."""
    result: Dict[str, Optional[str]] = {}
    for package in PACKAGES:
        version = read_version(root, package)
        known = {str(Version(v)) for v in published(package.name) if _valid(v)}
        result[package.key] = None if str(Version(version)) in known else version
    return result


def _valid(text: str) -> bool:
    try:
        Version(text)
        return True
    except InvalidVersion:
        return False


def write_github_output(selected: Dict[str, Optional[str]]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if not output:
        return
    with open(output, "a") as f:
        f.write(f"plan={json.dumps({k: v is not None for k, v in selected.items()})}\n")
        f.write(f"versions={json.dumps({k: v for k, v in selected.items() if v is not None})}\n")
        f.write(f"any={'true' if any(v is not None for v in selected.values()) else 'false'}\n")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("command", choices=("check", "plan"))
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT, help="repository root (default: this checkout)")
    args = parser.parse_args(argv)
    problems = check(args.root)
    for problem in problems:
        print(f"ERROR: {problem}", file=sys.stderr)
    if problems:
        return 1
    if args.command == "check":
        print("The versions and the requirements between the DiscoPoP packages are consistent.")
        return 0
    selected = plan(args.root)
    for package in PACKAGES:
        version = selected[package.key]
        state = f"publish {version} (tag {package.tag_prefix}{version})" if version else "already on PyPI"
        print(f"{package.name:28} {read_version(args.root, package):12} {state}")
    if not any(selected.values()):
        print("Nothing to publish: every VERSION is on PyPI already.")
    write_github_output(selected)
    return 0


if __name__ == "__main__":
    sys.exit(main())

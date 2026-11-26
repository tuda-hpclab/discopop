#!/usr/bin/env python3
# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Install the newest published DiscoPoP release of a channel from PyPI into a new venv and test it end to end.

Shows whether the versions on PyPI work together, independently of the checkout: only the example program
(``example/example.cpp``) is taken from it. Channels:

- ``stable``: ``pip install discopop``, the newest final release
- ``pre-release``: ``pip install --pre discopop``, the newest release including pre-releases; ``--pre`` also takes
  the pre-releases of the third-party dependencies, which this check therefore tests, too

Both are the commands of the installation guide (``docs/setup/discopop.md``); the check verifies that they install
the newest version of every DiscoPoP package of the channel.

Checks, all of them are run and reported:

1. the installation succeeds and ``pip check`` finds no conflicting requirements
2. every DiscoPoP package is installed, at least in the newest version on PyPI of its channel (a pip falling back to
   older versions would hide an incompatibility of the newest ones); on the stable channel, no pre-release of a
   package with a final release (pip takes pre-releases for a requirement whose minimum names one)
3. every DiscoPoP command starts (``--help``), except the compiler wrappers, which item 4 runs
4. the example is instrumented (``discopop_cxx``), run, and explored (``discopop_explorer``), and the explorer
   writes at least one parallelization suggestion

Runs in a temporary directory outside the checkout, with a HOME of its own (the explorer of older releases checks
GitHub for updates). Needs the system packages of the installation guide (LLVM, clang, cmake, boost), as the profiler
is built from its source distribution. Usage: ``python3 scripts/dev/check_published_installation.py --channel
pre-release [--work-dir DIR]``; exits with 1 if a check fails.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

CHANNELS = ("stable", "pre-release")
CHANNEL_TITLES = {"stable": "stable release", "pre-release": "pre-release"}
META_PACKAGE = "discopop"
COMPONENTS = (
    "discopop-profiler",
    "discopop-library",
    "discopop-explorer",
    "discopop-gui",
    "discopop-hotspot-detection",
    "discopop-mcp-server",
)
COMPILER_WRAPPERS = ("discopop_cc", "discopop_cxx")
PYPI_URL = "https://pypi.org/pypi/{name}/json"
EXAMPLE_DIR = Path(__file__).resolve().parents[2] / "example"
INSIDE_VENV_FLAG = "--inside-venv"
COMMAND_TIMEOUT_S = 120
LOG_TAIL_LINES = 60


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--channel", choices=CHANNELS, required=True)
    parser.add_argument("--work-dir", type=Path, help="directory for the venv and the example (default: a new one)")
    parser.add_argument(INSIDE_VENV_FLAG, action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.inside_venv:
        return Check(args.channel, args.work_dir).run()
    # the version logic needs `packaging`, which the system python may lack: continue in the test venv
    work_dir = (args.work_dir or Path(tempfile.mkdtemp(prefix="discopop_published_"))).resolve()
    venv = work_dir / "venv"
    print(f"Working directory: {work_dir}", flush=True)
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    python = venv / "bin" / "python"
    subprocess.run([str(python), "-m", "pip", "install", "--quiet", "--upgrade", "pip", "packaging"], check=True)
    command = [str(python), "-I", __file__, "--channel", args.channel, "--work-dir", str(work_dir), INSIDE_VENV_FLAG]
    return subprocess.run(command, cwd=work_dir).returncode


# --- runs in the test venv ---


def release_versions(name: str) -> List[str]:
    """The versions of ``name`` on PyPI that have files and are not yanked entirely."""
    for attempt in range(3):
        try:
            with urllib.request.urlopen(PYPI_URL.format(name=name), timeout=30) as response:
                releases = json.load(response).get("releases", {})
            break
        except OSError:
            if attempt == 2:
                raise
            time.sleep(10)
    return [
        version
        for version, files in releases.items()
        if files and not all(isinstance(f, dict) and f.get("yanked") for f in files)
    ]


def newest(versions: Sequence[str], stable: bool) -> Optional[str]:
    """The newest of ``versions``; on the stable channel the newest final release, unless there is none (as pip)."""
    from packaging.version import InvalidVersion, Version

    parsed = []
    for text in versions:
        try:
            parsed.append(Version(text))
        except InvalidVersion:
            continue
    candidates = [v for v in parsed if not v.is_prerelease] if stable else parsed
    candidates = candidates or parsed
    return str(max(candidates)) if candidates else None


class Check:
    def __init__(self, channel: str, work_dir: Path) -> None:
        self.channel = channel
        self.stable = channel == "stable"
        self.title = f"Newest published {CHANNEL_TITLES[channel]}"
        self.work_dir = work_dir
        self.bin_dir = Path(sys.executable).parent
        self.home = work_dir / "home"
        self.failures: List[str] = []
        self.summary: List[str] = []

    # --- reporting ---

    def fail(self, check: str, message: str, log: str = "") -> None:
        self.failures.append(f"{check}: {message}")
        print(f"FAILED  {check}: {message}", flush=True)
        if log:
            print("\n".join(log.splitlines()[-LOG_TAIL_LINES:]), flush=True)
        if os.environ.get("GITHUB_ACTIONS"):
            print(f"::error title={self.title}::{check}: {message}", flush=True)

    def passed(self, check: str, message: str = "") -> None:
        print(f"ok      {check}{': ' + message if message else ''}", flush=True)

    def group(self, title: str) -> None:
        if os.environ.get("GITHUB_ACTIONS"):
            print("::endgroup::", flush=True)
            print(f"::group::{title}", flush=True)
        else:
            print(f"\n=== {title}", flush=True)

    # --- helpers ---

    def environment(self) -> Dict[str, str]:
        env = dict(os.environ)
        env["PATH"] = f"{self.bin_dir}{os.pathsep}{env.get('PATH', '')}"
        env["HOME"] = str(self.home)
        env["QT_QPA_PLATFORM"] = "offscreen"
        for variable in ("DOT_DISCOPOP", "DP_PROJECT_ROOT_DIR", "PYTHONPATH", "VIRTUAL_ENV"):
            env.pop(variable, None)
        return env

    def execute(self, command: Sequence[str], cwd: Path, timeout: Optional[float] = None) -> Tuple[int, str]:
        try:
            result = subprocess.run(
                list(command),
                cwd=cwd,
                env=self.environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            output = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode(errors="replace")
            return -1, f"{output}\n(no result after {timeout} s)"
        return result.returncode, result.stdout

    def prepare_home(self) -> None:
        settings = self.home / ".discopop_config" / "auto_updater" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"automatic_check_active": False, "enable_interactive_notifications": False}))

    # --- the checks ---

    def run(self) -> int:
        self.prepare_home()
        self.group(f"{self.title} of DiscoPoP")
        target = newest(release_versions(META_PACKAGE), self.stable)
        if target is None:
            self.fail("release", f"no release of {META_PACKAGE} on PyPI")
            return self.finish()
        print(f"{self.title} of {META_PACKAGE}: {target}", flush=True)
        if self.install(target):
            self.check_requirements()
            self.check_versions()
            self.check_commands()
            self.check_example()
        return self.finish()

    def install(self, target: str) -> bool:
        command = ["pip", "install"] + ([] if self.stable else ["--pre"]) + [META_PACKAGE]
        self.group(" ".join(command))
        start = time.monotonic()
        code, output = self.execute([sys.executable, "-m"] + command, self.work_dir)
        duration = time.monotonic() - start
        if code != 0:
            self.fail("installation", f"{' '.join(command)} failed (exit code {code})", output)
            return False
        self.passed("installation", f"{' '.join(command)} in {duration:.0f} s (newest: {META_PACKAGE} {target})")
        return True

    def check_requirements(self) -> None:
        self.group("pip check")
        code, output = self.execute([sys.executable, "-m", "pip", "check"], self.work_dir)
        if code != 0:
            self.fail("requirements", "pip check reports conflicting requirements", output)
        else:
            self.passed("requirements", "pip check finds no conflicts")

    def check_versions(self) -> None:
        from importlib.metadata import PackageNotFoundError, version

        from packaging.version import Version

        self.group("Installed versions")
        self.summary.append("| Package | Installed | Newest on PyPI |")
        self.summary.append("|---|---|---|")
        for name in (META_PACKAGE,) + COMPONENTS:
            expected = newest(release_versions(name), self.stable)
            try:
                installed: Optional[str] = version(name)
            except PackageNotFoundError:
                installed = None
            self.summary.append(f"| {name} | {installed or 'missing'} | {expected or 'none'} |")
            if installed is None:
                self.fail("versions", f"{name} is not installed")
            elif expected is not None and Version(installed) < Version(expected):
                self.fail("versions", f"{name} {installed} is installed, but {expected} is the newest on PyPI")
            elif self.stable and Version(installed).is_prerelease and not Version(expected or installed).is_prerelease:
                # pip takes pre-releases for a requirement whose minimum names one (e.g. >=0.0.1a11)
                self.fail(
                    "versions",
                    f"the pre-release {name} {installed} is installed, although {expected} is a final release: "
                    "a requirement on it names a pre-release as its minimum",
                )
            else:
                self.passed("versions", f"{name} {installed}")

    def commands(self) -> List[str]:
        from importlib.metadata import PackageNotFoundError, distribution

        names: Set[str] = set()
        for package in (META_PACKAGE,) + COMPONENTS:
            try:
                entry_points = distribution(package).entry_points
            except PackageNotFoundError:
                continue
            names.update(e.name for e in entry_points if e.group == "console_scripts")
        return sorted(names - set(COMPILER_WRAPPERS))

    def check_commands(self) -> None:
        self.group("Commands (--help)")
        for name in self.commands():
            code, output = self.execute([str(self.bin_dir / name), "--help"], self.work_dir, COMMAND_TIMEOUT_S)
            if code != 0:
                self.fail("commands", f"{name} --help failed (exit code {code})", output)
            else:
                self.passed("commands", name)

    def check_example(self) -> None:
        self.group("Example: instrument, profile, explore")
        example = self.work_dir / "example"
        shutil.rmtree(example, ignore_errors=True)
        shutil.copytree(EXAMPLE_DIR, example)
        steps = [
            ("instrumentation", ["discopop_cxx", "example.cpp", "-o", "a.out"], example),
            ("profiling", ["./a.out"], example),
            ("pattern detection", ["discopop_explorer"], example / ".discopop"),
        ]
        for step, command, cwd in steps:
            if not cwd.is_dir():
                self.fail("example", f"{step}: {cwd} does not exist")
                return
            code, output = self.execute(command, cwd)
            if code != 0:
                self.fail("example", f"{step} failed (exit code {code}): {' '.join(command)}", output)
                return
            self.passed("example", step)
        patches = example / ".discopop" / "patch_generator"
        suggestions = sorted(p.name for p in patches.iterdir()) if patches.is_dir() else []
        if not suggestions:
            self.fail("example", f"the explorer wrote no parallelization suggestion to {patches}")
        else:
            self.passed("example", f"{len(suggestions)} parallelization suggestions")

    def finish(self) -> int:
        if os.environ.get("GITHUB_ACTIONS"):
            print("::endgroup::", flush=True)
        verdict = "passed" if not self.failures else f"{len(self.failures)} failed check(s)"
        print(f"\n{self.title}: {verdict}", flush=True)
        for failure in self.failures:
            print(f"  - {failure}", flush=True)
        summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_file:
            lines = [f"### {self.title}: {verdict}", ""]
            lines += [f"- {failure}" for failure in self.failures]
            lines += [""] + self.summary
            with open(summary_file, "a") as f:
                f.write("\n".join(lines) + "\n")
        return 1 if self.failures else 0


if __name__ == "__main__":
    sys.exit(main())

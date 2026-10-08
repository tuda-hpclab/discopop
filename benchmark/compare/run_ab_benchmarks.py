# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Measure two versions of DiscoPoP with the pass overhead and the callback benchmark, interleaved.

The version under test ("head") is the one this script belongs to and whose venv runs it. The version to compare
with ("base") is given by the Python interpreter of a venv with its profiler installed (``--base-python``) and, for
the callback benchmark, by a checkout of its sources (``--base-source-dir``). Both versions are measured with the
drivers of the head, so the same programs and the same procedure are used on both sides.

The versions alternate round by round (head, base, base, head, ...), so that a change of the machine's speed
during the job affects both alike. The raw reports go to ``--results-dir``, see ``benchmark_compare/results.py``;
``compare_benchmarks.py`` turns them into the report.

A failure of the head fails the run (exit code 1), as the drivers do on their own. A failure of the base only
removes it from the comparison: the report then says why and shows the head alone.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from benchmark_compare.results import BASE, HEAD, Manifest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PASS_DRIVER = REPOSITORY_ROOT / "benchmark" / "pass_overhead" / "run_pass_benchmark.py"
CALLBACK_DRIVER = REPOSITORY_ROOT / "benchmark" / "injected_functions" / "run_callback_benchmark.py"


class BaseUnavailable(Exception):
    """The version to compare with cannot be measured; the message says why."""


def _run(command: Sequence[str], what: str) -> bool:
    print(f"\n=== {what}\n$ {' '.join(command)}", flush=True)
    return subprocess.run(list(command)).returncode == 0


def find_base_profiler(base_python: Path) -> Tuple[Path, Path]:
    """The pass plugin and the directory of the runtime library installed in the venv of ``base_python``."""
    if not base_python.is_file():
        raise BaseUnavailable(f"its profiler could not be built ({base_python} does not exist)")
    query = (
        "import json, site, sysconfig; "
        "print(json.dumps([*site.getsitepackages(), sysconfig.get_paths()['purelib']]))"
    )
    completed = subprocess.run([str(base_python), "-c", query], capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise BaseUnavailable(f"its venv does not work: {completed.stderr.strip()}")
    for directory in json.loads(completed.stdout):
        libraries = Path(directory) / "discopop-profiler.libs"
        for plugin_name in ("LLVMDiscoPoP.so", "LLVMDiscoPoP.dylib"):
            if (libraries / plugin_name).is_file() and (libraries / "libDiscoPoP_RT.a").is_file():
                return libraries / plugin_name, libraries
    raise BaseUnavailable("its venv has no installed profiler")


def _write_manifest(directory: Path, manifest: Manifest) -> None:
    if manifest.base_available:
        manifest.base_note = ""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps(manifest.to_json(), indent=2) + "\n")


def _new_manifest(arguments: argparse.Namespace, rounds: int, **settings: object) -> Manifest:
    return Manifest(
        head_label=arguments.head_label,
        base_label=arguments.base_label,
        base_available=False,
        base_note=arguments.base_note or "no version to compare with",
        rounds=rounds,
        settings=dict(settings),
    )


def _order(round_number: int) -> List[str]:
    """Head first in odd rounds, base first in even ones."""
    return [HEAD, BASE] if round_number % 2 == 1 else [BASE, HEAD]


def run_pass_overhead(arguments: argparse.Namespace) -> int:
    directory: Path = arguments.results_dir / "pass_overhead"
    shutil.rmtree(directory, ignore_errors=True)
    manifest = _new_manifest(arguments, arguments.rounds, repetitions=arguments.repetitions)

    base_options: Optional[List[str]] = None
    if arguments.base_python is not None:
        try:
            plugin, rtlib_dir = find_base_profiler(arguments.base_python)
            base_options = ["--plugin", str(plugin), "--rtlib-dir", str(rtlib_dir)]
        except BaseUnavailable as reason:
            manifest.base_note = f"the version to compare with is not available: {reason}"

    try:
        for round_number in range(1, arguments.rounds + 1):
            for side in _order(round_number):
                if side == BASE and base_options is None:
                    continue
                command = [
                    sys.executable,
                    str(PASS_DRIVER),
                    "--repetitions",
                    str(arguments.repetitions),
                    "--json-out",
                    str(directory / side / f"round_{round_number}.json"),
                ]
                if arguments.filter:
                    command += ["--filter", arguments.filter]
                if side == BASE and base_options is not None:
                    command += base_options
                if not _run(command, f"pass overhead, round {round_number}, {side}"):
                    if side == HEAD:
                        return 1
                    base_options = None
                    manifest.base_note = "the version to compare with failed the pass overhead benchmark"
        manifest.base_available = base_options is not None
    finally:
        _write_manifest(directory, manifest)
    return 0


def _build_callback_benchmark(source: Path, build: Path, jobs: int, side: str) -> bool:
    command = [
        sys.executable,
        str(CALLBACK_DRIVER),
        "--build-only",
        "--source-dir",
        str(source),
        "--build-dir",
        str(build),
        "-j",
        str(jobs),
    ]
    return _run(command, f"callback benchmark, build {side}")


def run_callbacks(arguments: argparse.Namespace) -> int:
    results: Path = arguments.results_dir
    callbacks_dir, breakdown_dir = results / "callbacks", results / "breakdown"
    shutil.rmtree(callbacks_dir, ignore_errors=True)
    shutil.rmtree(breakdown_dir, ignore_errors=True)
    manifest = _new_manifest(
        arguments, arguments.rounds, repetitions=arguments.repetitions, min_time=arguments.min_time
    )
    builds = {HEAD: arguments.head_build_dir, BASE: arguments.base_build_dir}

    if not _build_callback_benchmark(REPOSITORY_ROOT, builds[HEAD], arguments.jobs, HEAD):
        _write_manifest(callbacks_dir, manifest)
        return 1

    base_plugin: Optional[Path] = None
    if arguments.base_python is not None and arguments.base_source_dir is not None:
        try:
            base_plugin, _ = find_base_profiler(arguments.base_python)
            if not _build_callback_benchmark(arguments.base_source_dir, builds[BASE], arguments.jobs, BASE):
                raise BaseUnavailable("its callback benchmark does not build (it may predate the benchmark)")
            manifest.base_available = True
        except BaseUnavailable as reason:
            manifest.base_note = f"the version to compare with is not available: {reason}"

    try:
        for round_number in range(1, arguments.rounds + 1):
            for side in _order(round_number):
                if side == BASE and not manifest.base_available:
                    continue
                command = [
                    sys.executable,
                    str(CALLBACK_DRIVER),
                    "--no-build",
                    "--build-dir",
                    str(builds[side]),
                    "--repetitions",
                    str(arguments.repetitions),
                    "--min-time",
                    str(arguments.min_time),
                    "--json-out",
                    str(callbacks_dir / side / f"round_{round_number}.json"),
                ]
                (callbacks_dir / side).mkdir(parents=True, exist_ok=True)
                if not _run(command, f"callback benchmark, round {round_number}, {side}"):
                    if side == HEAD:
                        manifest.base_available = False
                        return 1
                    manifest.base_available = False
                    manifest.base_note = "the version to compare with failed the callback benchmark"
    finally:
        _write_manifest(callbacks_dir, manifest)

    if arguments.no_breakdown:
        return 0
    return run_breakdown(arguments, builds, base_plugin if manifest.base_available else None, breakdown_dir)


def run_breakdown(
    arguments: argparse.Namespace, builds: Dict[str, Path], base_plugin: Optional[Path], directory: Path
) -> int:
    """The callback breakdown of the pass overhead benchmark, once per version (it is read as a ranking)."""
    manifest = _new_manifest(arguments, 1, repetitions=arguments.breakdown_repetitions)
    if base_plugin is None:
        manifest.base_note = "the version to compare with has no callback benchmark"
    sides = [HEAD] + ([BASE] if base_plugin is not None else [])
    try:
        for side in sides:
            cmake = shutil.which("cmake") or "cmake"
            build = [cmake, "--build", str(builds[side]), "--target", "DiscoPoP_RT_BenchmarkVariants"]
            build += ["-j", str(arguments.jobs)]
            command = [
                sys.executable,
                str(PASS_DRIVER),
                "--callback-breakdown",
                "--repetitions",
                str(arguments.breakdown_repetitions),
                "--variants-dir",
                str(builds[side] / "profiler" / "rtlib"),
                "--json-out",
                str(directory / f"{side}.json"),
            ]
            if side == BASE and base_plugin is not None:
                command += ["--plugin", str(base_plugin)]
            succeeded = _run(build, f"runtime library variants, {side}") and _run(command, f"breakdown, {side}")
            if not succeeded:
                if side == HEAD:
                    return 1
                manifest.base_note = "the version to compare with failed the callback breakdown"
                return 0
        manifest.base_available = base_plugin is not None
    finally:
        _write_manifest(directory, manifest)
    return 0


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-dir", type=Path, required=True, help="where the raw results are written")
    parser.add_argument("--head-label", required=True, help="how the version under test is named in the report")
    parser.add_argument("--base-label", default="", help="how the version to compare with is named in the report")
    parser.add_argument("--base-python", type=Path, default=None, help="python of a venv with the base profiler")
    parser.add_argument("--base-note", default="", help="why there is no version to compare with, for the report")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4, help="parallel build jobs")
    subparsers = parser.add_subparsers(dest="benchmark", required=True)

    pass_overhead = subparsers.add_parser("pass-overhead", help="benchmark/pass_overhead, without the breakdown")
    pass_overhead.add_argument("--rounds", type=int, default=2, help="interleaved rounds per version (default: 2)")
    pass_overhead.add_argument("--repetitions", type=int, default=3, help="repetitions per round (default: 3)")
    pass_overhead.add_argument("--filter", default=None, help="only the programs whose name contains this")

    callbacks = subparsers.add_parser("callbacks", help="benchmark/injected_functions, then the callback breakdown")
    callbacks.add_argument("--rounds", type=int, default=3, help="interleaved rounds per version (default: 3)")
    callbacks.add_argument("--repetitions", type=int, default=5, help="repetitions per round (default: 5)")
    callbacks.add_argument("--min-time", type=float, default=0.1, help="seconds per repetition (default: 0.1)")
    callbacks.add_argument("--head-build-dir", type=Path, default=REPOSITORY_ROOT / "build_tests")
    callbacks.add_argument("--base-source-dir", type=Path, default=None, help="checkout of the version to compare with")
    callbacks.add_argument("--base-build-dir", type=Path, default=REPOSITORY_ROOT / "build_base")
    callbacks.add_argument("--no-breakdown", action="store_true", help="skip the callback breakdown")
    callbacks.add_argument("--breakdown-repetitions", type=int, default=1, help="repetitions of the breakdown")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parse_arguments(argv)
    if arguments.benchmark == "pass-overhead":
        return run_pass_overhead(arguments)
    return run_callbacks(arguments)


if __name__ == "__main__":
    sys.exit(main())

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Measure what each callback the DiscoPoP LLVM pass injects costs, split into call and body.

Runs the two builds of ``benchmark_injected_functions.cpp`` and puts them side by side:

``DiscoPoP_BM_Callbacks_Empty``
    linked against the runtime built with ``DP_BENCHMARK_EMPTY_CALLBACKS``, where every callback
    returns as soon as it has been entered. What it measures is the price of the added calls.

``DiscoPoP_BM_Callbacks``
    linked against the runtime as it is shipped. What it measures is the call plus the body.

Both binaries run the same benchmarks under the same names, so the body of a callback costs the
difference between the two -- and the loop that drives the measurement, being identical on both
sides, drops out of it.

Run ``python3 run_callback_benchmark.py --help`` for the available options.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

# the two binaries and the value of the dp_callback_bodies context each one has to report. The
# check is what keeps a mixed up pair of binaries from being reported as a runtime that costs
# nothing: both would carry bodies, and every difference below would come out as noise.
CALL_ONLY_BINARY = "DiscoPoP_BM_Callbacks_Empty"
FULL_BINARY = "DiscoPoP_BM_Callbacks"
EXPECTED_CONTEXT = {CALL_ONLY_BINARY: "disabled", FULL_BINARY: "enabled"}

# The result files the runtime insists on. It opens them from __dp_init, before main, so the
# directory has to exist before the binary is started -- see the note in the benchmark source.
# Their content is what a program without a single instrumented module has: no call state
# transitions, and state 0 as the state to start from.
PROFILER_INPUT_FILES = {
    "callpath_state_transitions.txt": "",
    "callpath_state_return_targets.txt": "",
    "initial_stateID.txt": "0\n",
}

# benchmarks that drive two callbacks per iteration, because the two are the halves of one bracket
# and measuring either on its own would let the runtime's bookkeeping run away. Reported as they
# are measured; the column header says so.
PAIRED_BENCHMARKS = frozenset({"__dp_func_entry+__dp_func_exit", "__dp_loop_entry+__dp_loop_exit"})


# Google Benchmark reports every row in the unit it picked for that benchmark, so the unit is read
# off the row rather than assumed to be the nanoseconds these callbacks land in today.
NANOSECONDS_PER_UNIT = {"ns": 1.0, "us": 1e3, "ms": 1e6, "s": 1e9}


class BenchmarkError(RuntimeError):
    """Raised when the benchmark cannot be carried out or its result cannot be trusted."""


@dataclass
class Measurement:
    """What one binary reported for one benchmark."""

    name: str
    nanoseconds: float
    deviation: float
    iterations: int


@dataclass
class Comparison:
    """One callback, measured in both builds."""

    name: str
    call_only: Measurement
    full: Measurement

    @property
    def body_nanoseconds(self) -> float:
        return self.full.nanoseconds - self.call_only.nanoseconds

    @property
    def body_share(self) -> float:
        if self.full.nanoseconds <= 0.0:
            return 0.0
        return self.body_nanoseconds / self.full.nanoseconds

    @property
    def is_paired(self) -> bool:
        return self.name in PAIRED_BENCHMARKS


def build_binaries(build_directory: Path, jobs: int) -> None:
    """Configure and build both benchmark binaries."""

    cmake = shutil.which("cmake")
    if cmake is None:
        raise BenchmarkError("cmake was not found on PATH")

    configure = [
        cmake,
        "-S",
        str(REPOSITORY_ROOT),
        "-B",
        str(build_directory),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DDP_BUILD_UNITTESTS=1",
    ]
    print("Configuring: " + " ".join(configure), flush=True)
    if subprocess.run(configure).returncode != 0:
        raise BenchmarkError("cmake failed to configure the build")

    build = [cmake, "--build", str(build_directory), "--target", FULL_BINARY, CALL_ONLY_BINARY, "-j", str(jobs)]
    print("Building: " + " ".join(build), flush=True)
    if subprocess.run(build).returncode != 0:
        raise BenchmarkError("cmake failed to build the benchmark binaries")


def prepare_runtime_directory(directory: Path) -> Dict[str, str]:
    """Create the directory the runtime writes to and return the environment that points at it."""

    profiler_directory = directory / "profiler"
    profiler_directory.mkdir(parents=True, exist_ok=True)
    for file_name, content in PROFILER_INPUT_FILES.items():
        (profiler_directory / file_name).write_text(content)

    environment = dict(os.environ)
    environment["DOT_DISCOPOP"] = str(directory)
    return environment


def run_binary(
    binary: Path,
    environment: Dict[str, str],
    output_file: Path,
    repetitions: int,
    minimum_time: float,
    benchmark_filter: Optional[str],
) -> Dict[str, Measurement]:
    """Run one benchmark binary and read its measurements back."""

    command = [
        str(binary),
        "--benchmark_format=console",
        f"--benchmark_out={output_file}",
        "--benchmark_out_format=json",
        f"--benchmark_repetitions={repetitions}",
        f"--benchmark_min_time={minimum_time}",
    ]
    if benchmark_filter is not None:
        command.append(f"--benchmark_filter={benchmark_filter}")

    print(f"Running {binary.name}", flush=True)
    if subprocess.run(command, env=environment).returncode != 0:
        raise BenchmarkError(f"{binary.name} exited with an error")

    return read_measurements(binary.name, output_file, repetitions)


def read_measurements(binary_name: str, output_file: Path, repetitions: int) -> Dict[str, Measurement]:
    """Pick the median of each benchmark out of a Google Benchmark JSON report."""

    try:
        report = json.loads(output_file.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise BenchmarkError(f"{binary_name} did not produce a readable report: {error}")

    context = report.get("context", {})
    reported_bodies = context.get("dp_callback_bodies")
    expected_bodies = EXPECTED_CONTEXT[binary_name]
    if reported_bodies != expected_bodies:
        raise BenchmarkError(
            f"{binary_name} reports dp_callback_bodies={reported_bodies!r}, expected {expected_bodies!r}. "
            "It was linked against the wrong runtime library."
        )

    medians: Dict[str, float] = {}
    deviations: Dict[str, float] = {}
    iterations: Dict[str, int] = {}
    samples: Dict[str, List[float]] = {}

    for entry in report.get("benchmarks", []):
        unit = NANOSECONDS_PER_UNIT.get(str(entry.get("time_unit", "ns")))
        if unit is None:
            raise BenchmarkError(f"{binary_name} reported an unknown time unit: {entry.get('time_unit')!r}")
        real_time = float(entry["real_time"]) * unit

        run_type = entry.get("run_type")
        base_name = str(entry.get("run_name", entry.get("name", "")))
        if run_type == "iteration":
            # the per repetition rows, kept so that a single repetition still yields a number
            samples.setdefault(base_name, []).append(real_time)
            iterations[base_name] = int(entry.get("iterations", 0))
        elif run_type == "aggregate":
            if entry.get("aggregate_name") == "median":
                medians[base_name] = real_time
            elif entry.get("aggregate_name") == "stddev":
                deviations[base_name] = real_time

    measurements: Dict[str, Measurement] = {}
    for name, values in samples.items():
        median = medians.get(name, statistics.median(values))
        deviation = deviations.get(name, 0.0)
        measurements[name] = Measurement(name, median, deviation, iterations.get(name, 0))

    if not measurements:
        raise BenchmarkError(f"{binary_name} reported no benchmarks (repetitions={repetitions})")
    return measurements


def compare(call_only: Dict[str, Measurement], full: Dict[str, Measurement]) -> List[Comparison]:
    """Join the two runs per callback, in the order the full run reported them."""

    missing = sorted(set(full) ^ set(call_only))
    if missing:
        raise BenchmarkError(
            "the two binaries did not run the same benchmarks, which they must for the difference "
            f"to mean anything. Only one of them has: {', '.join(missing)}"
        )
    return [Comparison(name, call_only[name], full[name]) for name in full]


def row_label(comparison: Comparison) -> str:
    return comparison.name + (" (2 calls)" if comparison.is_paired else "")


def format_table(comparisons: Sequence[Comparison]) -> str:
    """The comparison as a plain text table."""

    # measured rather than fixed: the bracketed entries carry a suffix and are long enough to push
    # every number on their row out of its column
    width = max([len("callback")] + [len(row_label(comparison)) for comparison in comparisons]) + 2

    header = f"{'callback':<{width}}{'call only':>12}{'call+body':>12}{'body':>12}{'body share':>13}"
    lines = [header, "-" * len(header)]
    for comparison in comparisons:
        lines.append(
            f"{row_label(comparison):<{width}}"
            f"{comparison.call_only.nanoseconds:>10.2f} ns"
            f"{comparison.full.nanoseconds:>10.2f} ns"
            f"{comparison.body_nanoseconds:>10.2f} ns"
            f"{comparison.body_share:>12.0%}"
        )
    return "\n".join(lines)


def format_markdown(comparisons: Sequence[Comparison]) -> str:
    """The comparison as a markdown section, for use as a CI job summary."""

    lines = [
        "## Cost of the injected callbacks",
        "",
        "`call only` is the runtime built with `DP_BENCHMARK_EMPTY_CALLBACKS`, where every callback",
        "returns as soon as it has been entered: what an instrumented program pays for the added",
        "calls. `body` is what the runtime does inside them, measured as the difference.",
        "",
        "| Callback | Call only | Call + body | Body | Body share |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for comparison in comparisons:
        name = f"`{comparison.name}`" + (" (2 calls)" if comparison.is_paired else "")
        lines.append(
            f"| {name} "
            f"| {comparison.call_only.nanoseconds:.2f} ns "
            f"| {comparison.full.nanoseconds:.2f} ns "
            f"| {comparison.body_nanoseconds:.2f} ns "
            f"| {comparison.body_share:.0%} |"
        )
    lines += [
        "",
        "_Median over the repetitions. The two bracketed entries drive both halves of their bracket "
        "per iteration, because measuring either on its own would let the runtime's bookkeeping run "
        "away over millions of iterations._",
        "",
    ]
    return "\n".join(lines)


def build_json_report(comparisons: Sequence[Comparison], repetitions: int, minimum_time: float) -> Dict[str, object]:
    """The comparison in machine readable form."""

    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "machine": platform.platform(),
        "repetitions": repetitions,
        "min_time_seconds": minimum_time,
        "callbacks": [
            {
                "name": comparison.name,
                "calls_per_iteration": 2 if comparison.is_paired else 1,
                "call_only_ns": comparison.call_only.nanoseconds,
                "call_only_stddev_ns": comparison.call_only.deviation,
                "full_ns": comparison.full.nanoseconds,
                "full_stddev_ns": comparison.full.deviation,
                "body_ns": comparison.body_nanoseconds,
                "body_share": comparison.body_share,
            }
            for comparison in comparisons
        ],
    }


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--build-dir",
        type=Path,
        default=REPOSITORY_ROOT / "build_tests",
        help="build directory holding the benchmark binaries (default: <repo>/build_tests)",
    )
    parser.add_argument("--no-build", action="store_true", help="use the binaries that are already built")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 4, help="parallel build jobs")
    parser.add_argument("--repetitions", type=int, default=5, help="repetitions per benchmark (default: 5)")
    parser.add_argument(
        "--min-time", type=float, default=0.1, help="seconds one repetition runs for at least (default: 0.1)"
    )
    parser.add_argument("--filter", default=None, help="only run the benchmarks matching this regular expression")
    parser.add_argument("--json-out", type=Path, default=None, help="write the comparison as JSON")
    parser.add_argument("--markdown-out", type=Path, default=None, help="write the comparison as markdown")
    return parser.parse_args(argv)


def locate_binaries(build_directory: Path) -> Tuple[Path, Path]:
    binaries = tuple(build_directory / "benchmark" / name for name in (CALL_ONLY_BINARY, FULL_BINARY))
    for binary in binaries:
        if not binary.is_file():
            raise BenchmarkError(
                f"{binary} does not exist. Build it with\n"
                f"  cmake -S . -B {build_directory} -DCMAKE_BUILD_TYPE=Release -DDP_BUILD_UNITTESTS=1\n"
                f"  cmake --build {build_directory} --target {FULL_BINARY} {CALL_ONLY_BINARY}"
            )
    return binaries[0], binaries[1]


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parse_arguments(argv)

    try:
        if not arguments.no_build:
            build_binaries(arguments.build_dir, arguments.jobs)
        call_only_binary, full_binary = locate_binaries(arguments.build_dir)

        with tempfile.TemporaryDirectory(prefix="discopop_callback_benchmark_") as scratch:
            scratch_path = Path(scratch)
            environment = prepare_runtime_directory(scratch_path / "dot_discopop")
            call_only = run_binary(
                call_only_binary,
                environment,
                scratch_path / "call_only.json",
                arguments.repetitions,
                arguments.min_time,
                arguments.filter,
            )
            full = run_binary(
                full_binary,
                environment,
                scratch_path / "full.json",
                arguments.repetitions,
                arguments.min_time,
                arguments.filter,
            )

        comparisons = compare(call_only, full)
    except BenchmarkError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print()
    print(format_table(comparisons))
    print()

    if arguments.json_out is not None:
        arguments.json_out.write_text(
            json.dumps(build_json_report(comparisons, arguments.repetitions, arguments.min_time), indent=2) + "\n"
        )
        print(f"JSON report written to {arguments.json_out}")
    if arguments.markdown_out is not None:
        arguments.markdown_out.write_text(format_markdown(comparisons))
        print(f"Markdown summary written to {arguments.markdown_out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

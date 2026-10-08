# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Compare compiling and running test programs with and without the DiscoPoP LLVM pass.

For every program in ``programs/`` two configurations are built from identical sources with
identical compiler flags. The ``baseline`` configuration is a plain clang invocation, the
``instrumented`` configuration additionally loads the ``LLVMDiscoPoP`` plugin and links the
DiscoPoP runtime library -- the same combination ``CXX_wrapper.sh`` uses, minus the AST dump.
Compile time, execution time and binary size are measured for both and reported side by side.

Run ``python3 run_pass_benchmark.py --help`` for the available options.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import site
import statistics
import subprocess
import sys
import sysconfig
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# flags shared by both configurations, mirroring the ones CXX_wrapper.sh applies
COMMON_COMPILE_FLAGS: Tuple[str, ...] = ("-g", "-O0", "-fno-discard-value-names", "-fPIC")

# clang versions the profiler supports, newest first (see profiler/CMakeLists.txt)
SUPPORTED_CLANG_VERSIONS: Tuple[int, ...] = (22, 21, 20, 19)

DESCRIPTION_MARKER = re.compile(r"^//\s*BENCHMARK:\s*(?P<description>.+?)\s*$", re.MULTILINE)

BASELINE = "baseline"
INSTRUMENTED = "instrumented"


class BenchmarkError(RuntimeError):
    """Raised when the benchmark cannot be carried out, e.g. because a program fails to build."""


@dataclass
class Program:
    """A single benchmark program."""

    name: str
    source: Path
    description: str


@dataclass
class Toolchain:
    """Everything needed to build both configurations."""

    cxx: Path
    cxx_version: str
    plugin: Path
    rtlib_dir: Path


@dataclass
class Measurement:
    """The measurements of one program in one configuration."""

    compile_seconds: List[float] = field(default_factory=list)
    run_seconds: List[float] = field(default_factory=list)
    binary_size_bytes: int = 0
    stdout: str = ""

    @property
    def compile_median(self) -> float:
        return statistics.median(self.compile_seconds)

    @property
    def run_median(self) -> float:
        return statistics.median(self.run_seconds)


@dataclass
class Comparison:
    """Baseline and instrumented measurements of one program, plus the derived factors."""

    program: Program
    baseline: Measurement
    instrumented: Measurement

    @property
    def compile_factor(self) -> float:
        return _factor(self.instrumented.compile_median, self.baseline.compile_median)

    @property
    def run_factor(self) -> float:
        return _factor(self.instrumented.run_median, self.baseline.run_median)

    @property
    def binary_size_factor(self) -> float:
        return _factor(float(self.instrumented.binary_size_bytes), float(self.baseline.binary_size_bytes))

    @property
    def output_preserved(self) -> bool:
        """Whether the instrumented run still produced the output of the baseline run.

        The runtime library writes progress messages to stdout, so the outputs cannot be compared
        verbatim. Every line the baseline printed has to show up in the instrumented output though.
        """
        instrumented_lines = set(self.instrumented.stdout.splitlines())
        return all(line in instrumented_lines for line in self.baseline.stdout.splitlines())


def _factor(instrumented: float, baseline: float) -> float:
    if baseline <= 0.0:
        return math.nan
    return instrumented / baseline


def _geometric_mean(values: Sequence[float]) -> float:
    usable = [value for value in values if value > 0.0 and math.isfinite(value)]
    if not usable:
        return math.nan
    return math.exp(sum(math.log(value) for value in usable) / len(usable))


# ---------------------------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------------------------


def discover_programs(programs_dir: Path, name_filter: Optional[str]) -> List[Program]:
    """Collect the benchmark programs from ``programs_dir``, sorted by name."""
    programs: List[Program] = []
    # absolute, because every program is compiled from its own working directory
    for source in sorted(programs_dir.resolve().glob("*.cpp")):
        name = source.stem
        if name_filter is not None and name_filter not in name:
            continue
        match = DESCRIPTION_MARKER.search(source.read_text())
        description = match.group("description") if match else ""
        programs.append(Program(name=name, source=source, description=description))
    if not programs:
        raise BenchmarkError(f"No benchmark programs found in {programs_dir}")
    return programs


def _candidate_library_dirs() -> List[Path]:
    """Directories that may hold the installed profiler artifacts, most specific first."""
    candidates: List[Path] = []
    for directory in [*site.getsitepackages(), sysconfig.get_paths()["purelib"]]:
        candidates.append(Path(directory) / "discopop-profiler.libs")
    user_site = site.getusersitepackages()
    if isinstance(user_site, str):
        candidates.append(Path(user_site) / "discopop-profiler.libs")
    # de-duplicate while keeping the order
    return list(dict.fromkeys(candidates))


def find_plugin(explicit: Optional[Path]) -> Path:
    """Locate ``LLVMDiscoPoP.{so,dylib}``."""
    if explicit is not None:
        if not explicit.is_file():
            raise BenchmarkError(f"The specified pass plugin does not exist: {explicit}")
        # absolute, because the compiler is invoked from a different working directory
        return explicit.resolve()
    for directory in _candidate_library_dirs():
        for filename in ("LLVMDiscoPoP.so", "LLVMDiscoPoP.dylib"):
            plugin = directory / filename
            if plugin.is_file():
                return plugin
    raise BenchmarkError(
        "Could not locate LLVMDiscoPoP.so. Install the profiler into the active environment "
        "(`pip install ./profiler`, without -e) or pass --plugin explicitly."
    )


def find_rtlib_dir(explicit: Optional[Path], plugin: Path) -> Path:
    """Locate the directory holding ``libDiscoPoP_RT.a``."""
    candidates = [explicit] if explicit is not None else [plugin.parent, *_candidate_library_dirs()]
    for directory in candidates:
        if directory is not None and (directory / "libDiscoPoP_RT.a").is_file():
            return directory.resolve()
    raise BenchmarkError(
        "Could not locate libDiscoPoP_RT.a. Install the profiler into the active environment "
        "(`pip install ./profiler`, without -e) or pass --rtlib-dir explicitly."
    )


def find_cxx(explicit: Optional[Path]) -> Path:
    """Locate a clang++ supported by the profiler."""
    if explicit is not None:
        resolved = shutil.which(str(explicit))
        if resolved is None:
            raise BenchmarkError(f"The specified compiler does not exist: {explicit}")
        return Path(resolved)
    for version in SUPPORTED_CLANG_VERSIONS:
        found = shutil.which(f"clang++-{version}")
        if found is not None:
            return Path(found)
    found = shutil.which("clang++")
    if found is not None:
        return Path(found)
    raise BenchmarkError("No supported clang++ (19-22) found in PATH. Install one or pass --cxx explicitly.")


def build_toolchain(cxx: Optional[Path], plugin: Optional[Path], rtlib_dir: Optional[Path]) -> Toolchain:
    resolved_cxx = find_cxx(cxx)
    resolved_plugin = find_plugin(plugin)
    version_output = subprocess.run(
        [str(resolved_cxx), "--version"], capture_output=True, text=True, check=False
    ).stdout
    return Toolchain(
        cxx=resolved_cxx,
        cxx_version=version_output.splitlines()[0].strip() if version_output else "unknown",
        plugin=resolved_plugin,
        rtlib_dir=find_rtlib_dir(rtlib_dir, resolved_plugin),
    )


# ---------------------------------------------------------------------------------------------
# measuring
# ---------------------------------------------------------------------------------------------


def compile_command(toolchain: Toolchain, program: Program, configuration: str, binary: Path) -> List[str]:
    """The compile command for one configuration.

    Both configurations use the same compiler and the same flags. The instrumented one adds the
    pass plugin and the runtime library, exactly as CXX_wrapper.sh does.
    """
    command = [str(toolchain.cxx), str(program.source), *COMMON_COMPILE_FLAGS]
    if configuration == INSTRUMENTED:
        command += [
            "-Xclang",
            "-load",
            "-Xclang",
            str(toolchain.plugin),
            "-Xclang",
            f"-fpass-plugin={toolchain.plugin}",
            "-Xlinker",
            f"-L{toolchain.rtlib_dir}",
            "-Xlinker",
            "-lDiscoPoP_RT",
        ]
        if platform.system() != "Darwin":
            # pthread is part of libSystem on macOS
            command += ["-Xlinker", "-lpthread"]
    command += ["-o", str(binary)]
    return command


def _timed_run(command: Sequence[str], cwd: Path, env: Dict[str, str], what: str) -> Tuple[float, str]:
    """Run ``command`` and return its wall clock time together with its stdout."""
    start = time.perf_counter()
    completed = subprocess.run(list(command), cwd=str(cwd), env=env, capture_output=True, text=True, check=False)
    duration = time.perf_counter() - start
    if completed.returncode != 0:
        raise BenchmarkError(
            f"{what} failed with exit code {completed.returncode}\n"
            f"command: {' '.join(command)}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return duration, completed.stdout


def measure(
    toolchain: Toolchain,
    program: Program,
    configuration: str,
    work_dir: Path,
    repetitions: int,
) -> Measurement:
    """Compile and run one program in one configuration, ``repetitions`` times after a warm up."""
    run_dir = work_dir / program.name / configuration
    run_dir.mkdir(parents=True, exist_ok=True)
    binary = run_dir / f"{program.name}.exe"

    # The pass writes its static analysis results (file mapping, id counters, ...) next to the
    # program. Keeping that inside the run directory keeps repetitions independent of each other
    # and keeps the repository clean.
    dot_discopop = run_dir / ".discopop"
    env = dict(os.environ)
    env["DOT_DISCOPOP"] = str(dot_discopop)

    command = compile_command(toolchain, program, configuration, binary)
    measurement = Measurement()

    for repetition in range(repetitions + 1):
        # the id counters the pass maintains are cumulative, so every compilation starts fresh
        shutil.rmtree(dot_discopop, ignore_errors=True)
        duration, _ = _timed_run(command, run_dir, env, f"compiling {program.name} ({configuration})")
        if repetition > 0:  # the first iteration is a warm up and is discarded
            measurement.compile_seconds.append(duration)

    for repetition in range(repetitions + 1):
        duration, stdout = _timed_run([str(binary)], run_dir, env, f"running {program.name} ({configuration})")
        if repetition > 0:
            measurement.run_seconds.append(duration)
            measurement.stdout = stdout

    measurement.binary_size_bytes = binary.stat().st_size
    return measurement


def run_benchmark(
    toolchain: Toolchain,
    programs: Sequence[Program],
    work_dir: Path,
    repetitions: int,
) -> List[Comparison]:
    comparisons: List[Comparison] = []
    for program in programs:
        print(f"  {program.name} ...", end="", flush=True)
        baseline = measure(toolchain, program, BASELINE, work_dir, repetitions)
        instrumented = measure(toolchain, program, INSTRUMENTED, work_dir, repetitions)
        comparison = Comparison(program=program, baseline=baseline, instrumented=instrumented)
        comparisons.append(comparison)
        print(f" compile x{comparison.compile_factor:.2f}, runtime x{comparison.run_factor:.2f}")
    return comparisons


# ---------------------------------------------------------------------------------------------
# reporting
# ---------------------------------------------------------------------------------------------


def _format_factor(value: float) -> str:
    return "n/a" if math.isnan(value) else f"x{value:.2f}"


def format_table(comparisons: Sequence[Comparison]) -> str:
    """The side by side comparison as a plain text table."""
    name_width = max([len("geometric mean"), *(len(c.program.name) for c in comparisons)])
    header = f"{'':<{name_width}}  {'compile time [s]':^24}  {'run time [s]':^24}  {'binary size [KiB]':^24}"
    sub_header = f"{'program':<{name_width}}  " + "  ".join([f"{'base':>7} {'+pass':>8} {'factor':>7}"] * 3)
    separator = "-" * len(sub_header)

    lines = [header, sub_header, separator]
    for comparison in comparisons:
        lines.append(
            f"{comparison.program.name:<{name_width}}  "
            f"{comparison.baseline.compile_median:>7.3f} {comparison.instrumented.compile_median:>8.3f} "
            f"{_format_factor(comparison.compile_factor):>7}  "
            f"{comparison.baseline.run_median:>7.3f} {comparison.instrumented.run_median:>8.3f} "
            f"{_format_factor(comparison.run_factor):>7}  "
            f"{comparison.baseline.binary_size_bytes / 1024:>7.0f} "
            f"{comparison.instrumented.binary_size_bytes / 1024:>8.0f} "
            f"{_format_factor(comparison.binary_size_factor):>7}"
        )
    lines.append(separator)
    lines.append(
        f"{'geometric mean':<{name_width}}  "
        f"{'':>7} {'':>8} {_format_factor(_geometric_mean([c.compile_factor for c in comparisons])):>7}  "
        f"{'':>7} {'':>8} {_format_factor(_geometric_mean([c.run_factor for c in comparisons])):>7}  "
        f"{'':>7} {'':>8} {_format_factor(_geometric_mean([c.binary_size_factor for c in comparisons])):>7}"
    )
    return "\n".join(lines)


def format_markdown(comparisons: Sequence[Comparison], toolchain: Toolchain, repetitions: int) -> str:
    """The same comparison as a markdown table, for the CI job summary."""
    lines = [
        "## DiscoPoP pass overhead",
        "",
        f"`{toolchain.cxx_version}`, median of {repetitions} repetitions, "
        f"flags `{' '.join(COMMON_COMPILE_FLAGS)}`.",
        "",
        "| program | compile base [s] | compile +pass [s] | compile factor "
        "| run base [s] | run +pass [s] | run factor | size base [KiB] | size +pass [KiB] | size factor |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for comparison in comparisons:
        lines.append(
            f"| {comparison.program.name} "
            f"| {comparison.baseline.compile_median:.3f} | {comparison.instrumented.compile_median:.3f} "
            f"| {_format_factor(comparison.compile_factor)} "
            f"| {comparison.baseline.run_median:.3f} | {comparison.instrumented.run_median:.3f} "
            f"| {_format_factor(comparison.run_factor)} "
            f"| {comparison.baseline.binary_size_bytes / 1024:.0f} "
            f"| {comparison.instrumented.binary_size_bytes / 1024:.0f} "
            f"| {_format_factor(comparison.binary_size_factor)} |"
        )
    lines.append(
        f"| **geometric mean** | | | **{_format_factor(_geometric_mean([c.compile_factor for c in comparisons]))}** "
        f"| | | **{_format_factor(_geometric_mean([c.run_factor for c in comparisons]))}** "
        f"| | | **{_format_factor(_geometric_mean([c.binary_size_factor for c in comparisons]))}** |"
    )
    lines.append("")
    lines.append(
        "Wall clock times depend on the machine they were taken on -- compare them across runs of "
        "the same machine, not against absolute numbers."
    )
    lines.append("")
    return "\n".join(lines)


def build_report(comparisons: Sequence[Comparison], toolchain: Toolchain, repetitions: int) -> Dict[str, object]:
    """The machine readable form of the comparison."""
    return {
        "metadata": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "compiler": str(toolchain.cxx),
            "compiler_version": toolchain.cxx_version,
            "pass_plugin": str(toolchain.plugin),
            "rtlib_dir": str(toolchain.rtlib_dir),
            "common_compile_flags": list(COMMON_COMPILE_FLAGS),
            "repetitions": repetitions,
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "programs": [
            {
                "name": comparison.program.name,
                "description": comparison.program.description,
                "output_preserved": comparison.output_preserved,
                "baseline": {
                    "compile_seconds": comparison.baseline.compile_seconds,
                    "compile_seconds_median": comparison.baseline.compile_median,
                    "run_seconds": comparison.baseline.run_seconds,
                    "run_seconds_median": comparison.baseline.run_median,
                    "binary_size_bytes": comparison.baseline.binary_size_bytes,
                },
                "instrumented": {
                    "compile_seconds": comparison.instrumented.compile_seconds,
                    "compile_seconds_median": comparison.instrumented.compile_median,
                    "run_seconds": comparison.instrumented.run_seconds,
                    "run_seconds_median": comparison.instrumented.run_median,
                    "binary_size_bytes": comparison.instrumented.binary_size_bytes,
                },
                "factors": {
                    "compile": comparison.compile_factor,
                    "run": comparison.run_factor,
                    "binary_size": comparison.binary_size_factor,
                },
            }
            for comparison in comparisons
        ],
        "summary": {
            "geometric_mean_compile_factor": _geometric_mean([c.compile_factor for c in comparisons]),
            "geometric_mean_run_factor": _geometric_mean([c.run_factor for c in comparisons]),
            "geometric_mean_binary_size_factor": _geometric_mean([c.binary_size_factor for c in comparisons]),
        },
    }


# ---------------------------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------------------------


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--programs-dir",
        type=Path,
        default=Path(__file__).parent / "programs",
        help="directory containing the benchmark programs (default: %(default)s)",
    )
    parser.add_argument("--filter", type=str, default=None, help="only run programs whose name contains this")
    parser.add_argument(
        "--repetitions",
        type=int,
        default=3,
        help="measured repetitions per program and configuration, on top of one discarded warm up "
        "(default: %(default)s)",
    )
    parser.add_argument("--cxx", type=Path, default=None, help="clang++ to use (default: auto detected)")
    parser.add_argument(
        "--plugin", type=Path, default=None, help="path to LLVMDiscoPoP.{so,dylib} (default: auto detected)"
    )
    parser.add_argument(
        "--rtlib-dir", type=Path, default=None, help="directory containing libDiscoPoP_RT.a (default: auto detected)"
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="directory for the compiled binaries and profiling output (default: a temporary directory)",
    )
    parser.add_argument("--json-out", type=Path, default=None, help="write the full results to this JSON file")
    parser.add_argument("--markdown-out", type=Path, default=None, help="write a markdown summary to this file")
    parser.add_argument(
        "--max-compile-factor",
        type=float,
        default=None,
        help="fail if the geometric mean of the compile time factors exceeds this value",
    )
    parser.add_argument(
        "--max-run-factor",
        type=float,
        default=None,
        help="fail if the geometric mean of the run time factors exceeds this value",
    )
    return parser.parse_args(argv)


def _check_thresholds(report: Dict[str, object], arguments: argparse.Namespace) -> List[str]:
    summary = report["summary"]
    assert isinstance(summary, dict)
    failures: List[str] = []
    thresholds = [
        ("compile time", "geometric_mean_compile_factor", arguments.max_compile_factor),
        ("run time", "geometric_mean_run_factor", arguments.max_run_factor),
    ]
    for label, key, limit in thresholds:
        if limit is None:
            continue
        measured = float(summary[key])
        if math.isfinite(measured) and measured > limit:
            failures.append(f"{label} overhead x{measured:.2f} exceeds the allowed x{limit:.2f}")
    return failures


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parse_arguments(argv)
    if arguments.repetitions < 1:
        print("--repetitions must be at least 1", file=sys.stderr)
        return 2

    try:
        toolchain = build_toolchain(arguments.cxx, arguments.plugin, arguments.rtlib_dir)
        programs = discover_programs(arguments.programs_dir, arguments.filter)
    except BenchmarkError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2

    print("DiscoPoP pass overhead")
    print(f"compiler:   {toolchain.cxx} ({toolchain.cxx_version})")
    print(f"pass:       {toolchain.plugin}")
    print(f"runtime:    {toolchain.rtlib_dir / 'libDiscoPoP_RT.a'}")
    print(f"flags:      {' '.join(COMMON_COMPILE_FLAGS)}")
    print(f"programs:   {len(programs)}, {arguments.repetitions} measured repetitions each")
    print()

    temporary_dir: Optional[tempfile.TemporaryDirectory[str]] = None
    if arguments.work_dir is not None:
        work_dir = arguments.work_dir
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        temporary_dir = tempfile.TemporaryDirectory(prefix="discopop_pass_benchmark_")
        work_dir = Path(temporary_dir.name)

    try:
        comparisons = run_benchmark(toolchain, programs, work_dir, arguments.repetitions)
    except BenchmarkError as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        return 1
    finally:
        if temporary_dir is not None:
            temporary_dir.cleanup()

    report = build_report(comparisons, toolchain, arguments.repetitions)

    print()
    print(format_table(comparisons))
    print()
    print(
        "Wall clock times depend on the machine they were taken on -- compare them across runs "
        "of the same machine, not against absolute numbers."
    )
    print()

    if arguments.json_out is not None:
        arguments.json_out.parent.mkdir(parents=True, exist_ok=True)
        arguments.json_out.write_text(json.dumps(report, indent=2) + "\n")
        print(f"wrote {arguments.json_out}")
    if arguments.markdown_out is not None:
        arguments.markdown_out.parent.mkdir(parents=True, exist_ok=True)
        arguments.markdown_out.write_text(format_markdown(comparisons, toolchain, arguments.repetitions))
        print(f"wrote {arguments.markdown_out}")

    failures = [
        f"{comparison.program.name}: the instrumented run did not reproduce the baseline output"
        for comparison in comparisons
        if not comparison.output_preserved
    ]
    failures += _check_thresholds(report, arguments)
    if failures:
        print()
        for failure in failures:
            print(f"FAILED: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

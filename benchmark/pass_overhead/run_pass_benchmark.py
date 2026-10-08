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
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# flags shared by both configurations, mirroring the ones CXX_wrapper.sh applies
COMMON_COMPILE_FLAGS: Tuple[str, ...] = ("-g", "-O0", "-fno-discard-value-names", "-fPIC")

# clang versions the profiler supports, newest first (see profiler/CMakeLists.txt)
SUPPORTED_CLANG_VERSIONS: Tuple[int, ...] = (22, 21, 20, 19)

DESCRIPTION_MARKER = re.compile(r"^//\s*BENCHMARK:\s*(?P<description>.+?)\s*$", re.MULTILINE)

# The runtime libraries a program can be linked against. The shipped one runs every callback body;
# the others are the benchmark builds from profiler/rtlib/CMakeLists.txt, which switch the bodies
# off and then switch exactly one back on. Their names carry the CallbackId enumerator from
# callback_scope.hpp, so there is no table to keep in step.
FULL_LIBRARY = "DiscoPoP_RT"
CALLS_ONLY_LIBRARY = "DiscoPoP_RT_EmptyCallbacks"

# the callbacks the breakdown switches on one at a time, ordered the way benchmark/injected_functions
# reports them so that the two benchmarks can be read side by side
BREAKDOWN_CALLBACKS: Tuple[str, ...] = (
    "READ",
    "WRITE",
    "DECL",
    "ALLOCA",
    "NEW",
    "DELETE",
    "CALL",
    "FUNC_ENTRY",
    "FUNC_EXIT",
    "LOOP_ENTRY",
    "LOOP_EXIT",
    "LOOP_INCR",
    "REPORT_BB",
    "REPORT_BB_PAIR",
    "INCR_TAKEN_BRANCH_COUNTER",
)


class BenchmarkError(RuntimeError):
    """Raised when the benchmark cannot be carried out, e.g. because a program fails to build."""


@dataclass(frozen=True)
class Configuration:
    """One way of building a program: without the pass, or with it plus one runtime library."""

    name: str
    library: Optional[str] = None

    @property
    def instrumented(self) -> bool:
        return self.library is not None

    @property
    def directory_name(self) -> str:
        """A name usable as a directory, so that configurations do not share a build directory."""
        return re.sub(r"[^A-Za-z0-9_.-]+", "_", self.name)


BASELINE = Configuration("baseline")
INSTRUMENTED = Configuration("instrumented", FULL_LIBRARY)
CALLS_ONLY = Configuration("calls only", CALLS_ONLY_LIBRARY)


def callback_name(enumerator: str) -> str:
    """The callback a CallbackId enumerator belongs to, e.g. ``READ`` -> ``__dp_read``."""
    return "__dp_" + enumerator.lower()


def breakdown_configurations() -> List[Configuration]:
    """Every configuration the callback breakdown adds, in the order it reports them."""
    return [CALLS_ONLY] + [
        Configuration(f"only {callback_name(enumerator)}", f"DiscoPoP_RT_Only_{enumerator}")
        for enumerator in BREAKDOWN_CALLBACKS
    ]


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
    # the callback breakdown, keyed by configuration name -- empty unless it was asked for
    breakdown: Dict[str, Measurement] = field(default_factory=dict)

    def run_factor_of(self, configuration: Configuration) -> float:
        """The run time factor of one breakdown configuration against the baseline."""
        measurement = self.breakdown.get(configuration.name)
        if measurement is None:
            return math.nan
        return _factor(measurement.run_median, self.baseline.run_median)

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


def find_variants_dir(directory: Path, breakdown: Sequence[Configuration]) -> Path:
    """Check that the directory holds every runtime library the breakdown needs, and return it."""
    required = [FULL_LIBRARY, *(configuration.library for configuration in breakdown)]
    missing = [name for name in required if name is not None and not (directory / f"lib{name}.a").is_file()]
    if missing:
        raise BenchmarkError(
            f"{directory} is missing {len(missing)} of the runtime libraries the callback breakdown "
            f"needs, starting with lib{missing[0]}.a. Build them with\n"
            f"  cmake -S . -B build_tests -DCMAKE_BUILD_TYPE=Release -DDP_BUILD_UNITTESTS=1\n"
            f"  cmake --build build_tests --target DiscoPoP_RT_BenchmarkVariants\n"
            f"or point --variants-dir at the directory that has them."
        )
    return directory.resolve()


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


def compile_command(toolchain: Toolchain, program: Program, configuration: Configuration, binary: Path) -> List[str]:
    """The compile command for one configuration.

    Every configuration uses the same compiler and the same flags. An instrumented one adds the
    pass plugin and a runtime library, exactly as CXX_wrapper.sh does -- which library is what
    distinguishes the configurations from each other.
    """
    command = [str(toolchain.cxx), str(program.source), *COMMON_COMPILE_FLAGS]
    if configuration.library is not None:
        command += [
            "-Xclang",
            "-load",
            "-Xclang",
            str(toolchain.plugin),
            "-Xclang",
            f"-fpass-plugin={toolchain.plugin}",
            "-Xlinker",
            f"-L{toolchain.rtlib_dir}",
            # libDiscoPoP_RT.a is a static archive and nothing in instrumented code references
            # __dp_init -- the runtime starts from the .init_array entry next to it. Without this
            # the linker leaves that object out, the runtime never comes up, and every callback
            # returns at its guard: the benchmark then measures the cost of calling the callbacks
            # rather than the cost of profiling. CXX_wrapper.sh passes the same flag.
            "-Xlinker",
            "-u",
            "-Xlinker",
            "__dp_init",
            "-Xlinker",
            f"-l{configuration.library}",
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
    configuration: Configuration,
    work_dir: Path,
    repetitions: int,
) -> Measurement:
    """Compile and run one program in one configuration, ``repetitions`` times after a warm up."""
    run_dir = work_dir / program.name / configuration.directory_name
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
        duration, _ = _timed_run(command, run_dir, env, f"compiling {program.name} ({configuration.name})")
        if repetition > 0:  # the first iteration is a warm up and is discarded
            measurement.compile_seconds.append(duration)

    for repetition in range(repetitions + 1):
        duration, stdout = _timed_run([str(binary)], run_dir, env, f"running {program.name} ({configuration.name})")
        if repetition > 0:
            measurement.run_seconds.append(duration)
            measurement.stdout = stdout

    if configuration.instrumented:
        # An instrumented binary that never brings the runtime up still calls every callback, so
        # it looks plausible and merely reports a much smaller overhead -- which is what a missing
        # -u __dp_init did until it was noticed by comparing two branches. The dependency file is
        # the cheapest proof that the runtime came up: __dp_init opens it, so it is there even in
        # the configurations whose callbacks record nothing into it.
        dependencies = dot_discopop / "profiler" / "dynamic_dependencies.txt"
        if not dependencies.is_file():
            raise BenchmarkError(
                f"{program.name}: the instrumented run produced no {dependencies.name}, so the "
                f"runtime did not profile anything and the measured overhead is meaningless. "
                f"Check that the runtime library is linked the way the wrappers link it."
            )

    measurement.binary_size_bytes = binary.stat().st_size
    return measurement


def run_benchmark(
    toolchain: Toolchain,
    programs: Sequence[Program],
    work_dir: Path,
    repetitions: int,
    breakdown: Sequence[Configuration] = (),
) -> List[Comparison]:
    comparisons: List[Comparison] = []
    for program in programs:
        print(f"  {program.name} ...", end="", flush=True)
        baseline = measure(toolchain, program, BASELINE, work_dir, repetitions)
        instrumented = measure(toolchain, program, INSTRUMENTED, work_dir, repetitions)
        comparison = Comparison(program=program, baseline=baseline, instrumented=instrumented)
        print(f" compile x{comparison.compile_factor:.2f}, runtime x{comparison.run_factor:.2f}", end="", flush=True)

        for configuration in breakdown:
            comparison.breakdown[configuration.name] = measure(toolchain, program, configuration, work_dir, repetitions)
            print(".", end="", flush=True)

        comparisons.append(comparison)
        print()
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


def _breakdown_rows(
    comparisons: Sequence[Comparison], breakdown: Sequence[Configuration]
) -> List[Tuple[str, List[float], float]]:
    """One row per configuration: its name, its run factor per program, and their geometric mean.

    The shipped runtime is appended as the last row, so that the callbacks can be read against the
    number they add up to.
    """
    rows: List[Tuple[str, List[float], float]] = []
    for configuration in [*breakdown, INSTRUMENTED]:
        if configuration is INSTRUMENTED:
            factors = [comparison.run_factor for comparison in comparisons]
            label = "all bodies (shipped runtime)"
        else:
            factors = [comparison.run_factor_of(configuration) for comparison in comparisons]
            label = configuration.name
        rows.append((label, factors, _geometric_mean(factors)))
    return rows


def format_breakdown_table(comparisons: Sequence[Comparison], breakdown: Sequence[Configuration]) -> str:
    """The run time factor of every configuration, one row each, programs across the columns."""
    rows = _breakdown_rows(comparisons, breakdown)
    label_width = max(len("configuration"), *(len(label) for label, _, _ in rows))
    columns = [comparison.program.name for comparison in comparisons]
    column_widths = [max(9, len(name)) for name in columns]

    header = f"{'configuration':<{label_width}}  " + "  ".join(
        f"{name:>{width}}" for name, width in zip(columns, column_widths)
    )
    header += f"  {'geomean':>9}"
    lines = [header, "-" * len(header)]
    for label, factors, mean in rows:
        cells = "  ".join(f"{_format_factor(factor):>{width}}" for factor, width in zip(factors, column_widths))
        lines.append(f"{label:<{label_width}}  {cells}  {_format_factor(mean):>9}")
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


def format_breakdown_markdown(comparisons: Sequence[Comparison], breakdown: Sequence[Configuration]) -> str:
    """The callback breakdown as a markdown table, for the CI job summary."""
    if not breakdown:
        return ""
    rows = _breakdown_rows(comparisons, breakdown)
    columns = [comparison.program.name for comparison in comparisons]

    lines = [
        "### Where the run time overhead comes from",
        "",
        "Run time against the uninstrumented baseline. `calls only` links the runtime whose callbacks",
        "return as soon as they are entered, so it is what the added calls cost by themselves; each",
        "`only __dp_*` row switches exactly that one body back on, on top of those calls.",
        "",
        "| configuration | " + " | ".join(columns) + " | geomean |",
        "| --- |" + " ---: |" * (len(columns) + 1),
    ]
    for label, factors, mean in rows:
        cells = " | ".join(_format_factor(factor) for factor in factors)
        lines.append(f"| {label} | {cells} | **{_format_factor(mean)}** |")
    lines.append("")
    lines.append(
        "_The rows do not add up to the last one: the callbacks share the runtime's caches and "
        "queues, and a body that runs alone finds them in a state that it would not find them in "
        "with the others running too._"
    )
    lines.append("")
    return "\n".join(lines)


def build_report(
    comparisons: Sequence[Comparison],
    toolchain: Toolchain,
    repetitions: int,
    breakdown: Sequence[Configuration] = (),
) -> Dict[str, object]:
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
                "callback_breakdown": {
                    name: {
                        "run_seconds_median": measurement.run_median,
                        "run_factor": _factor(measurement.run_median, comparison.baseline.run_median),
                        "binary_size_bytes": measurement.binary_size_bytes,
                    }
                    for name, measurement in comparison.breakdown.items()
                },
            }
            for comparison in comparisons
        ],
        "summary": {
            "geometric_mean_compile_factor": _geometric_mean([c.compile_factor for c in comparisons]),
            "geometric_mean_run_factor": _geometric_mean([c.run_factor for c in comparisons]),
            "geometric_mean_binary_size_factor": _geometric_mean([c.binary_size_factor for c in comparisons]),
            "callback_breakdown_geometric_mean_run_factor": {
                label: mean for label, _, mean in _breakdown_rows(comparisons, breakdown)
            },
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
        "--callback-breakdown",
        action="store_true",
        help="additionally build every program against the runtime whose callbacks have no body, and "
        "once per callback with only that body switched on. Needs the benchmark runtime variants: "
        "cmake --build <build-dir> --target DiscoPoP_RT_BenchmarkVariants",
    )
    parser.add_argument(
        "--variants-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "build_tests" / "profiler" / "rtlib",
        help="directory holding the benchmark runtime variants, used for every instrumented "
        "configuration once --callback-breakdown is given, so that all of them come from one build "
        "(default: %(default)s)",
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

    breakdown: List[Configuration] = breakdown_configurations() if arguments.callback_breakdown else []

    try:
        toolchain = build_toolchain(arguments.cxx, arguments.plugin, arguments.rtlib_dir)
        if breakdown:
            # Every instrumented configuration is taken from the variants directory, not only the
            # ones the breakdown adds: comparing a runtime from the installed package against
            # variants from a build directory would put a second difference into every row.
            toolchain = replace(toolchain, rtlib_dir=find_variants_dir(arguments.variants_dir, breakdown))
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
    if breakdown:
        print(f"breakdown:  {len(breakdown)} further configurations per program")
    print()

    temporary_dir: Optional[tempfile.TemporaryDirectory[str]] = None
    if arguments.work_dir is not None:
        work_dir = arguments.work_dir
        work_dir.mkdir(parents=True, exist_ok=True)
    else:
        temporary_dir = tempfile.TemporaryDirectory(prefix="discopop_pass_benchmark_")
        work_dir = Path(temporary_dir.name)

    try:
        comparisons = run_benchmark(toolchain, programs, work_dir, arguments.repetitions, breakdown)
    except BenchmarkError as error:
        print(f"\nERROR: {error}", file=sys.stderr)
        return 1
    finally:
        if temporary_dir is not None:
            temporary_dir.cleanup()

    report = build_report(comparisons, toolchain, arguments.repetitions, breakdown)

    print()
    print(format_table(comparisons))
    print()
    if breakdown:
        print(format_breakdown_table(comparisons, breakdown))
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
        summary = format_markdown(comparisons, toolchain, arguments.repetitions)
        summary += format_breakdown_markdown(comparisons, breakdown)
        arguments.markdown_out.write_text(summary)
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

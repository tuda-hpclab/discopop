# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Does the optimization level of the target program (CXXFLAGS=-O2, ...) influence what DiscoPoP reports?

The profiler instruments unoptimized IR: the compiler wrappers append ``-O0`` to the arguments they are given, so
the level chosen by the user should not change the instrumentation, the profiling output or the detected patterns.
The tests below check exactly that, for the programs in this directory and the levels in ``LEVELS``:

* ``TestProfilerOutput``: every text file the instrumentation and the profiling run write is the same as at ``-O0``
  (after removing what legitimately differs between runs: the work directory, heap addresses, line order)
* ``TestDetectedPatterns``: the pattern detection finds the same patterns as at ``-O0``
* ``TestEffectiveFlags``: which ``-O`` option the compiler jobs of the wrapper really get
* ``TestControlWithoutWrapper``: control experiment; the same program compiled with the pass *without* the wrapper
  (so that ``-O2`` is not overridden) does produce different output; this is why the wrapper has to force ``-O0``
"""

import os
import re
import shlex
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from test.end_to_end.pipeline import PipelineError, build_and_profile, explore

HERE = Path(__file__).parent
LEVELS = ["-O0", "-O1", "-O2", "-O3", "-Os", "-Og"]
PROGRAMS = ["kernels", "optimize_macro"]
BASELINE = "-O0"
# files that differ between two runs of the same binary (timings, locks), not between optimization levels
IGNORED_FILES = {"statistics", "locking_files"}


def _normalize(text: str, work_dir: Path) -> list[str]:
    """Order independent, address independent, location independent lines of a profiler file."""
    text = text.replace(str(work_dir), "<WORK>")
    text = re.sub(r"\((\d{6,})\)", "(<ADDR>)", text)  # heap / stack addresses in variable names
    text = re.sub(r"=\"\d{6,}\"", '="<ADDR>"', text)
    text = re.sub(r"ast_export\.\w{6}", "ast_export.<TMP>", text)
    text = re.sub(r'"id": "0x[0-9a-f]+"', '"id": "<ID>"', text)  # clang node ids are addresses
    text = re.sub(r'"(?:previousDecl|referencedDecl|decl)": \{"id": "0x[0-9a-f]+"', '"decl": {"id": "<ID>"', text)
    return sorted(line.rstrip() for line in text.splitlines() if line.strip())


def _profiler_files(profiler_dir: Path) -> dict[str, list[str]]:
    work_dir = profiler_dir.parent.parent
    files: dict[str, list[str]] = {}
    for path in sorted(profiler_dir.rglob("*")):
        if not path.is_file() or path.name in IGNORED_FILES or IGNORED_FILES & set(path.parts):
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        files[str(path.relative_to(profiler_dir))] = _normalize(text, work_dir)
    return files


class Runs:
    """Builds and profiles each (program, level) once; keeps the temporary directories alive."""

    def __init__(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="discopop_optlevels_")
        self._dot_discopop: dict[tuple[str, str], Path] = {}

    def dot_discopop(self, program: str, level: str) -> Path:
        key = (program, level)
        if key not in self._dot_discopop:
            work_dir = Path(self._tmp.name) / program / level.lstrip("-") / "src"
            self._dot_discopop[key] = build_and_profile(
                HERE / program / "src", work_dir, extra_env={"CXXFLAGS": level, "CFLAGS": level}
            )
        return self._dot_discopop[key]

    def cleanup(self) -> None:
        self._tmp.cleanup()


@pytest.fixture(scope="module")
def runs() -> Iterator[Runs]:
    r = Runs()
    yield r
    r.cleanup()


def _diff(baseline: dict[str, list[str]], other: dict[str, list[str]]) -> list[str]:
    problems = []
    for name in sorted(set(baseline) | set(other)):
        if name not in other:
            problems.append(f"{name}: missing")
        elif name not in baseline:
            problems.append(f"{name}: additional file")
        elif baseline[name] != other[name]:
            only_base = sorted(set(baseline[name]) - set(other[name]))
            only_other = sorted(set(other[name]) - set(baseline[name]))
            problems.append(
                f"{name}: {len(only_base)} lines only at {BASELINE}, {len(only_other)} only at the other level; "
                f"e.g. {only_base[:2]} vs {only_other[:2]}"
            )
    return problems


@pytest.mark.parametrize("program", PROGRAMS)
@pytest.mark.parametrize("level", [lv for lv in LEVELS if lv != BASELINE])
class TestProfilerOutput:
    def test_same_files_as_baseline(self, runs: Runs, program: str, level: str) -> None:
        baseline = _profiler_files(runs.dot_discopop(program, BASELINE) / "profiler")
        other = _profiler_files(runs.dot_discopop(program, level) / "profiler")
        problems = _diff(baseline, other)
        assert not problems, f"{program} at {level} differs from {BASELINE}:\n" + "\n".join(problems)

    def test_file_mapping(self, runs: Runs, program: str, level: str) -> None:
        def mapping(lv: str) -> list[str]:
            d = runs.dot_discopop(program, lv)
            return _normalize((d / "FileMapping.txt").read_text(), d.parent)

        assert mapping(level) == mapping(BASELINE)


def _pattern_summary(dot_discopop: Path) -> dict[str, list[tuple[int, int]]]:
    result = explore(dot_discopop, "doall,reduction")
    summary: dict[str, list[tuple[int, int]]] = {}
    for kind in ("do_all", "reduction"):
        summary[kind] = sorted(
            (int(p.start_line.split(":")[1]), int(p.end_line.split(":")[1])) for p in getattr(result.patterns, kind)
        )
    return summary


@pytest.mark.parametrize("program", PROGRAMS)
class TestDetectedPatterns:
    def test_same_patterns_at_all_levels(self, runs: Runs, program: str) -> None:
        baseline = _pattern_summary(runs.dot_discopop(program, BASELINE))
        assert baseline["do_all"] or baseline["reduction"], "the baseline detects nothing, the test checks nothing"
        for level in LEVELS:
            if level == BASELINE:
                continue
            assert _pattern_summary(runs.dot_discopop(program, level)) == baseline, f"{program} at {level}"


def _cc1_jobs(level: str, tmp_path: Path) -> list[str]:
    """The cc1 command lines the wrapper's compiler jobs run (-###) for a compilation at the given level."""
    src = tmp_path / "t.cpp"
    src.write_text("int main() { return 0; }\n")
    (tmp_path / ".discopop").mkdir(exist_ok=True)
    env = dict(
        os.environ, DOT_DISCOPOP=str(tmp_path / ".discopop"), DP_PROJECT_ROOT_DIR=str(tmp_path), HOME=str(tmp_path)
    )
    result = subprocess.run(
        ["discopop_cxx", level, "-c", str(src), "-o", str(tmp_path / "t.o"), "-###"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stderr.splitlines() if '"-cc1"' in line]


def _opt_options(cc1_line: str) -> list[str]:
    return [t for t in shlex.split(cc1_line) if re.fullmatch(r"-O[0-9sgz]?", t)]


@pytest.mark.parametrize("level", [lv for lv in LEVELS if lv != BASELINE])
class TestEffectiveFlags:
    def test_object_file_is_compiled_at_O0(self, level: str, tmp_path: Path) -> None:
        """The job that emits the instrumented object file must not see the user's optimization level."""
        emit_jobs = [j for j in _cc1_jobs(level, tmp_path) if "-emit-obj" in j]
        assert emit_jobs, "no job emitting an object file found"
        for job in emit_jobs:
            assert _opt_options(job) == ["-O0"], _opt_options(job)

    def test_all_jobs_agree_on_the_level(self, level: str, tmp_path: Path) -> None:
        """The AST export (-fsyntax-only) of the same compilation must be done at the same level as the IR:
        otherwise the AST and the instrumented code can see different code (``__OPTIMIZE__``)."""
        levels = {tuple(_opt_options(j)) for j in _cc1_jobs(level, tmp_path)}
        assert len(levels) == 1, f"the compiler jobs of one compilation use different levels: {levels}"


def _control_run(level: str, work_dir: Path) -> Path:
    """Compile and run the kernels with the pass loaded directly into clang, i.e. without the wrapper's ``-O0``."""
    import shutil

    shutil.copytree(HERE / "kernels" / "src", work_dir)
    candidates = [
        p
        for p in Path(sys.prefix).rglob("discopop-profiler.libs/LLVMDiscoPoP.so")
        if (p.parent / "libDiscoPoP_RT.a").exists()
    ]
    if not candidates:
        pytest.skip("the installed profiler was not found")
    lib_dir = candidates[0].parent
    clang = next((c for c in ("clang++-22", "clang++-21", "clang++-20", "clang++-19") if shutil.which(c)), None)
    if clang is None:
        pytest.skip("no clang++ found")
    dot = work_dir / ".discopop"
    (dot / "profiler").mkdir(parents=True)
    (dot / "FileMapping.txt").write_text(f"1\t{work_dir / 'code.cpp'}\n")
    env = dict(os.environ, DOT_DISCOPOP=str(dot), DP_PROJECT_ROOT_DIR=str(work_dir), HOME=str(work_dir))
    plugin = lib_dir / "LLVMDiscoPoP.so"
    cmd = (
        f"{clang} code.cpp -o prog -g {level} -fno-discard-value-names -Xclang -load -Xclang {plugin} "
        f"-Xclang -fpass-plugin={plugin} -fPIC -Xlinker -L{lib_dir} -Xlinker -u -Xlinker __dp_init "
        "-Xlinker -lDiscoPoP_RT -Xlinker -lpthread"
    )
    for stage in (cmd, "./prog"):
        r = subprocess.run(stage, shell=True, cwd=work_dir, env=env, capture_output=True, text=True)
        if r.returncode != 0:
            raise PipelineError(f"{stage} failed:\n{r.stdout}\n{r.stderr}")
    return dot / "profiler"


class TestControlWithoutWrapper:
    """Shows the effect the wrapper's ``-O0`` hides: with the pass at -O2, the profiler output changes."""

    def test_optimization_changes_the_output_if_not_overridden(self, tmp_path: Path) -> None:
        o0 = _profiler_files(_control_run("-O0", tmp_path / "o0"))
        o2 = _profiler_files(_control_run("-O2", tmp_path / "o2"))
        assert _diff(o0, o2), "-O2 reaches the pass but the output is unchanged: the control no longer shows anything"

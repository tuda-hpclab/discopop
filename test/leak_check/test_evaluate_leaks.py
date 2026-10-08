# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Unit tests of evaluate_leaks.py, the evaluation of the profiler leak check (scripts/dev/check_profiler_leaks.sh)."""

import sys
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent))

import evaluate_leaks  # noqa: E402
from evaluate_leaks import Checker, KnownLeak  # noqa: E402

# (kind, bytes, objects, frames without the allocator, innermost first)
Leak = Tuple[str, int, int, Sequence[str]]

CANARY: Leak = ("Direct", evaluate_leaks.CANARY_BYTES, 1, ["dp_leak_check_canary", "report_leaks", "main"])
SELF_PATH: Leak = ("Direct", 4096, 1, ["__dp_func_entry", "main"])


def lsan_report(leaks: Sequence[Leak], summary: Optional[Tuple[int, int]] = None, prefix: str = "") -> str:
    lines = ["=================================================================", "==1==ERROR: LeakSanitizer: detected"]
    for kind, size, objects, frames in leaks:
        lines.append("")
        lines.append(f"{prefix}{kind} leak of {size} byte(s) in {objects} object(s) allocated from:")
        lines.append("    #0 0x55555555 in operator new(unsigned long) (/tmp/program+0x11e601) (BuildId: 5f21)")
        for number, frame in enumerate(frames, start=1):
            lines.append(f"    #{number} 0x5555{number:04x} in {frame} /src/profiler/rtlib/file.cpp:{number}:7")
    if summary is None:
        summary = (sum(leak[1] for leak in leaks), sum(leak[2] for leak in leaks))
    lines.append("")
    lines.append(f"SUMMARY: AddressSanitizer: {summary[0]} byte(s) leaked in {summary[1]} allocation(s).")
    return "\n".join(lines)


def program_log(
    before: Sequence[Leak],
    after: Sequence[Leak],
    heap_mb: Tuple[float, float] = (40.0, 36.0),
    before_report: Optional[str] = None,
) -> str:
    parts = [f"DP_LEAK_CHECK_LIVE_HEAP before_finalize {int(heap_mb[0] * 2**20)}"]
    parts += ["DP_LEAK_CHECK_BEGIN before_finalize"]
    parts += [before_report if before_report is not None else lsan_report([CANARY, *before])]
    parts += ["DP_LEAK_CHECK_END before_finalize"]
    parts += [f"DP_LEAK_CHECK_LIVE_HEAP after_finalize {int(heap_mb[1] * 2**20)}"]
    parts += [
        "DP_LEAK_CHECK_BEGIN after_finalize",
        lsan_report([CANARY, CANARY, *after]),
        "DP_LEAK_CHECK_END after_finalize",
    ]
    return "\n".join(parts) + "\n"


KNOWN = [
    KnownLeak("before_finalize", "Direct", 1, 4096, ("__dp_func_entry", "main"), 1),
    KnownLeak("after_finalize", "Direct", 1, 4096, ("__dp_func_entry", "main"), 2),
    KnownLeak("after_finalize", "Indirect", 1, 1 << 20, ("__dp::addDep",), 3),
    KnownLeak("after_finalize", "Indirect", 2, 1 << 24, ("__dp::PerfectShadow2::*",), 4),
]


def headlines(checker: Checker) -> List[str]:
    return [problem.headline for problem in checker.problems]


def test_clean_log_passes() -> None:
    checker = Checker(KNOWN)
    checker.check_log("run.log", program_log([SELF_PATH], [SELF_PATH]), verbose=False)
    assert checker.problems == []
    assert checker.used == {1, 2}


def test_unknown_runtime_leak_fails() -> None:
    leak: Leak = ("Direct", 64, 4, ["__dp_loop_incr", "main"])
    checker = Checker(KNOWN)
    checker.check_log("run.log", program_log([SELF_PATH, leak], [SELF_PATH, leak]), verbose=False)
    assert len(checker.problems) == 2  # once per section
    assert "__dp_loop_incr" in checker.problems[0].headline


def test_leak_of_the_target_program_is_ignored() -> None:
    leak: Leak = ("Direct", 64, 4, ["compute(int)", "main"])
    checker = Checker(KNOWN)
    checker.check_log("run.log", program_log([SELF_PATH, leak], [SELF_PATH, leak]), verbose=False)
    assert checker.problems == []


def test_teardown_leak_is_checked() -> None:
    lost_sets: Leak = ("Indirect", 4000, 40, ["__dp::addDep(long)", "__dp::processFirstAccessQueue(void*)"])
    checker = Checker(KNOWN)
    checker.check_log("run.log", program_log([SELF_PATH], [SELF_PATH, lost_sets]), verbose=False)
    assert any("line 3 exceeds its limit" in h and "after_finalize" in h for h in headlines(checker))


def test_known_leak_limit() -> None:
    twice: Leak = ("Direct", 8192, 2, ["__dp_func_entry", "main"])
    checker = Checker(KNOWN)
    checker.check_log("run.log", program_log([twice], [twice]), verbose=False)
    assert any("line 1 exceeds its limit" in h for h in headlines(checker))


@pytest.mark.parametrize(
    "entry, frame, matches",
    [
        ("__dp::foo", "__dp::foo(int, long)", True),
        ("__dp::foo", "__dp::foobar(int)", False),
        ("__dp::foo(int,long)", "__dp::foo(int, long)", True),
        ("__dp::PerfectShadow2::*", "__dp::PerfectShadow2::insertToWrite(long, long)", True),
        ("__dp::PerfectShadow2::*", "__dp::PerfectShadow2Other::get()", False),
        ("__dp_func_entry", "__dp_func_entry", True),
    ],
)
def test_frame_matching(entry: str, frame: str, matches: bool) -> None:
    assert evaluate_leaks._frame_matches(entry, frame) == matches


def test_missing_canary_fails() -> None:
    checker = Checker(KNOWN)
    report = lsan_report([SELF_PATH])  # no canary: LSan did not run or the report was not understood
    checker.check_log("run.log", program_log([], [SELF_PATH], before_report=report), verbose=False)
    assert any("canary" in h for h in headlines(checker))


def test_ansi_colour_codes_are_removed() -> None:
    report = lsan_report([CANARY, ("Direct", 64, 4, ["__dp_loop_incr", "main"])], prefix="\x1b[1m\x1b[34m")
    checker = Checker(KNOWN)
    checker.check_log("run.log", program_log([], [SELF_PATH], before_report=report), verbose=False)
    assert any("__dp_loop_incr" in h for h in headlines(checker))


def test_report_not_matching_the_summary_fails() -> None:
    # a leak line the parser does not understand: its bytes are missing from the parsed total
    report = lsan_report([CANARY], summary=(evaluate_leaks.CANARY_BYTES + 64, 5))
    report = report.replace("SUMMARY", "Direct leak (new format) of 64 byte(s)\nSUMMARY")
    checker = Checker(KNOWN)
    checker.check_log("run.log", program_log([], [SELF_PATH], before_report=report), verbose=False)
    assert any("do not match LSan's summary" in h for h in headlines(checker))


def test_missing_section_fails() -> None:
    checker = Checker(KNOWN)
    checker.check_log("run.log", "AddressSanitizer: SEGV\n", verbose=False)
    assert len(checker.problems) == 2


def grow(short_after: Sequence[Leak], long_after: Sequence[Leak], heap: Tuple[float, float] = (40.0, 40.0)) -> Checker:
    checker = Checker(KNOWN)
    short_log = program_log([SELF_PATH], [SELF_PATH, *short_after], heap_mb=(heap[0], heap[0]))
    long_log = program_log([SELF_PATH], [SELF_PATH, *long_after], heap_mb=(heap[1], heap[1]))
    short = checker.check_log("short.log", short_log, verbose=False)
    long = checker.check_log("long.log", long_log, verbose=False)
    checker.check_growth("short.log", short, "long.log", long)
    checker.check_heap_growth("short.log", short_log, "long.log", long_log, limit_mb=32)
    return checker


def test_growth_of_a_known_leak_fails() -> None:
    small: Leak = ("Indirect", 100000, 1, ["__dp::PerfectShadow2::insertToWrite(long, long)"])
    large: Leak = ("Indirect", 200000, 2, ["__dp::PerfectShadow2::updateInRead(long, long)"])
    checker = grow([small], [large])
    assert any(h.startswith("leak grows with the run time") for h in headlines(checker))


def test_growth_is_compared_per_known_entry_not_per_stack() -> None:
    first: Leak = ("Indirect", 100000, 1, ["__dp::PerfectShadow2::insertToWrite(long, long)"])
    second: Leak = ("Indirect", 100000, 1, ["__dp::PerfectShadow2::updateInRead(long, long)"])
    assert grow([first], [second]).problems == []


def test_byte_growth_within_the_slack_passes() -> None:
    small: Leak = ("Indirect", 232, 1, ["__dp::addDep(long)", "__dp::processSecondAccessQueue(void*)"])
    large: Leak = ("Indirect", 2056, 1, ["__dp::addDep(long)", "__dp::analyzeSingleAccess(long)"])
    assert grow([small], [large]).problems == []
    # a known leak that only the long run has is bounded by its entry's limit
    assert grow([], [large]).problems == []


def test_reachable_heap_growth_fails() -> None:
    assert grow([], [], heap=(40.0, 60.0)).problems == []
    checker = grow([], [], heap=(40.0, 120.0))
    assert len(checker.problems) == 2  # before and after finalize
    assert all(h.startswith("reachable memory grows") for h in headlines(checker))


def test_known_leaks_file_of_the_repository_parses() -> None:
    known = evaluate_leaks.load_known_leaks(str(Path(__file__).parent / "known_leaks.txt"))
    # every listed leak is a real one; the file may well list none
    assert {entry.section for entry in known} <= set(evaluate_leaks.SECTIONS)

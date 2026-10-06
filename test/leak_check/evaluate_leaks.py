# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Evaluate the LeakSanitizer reports of instrumented programs for the profiler leak check.

Usage:
    evaluate_leaks.py --known-leaks FILE [--grow SHORT_LOG LONG_LOG]... [LOG]...

Each LOG is the output of an instrumented program linked with lsan_finalize_hook.cpp, which reports two
sections between the markers ``DP_LEAK_CHECK_BEGIN <section>`` and ``DP_LEAK_CHECK_END <section>``:
``before_finalize`` (memory lost while the target ran) and ``after_finalize`` (additionally what the runtime
library's teardown in __dp_finalize loses). Both sections are evaluated, each against its own known leaks.

A leak counts if its allocation stack contains a function of the runtime library (``__dp_*`` or ``__dp::*``);
leaks of the target program itself are listed, but ignored. The check fails if

- a leak of the runtime library is not covered by an entry of the known leaks file for its section, or the
  leaks covered by an entry exceed its object or byte limit in a run,
- for a ``--grow SHORT_LOG LONG_LOG`` pair (the same program with a short and a long run), a leak of the
  runtime library leaks more objects, or more than 1 MB more, in the long run than in the short one
  (compared per section and known leaks entry, or per kind and innermost runtime library function, so the
  callers do not matter). Such a leak grows with the run time, so it fails the check even if it is covered by
  a known leaks entry (unless the short run does not have it at all; the entry's limit bounds it then),
- for a ``--grow`` pair, the live heap the hook reports (``DP_LEAK_CHECK_LIVE_HEAP``) grows by more than
  ``--heap-growth-limit-mb`` from the short to the long run in one of the sections. This catches memory that
  stays reachable but grows with the run time, which LSan cannot see,
- a report cannot be trusted: a section or the hook's canary leak is missing, or the parsed leaks do not add
  up to LSan's SUMMARY line (e.g. because the report format changed).

Direct and indirect leaks are both evaluated: blocks that only point at each other (e.g. a lost
unordered_set and its bucket array) are reported as indirect leaks only.

Known leaks file format, one entry per line (``#`` starts a comment):

    <before|after> <Direct|Indirect> <max objects per run> <max bytes per run> <frame> [<- <frame>]...

The frames of an entry are compared with the runtime library frames of a leak's allocation stack (plus
``main``), innermost first, so library internals like std::allocator frames do not matter. A frame of an
entry matches a function of the stack if it equals its full name or its name without the parameter list
(whitespace ignored), so ``__dp::foo`` matches ``__dp::foo(int, long)`` but not ``__dp::foobar``. An entry
covers a leak if its frames match the first frames of the leak. The leaks covered by one entry are summed up
per run and section.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

SECTIONS = ("before_finalize", "after_finalize")
PHASES = {"before": "before_finalize", "after": "after_finalize"}
CANARY_FUNCTION = "dp_leak_check_canary"
CANARY_BYTES = 7919
# number of LSan reports printed per failing leak site, and number of problems printed with their reports
MAX_REPORTS_SHOWN = 2
MAX_PROBLEMS_DETAILED = 20
DEFAULT_HEAP_GROWTH_LIMIT_MB = 32.0
DEFAULT_LEAK_BYTES_GROWTH_SLACK = 1 << 20
KNOWN_ENTRY_KEY = "known leaks entry of line "

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_LEAK_HEADER = re.compile(r"^(Direct|Indirect) leak of (\d+) byte\(s\) in (\d+) object\(s\) allocated from:")
_FRAME = re.compile(r"^\s*#(\d+) 0x[0-9a-fA-F]+ in (.+)$")
_SUMMARY = re.compile(r"SUMMARY: \w+Sanitizer: (\d+) byte\(s\) leaked in (\d+) allocation\(s\)")
_LIVE_HEAP = re.compile(r"^DP_LEAK_CHECK_LIVE_HEAP (\S+) (\d+)\s*$", re.MULTILINE)
# frames that end the interesting part of an allocation stack
_STACK_ROOTS = ("main", "__libc_start_main", "_start", "asan_thread_start", "start_thread", "clone")


def _normalize(name: str) -> str:
    return "".join(name.split())


def _base_name(name: str) -> str:
    """The function name without its parameter list: ``__dp::foo(int)`` -> ``__dp::foo``."""
    return name if name.startswith("(") else name.split("(", 1)[0]


def _frame_matches(entry_frame: str, frame: str) -> bool:
    entry = _normalize(entry_frame)
    if entry.endswith("::*"):
        # all members of a class or namespace
        return _normalize(_base_name(frame)).startswith(entry[:-1])
    return entry == _normalize(frame) or entry == _normalize(_base_name(frame))


def _is_runtime_library_frame(name: str) -> bool:
    return name.startswith("__dp_") or name.startswith("__dp::")


def _function_name(frame_text: str) -> str:
    """Strip the location from a symbolized frame: ``foo(int) /path/file.cpp:12:3`` -> ``foo(int)``."""
    name = re.sub(r"\s+\(BuildId: [^)]*\)$", "", frame_text.strip())
    # location as module and offset, e.g. "(/usr/lib/libfoo.so+0x1234)"
    name = re.sub(r"\s+\([^()\s]*\+0x[0-9a-fA-F]+\)$", "", name)
    # location as path, optionally with line and column, e.g. "/path/file.cpp:12:3",
    # "csu/../csu/libc-start.c:360:3", "/path/file.cpp" or "asan_interceptors.cpp.o"
    name = re.sub(r"\s+(?:\S*/\S*|[\w.+-]+\.(?:o|a|so[\d.]*|c|cc|cpp|cxx|h|hpp|inc))(?::\d+)*$", "", name)
    return name.strip() or frame_text.strip()


@dataclass
class LeakSite:
    kind: str
    frames: Tuple[str, ...]
    objects: int = 0
    bytes: int = 0
    reports: List[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.kind + " " + " <- ".join(self.frames)

    def runtime_frames(self) -> Tuple[str, ...]:
        """The runtime library frames of the stack, plus main, innermost first."""
        return tuple(f for f in self.frames if _is_runtime_library_frame(f) or _base_name(f) == "main")

    def growth_key(self) -> str:
        """Kind and innermost runtime library function: the same allocation reached through different
        callers (which can depend on timing) counts as one site."""
        innermost = next((f for f in self.frames if _is_runtime_library_frame(f)), "")
        return f"{self.kind} {_normalize(_base_name(innermost))}"

    def is_runtime_library(self) -> bool:
        return any(_is_runtime_library_frame(f) for f in self.frames)

    def is_canary(self) -> bool:
        return self.kind == "Direct" and any(_base_name(f) == CANARY_FUNCTION for f in self.frames)

    def unsymbolized(self) -> bool:
        """True if no frame has a function name, i.e. the symbolizer is missing (single frames of
        libraries without symbols are fine)."""
        return all(re.fullmatch(r"\(?[^ ]*\+0x[0-9a-fA-F]+\)?", f) for f in self.frames)

    def location(self) -> str:
        """The allocation stack from the innermost runtime library frame to its caller (all frames for
        leaks of the target program)."""
        frames = list(self.frames)
        first = next((i for i, f in enumerate(frames) if _is_runtime_library_frame(f)), None)
        if first is not None:
            last = next((i for i in range(first, len(frames)) if not _is_runtime_library_frame(frames[i])), None)
            frames = frames[first : len(frames) if last is None else last + 1]
        return " <- ".join(frames)

    def describe(self) -> str:
        return f"{self.kind} leak, {self.objects} object(s), {self.bytes} byte(s), at {self.location()}"

    def shown_reports(self) -> str:
        shown = "\n\n".join(self.reports[:MAX_REPORTS_SHOWN])
        if len(self.reports) > MAX_REPORTS_SHOWN:
            shown += f"\n... and {len(self.reports) - MAX_REPORTS_SHOWN} more report(s) of this leak site"
        return shown


@dataclass
class Section:
    """The parsed LSan report of one section of a log."""

    sites: Dict[str, LeakSite]
    summary: Optional[Tuple[int, int]]  # bytes, allocations of LSan's SUMMARY line, None if no leaks
    unparsed_headers: int  # lines mentioning a leak that the parser did not understand


@dataclass
class KnownLeak:
    section: str
    kind: str
    max_objects: int
    max_bytes: int
    frames: Tuple[str, ...]
    line: int

    def covers(self, site: LeakSite) -> bool:
        site_frames = site.runtime_frames()
        if site.kind != self.kind or len(site_frames) < len(self.frames):
            return False
        return all(_frame_matches(k, s) for k, s in zip(self.frames, site_frames))

    def describe(self) -> str:
        return f"{self.section} {self.kind} at {' <- '.join(self.frames)}"


@dataclass
class Problem:
    headline: str
    details: str


def section_text(text: str, section: str) -> Optional[str]:
    begin = text.find(f"DP_LEAK_CHECK_BEGIN {section}")
    end = text.find(f"DP_LEAK_CHECK_END {section}", begin + 1)
    if begin < 0 or end < 0:
        return None
    return text[begin:end]


def parse_section(text: str) -> Section:
    """Parse the LSan report of one section (text between its markers, ANSI escapes removed)."""
    sites: Dict[str, LeakSite] = {}
    lines = text.splitlines()
    unparsed = 0
    index = 0
    while index < len(lines):
        header = _LEAK_HEADER.match(lines[index])
        index += 1
        if header is None:
            if re.search(r"\b(Direct|Indirect) leak of\b", lines[index - 1]):
                unparsed += 1
            continue
        block = [lines[index - 1]]
        frames: List[str] = []
        reached_root = False
        while index < len(lines):
            frame = _FRAME.match(lines[index])
            if frame is None:
                break
            block.append(lines[index])
            index += 1
            if int(frame.group(1)) == 0 or reached_root:
                continue  # the allocator (operator new, malloc, ...) or below main / the thread start
            name = _function_name(frame.group(2))
            frames.append(name)
            reached_root = _base_name(name) in _STACK_ROOTS
        site = LeakSite(header.group(1), tuple(frames))
        site = sites.setdefault(site.key, site)
        site.objects += int(header.group(3))
        site.bytes += int(header.group(2))
        site.reports.append("\n".join(block))
    summary_match = _SUMMARY.search(text)
    summary = (int(summary_match.group(1)), int(summary_match.group(2))) if summary_match else None
    return Section(sites, summary, unparsed)


def load_known_leaks(path: str) -> List[KnownLeak]:
    known: List[KnownLeak] = []
    with open(path) as f:
        for number, raw in enumerate(f, start=1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split(None, 4)
            if len(parts) != 5 or parts[0] not in PHASES or parts[1] not in ("Direct", "Indirect"):
                raise ValueError(
                    f"{path}:{number}: expected '<before|after> <Direct|Indirect> <objects> <bytes> <frames>'"
                )
            frames = tuple(f.strip() for f in parts[4].split("<-"))
            known.append(KnownLeak(PHASES[parts[0]], parts[1], int(parts[2]), int(parts[3]), frames, number))
    return known


def read_live_heap(text: str) -> Dict[str, int]:
    return {match.group(1): int(match.group(2)) for match in _LIVE_HEAP.finditer(text)}


@dataclass
class Checker:
    known: Sequence[KnownLeak]
    bytes_growth_slack: int = DEFAULT_LEAK_BYTES_GROWTH_SLACK
    problems: List[Problem] = field(default_factory=list)
    used: Set[int] = field(default_factory=set)

    def check_log(self, log: str, text: str, verbose: bool) -> Dict[str, Dict[str, LeakSite]]:
        """Check one run against the known leaks; return its runtime library leak sites per section, by
        growth key."""
        text = _ANSI_ESCAPE.sub("", text)
        result: Dict[str, Dict[str, LeakSite]] = {}
        notes: List[str] = []
        for section_name in SECTIONS:
            raw = section_text(text, section_name)
            if raw is None:
                self.problems.append(
                    Problem(
                        f"{log}: no {section_name} report (did the program crash?)",
                        "end of the log:\n" + text[-3000:],
                    )
                )
                continue
            result[section_name] = self._check_section(log, section_name, parse_section(raw), raw, notes)
        if verbose:
            print(f"{log}:")
            for note in notes:
                print(f"  {note}")
        return result

    def _check_section(
        self, log: str, section_name: str, section: Section, raw: str, notes: List[str]
    ) -> Dict[str, LeakSite]:
        where = f"{log} [{section_name}]"
        self._check_report_integrity(where, section, raw)
        runtime_sites: Dict[str, LeakSite] = {}
        covered: Dict[int, List[LeakSite]] = {}
        entries = [k for k in self.known if k.section == section_name]
        for site in section.sites.values():
            if site.is_canary():
                continue
            if site.unsymbolized():
                self.problems.append(
                    Problem(f"{where}: unsymbolized allocation stack (is llvm-symbolizer installed?)", site.reports[0])
                )
                continue
            if not site.is_runtime_library():
                notes.append(f"{section_name}: ignored (leak of the target program): {site.describe()}")
                continue
            entry = next((k for k in entries if k.covers(site)), None)
            # growth is compared per known leaks entry, otherwise per innermost runtime library function, so
            # an allocation that is reached through different callers depending on timing counts once
            growth_key = f"{KNOWN_ENTRY_KEY}{entry.line}" if entry else site.growth_key()
            growth = runtime_sites.setdefault(growth_key, LeakSite(site.kind, site.runtime_frames()[:1]))
            growth.objects += site.objects
            growth.bytes += site.bytes
            growth.reports.extend(site.reports)
            if entry is None:
                self.problems.append(Problem(f"{where}: {site.describe()}", site.shown_reports()))
                continue
            covered.setdefault(entry.line, []).append(site)
            self.used.add(entry.line)
            notes.append(f"{section_name}: known leak (known leaks file, line {entry.line}): {site.describe()}")
        for entry in entries:
            matched = covered.get(entry.line, [])
            objects = sum(s.objects for s in matched)
            size = sum(s.bytes for s in matched)
            if objects > entry.max_objects or size > entry.max_bytes:
                self.problems.append(
                    Problem(
                        f"{where}: the known leak of line {entry.line} exceeds its limit: {objects} object(s) / "
                        f"{size} byte(s), at most {entry.max_objects} / {entry.max_bytes} allowed",
                        "\n\n".join(s.shown_reports() for s in matched),
                    )
                )
        return runtime_sites

    def _check_report_integrity(self, where: str, section: Section, raw: str) -> None:
        """The report must contain the hook's canary, and the parsed leaks must add up to LSan's summary."""
        if not any(site.is_canary() and site.bytes >= CANARY_BYTES for site in section.sites.values()):
            self.problems.append(
                Problem(
                    f"{where}: the canary leak of the hook ({CANARY_BYTES} bytes in {CANARY_FUNCTION}) was not "
                    "found; the LSan report was not understood or LSan did not run",
                    raw[-3000:],
                )
            )
        parsed_bytes = sum(s.bytes for s in section.sites.values())
        parsed_objects = sum(s.objects for s in section.sites.values())
        if section.unparsed_headers or (
            section.summary is not None and section.summary != (parsed_bytes, parsed_objects)
        ):
            self.problems.append(
                Problem(
                    f"{where}: the parsed leaks ({parsed_bytes} byte(s) in {parsed_objects} allocation(s), "
                    f"{section.unparsed_headers} unparsed leak line(s)) do not match LSan's summary {section.summary}",
                    raw[-3000:],
                )
            )

    def check_growth(
        self,
        short_log: str,
        short: Dict[str, Dict[str, LeakSite]],
        long_log: str,
        long: Dict[str, Dict[str, LeakSite]],
    ) -> None:
        for section_name in SECTIONS:
            before_sites = short.get(section_name, {})
            for key, site in long.get(section_name, {}).items():
                before = before_sites.get(key)
                objects_before = before.objects if before else 0
                bytes_before = before.bytes if before else 0
                # A known leak may only occur in the longer run (e.g. a lost bucket array that is only allocated
                # once the first dependency is recorded); the entry's limit bounds it. Otherwise: more objects:
                # something is lost per event; more bytes in as many objects: a lost container grew, which is
                # only a problem beyond the slack (e.g. a hash table's bucket array grows with the number of
                # distinct dependencies, not with the run time).
                if key.startswith(KNOWN_ENTRY_KEY) and objects_before == 0:
                    continue
                if site.objects > objects_before or site.bytes > bytes_before + self.bytes_growth_slack:
                    self.problems.append(
                        Problem(
                            f"leak grows with the run time [{section_name}]: {site.kind} leak at {key}: "
                            f"{objects_before} object(s) / {bytes_before} byte(s) in the short run, "
                            f"{site.objects} object(s) / {site.bytes} byte(s) in the long run",
                            f"{long_log}:\n{site.shown_reports()}",
                        )
                    )

    def check_heap_growth(
        self, short_log: str, short_text: str, long_log: str, long_text: str, limit_mb: float
    ) -> List[str]:
        """Compare the live heap of the short and the long run; return one line per section for the log."""
        short_heap = read_live_heap(_ANSI_ESCAPE.sub("", short_text))
        long_heap = read_live_heap(_ANSI_ESCAPE.sub("", long_text))
        lines = []
        for section_name in SECTIONS:
            if section_name not in short_heap or section_name not in long_heap:
                self.problems.append(
                    Problem(
                        f"{long_log}: live heap of {section_name} missing in the short or the long run",
                        "the hook prints DP_LEAK_CHECK_LIVE_HEAP lines; was the program linked with it?",
                    )
                )
                continue
            short_mb = short_heap[section_name] / 2**20
            long_mb = long_heap[section_name] / 2**20
            lines.append(
                f"live heap {section_name}: {short_mb:.1f} MB (short run), {long_mb:.1f} MB (long run), "
                f"limit +{limit_mb:.0f} MB"
            )
            if long_mb - short_mb > limit_mb:
                self.problems.append(
                    Problem(
                        f"reachable memory grows with the run time [{section_name}]: live heap {short_mb:.1f} MB "
                        f"in the short run, {long_mb:.1f} MB in the long run (more than +{limit_mb:.0f} MB)",
                        f"{short_log}\n{long_log}\nThe memory is still referenced, so LSan does not report it. "
                        "Find the growing structure, e.g. with __sanitizer_print_memory_profile() in the hook.",
                    )
                )
        return lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--known-leaks", required=True, help="file listing the known, bounded leaks")
    parser.add_argument("--grow", nargs=2, action="append", default=[], metavar=("SHORT_LOG", "LONG_LOG"))
    parser.add_argument(
        "--heap-growth-limit-mb",
        type=float,
        default=DEFAULT_HEAP_GROWTH_LIMIT_MB,
        help="allowed growth of the live heap from the short to the long run of a --grow pair",
    )
    parser.add_argument("--verbose", action="store_true", help="list the leaks of every log, not only of --grow")
    parser.add_argument("logs", nargs="*", help="logs of single runs (checked against the known leaks only)")
    args = parser.parse_args(argv)

    checker = Checker(load_known_leaks(args.known_leaks))

    def read(path: str) -> str:
        with open(path, errors="replace") as f:
            return f.read()

    for short_log, long_log in args.grow:
        short_text, long_text = read(short_log), read(long_log)
        short = checker.check_log(short_log, short_text, verbose=True)
        long = checker.check_log(long_log, long_text, verbose=True)
        checker.check_growth(short_log, short, long_log, long)
        for line in checker.check_heap_growth(short_log, short_text, long_log, long_text, args.heap_growth_limit_mb):
            print(f"  {line}")
    for log in args.logs:
        checker.check_log(log, read(log), verbose=args.verbose)
    if args.logs:
        print(f"{len(args.logs)} further program run(s) checked against the known leaks")
    for entry in checker.known:
        if entry.line not in checker.used:
            print(
                f"note: the known leak of line {entry.line} ({entry.describe()}) did not occur in any run; "
                "remove the entry if the leak is fixed"
            )

    problems = checker.problems
    if not problems:
        print("profiler leak check: no new or growing leaks of the runtime library")
        return 0

    rule = "=" * 100
    print(f"\n{rule}\nPROFILER LEAK CHECK FAILED, {len(problems)} problem(s):")
    for number, problem in enumerate(problems, start=1):
        print(f"  [{number}] {problem.headline}")
    print(rule)
    for number, problem in enumerate(problems[:MAX_PROBLEMS_DETAILED], start=1):
        print(f"\n[{number}] {problem.headline}\n{problem.details}")
    if len(problems) > MAX_PROBLEMS_DETAILED:
        print(f"\n(LSan reports of problems {MAX_PROBLEMS_DETAILED + 1}-{len(problems)} omitted, see the logs)")
    print(f"\n{rule}")
    print("Leaks of the runtime library must be fixed. Only a leak that is bounded (once per run) may be listed,")
    print("with a justification, in test/leak_check/known_leaks.txt; a growing leak always fails the check.")
    print(rule)
    return 1


if __name__ == "__main__":
    sys.exit(main())

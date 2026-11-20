<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License.  See the LICENSE file in the package base
directory for details.
-->
# Rodinia hotspot: the lost chunk loop suggestion (analysis and concept)

Status 2026-11-20: analysis done, tests added (`test/end_to_end/cases/do_all/*/conditional_scalar`), no detector
change yet. Remove this file when the open points below are done or dropped.

## Observation

The speedup of DiscoPoP's suggestions for `rodinia_3.1/serial/hotspot` (new_benchmark_harness) dropped from about
4x to 1x. The chunk loop `for (chunk = 0; chunk < num_chunk; ++chunk)` (serial line 70, the loop the reference
OpenMP version parallelizes at line 69) is no longer suggested; only the inner loops of the interior chunks
(136/138) are, which are too small to pay off.

- bisected on master with the current profiler data: last explorer suggesting it eb222a0b9, first rejecting it
  08f83342 ("make branch regions single-entry so branching markers nest")
- the old suggestion (`private(c,delta,r)`, patch of eb222a0b9) gives 3.4-3.7x with 4 threads on 8192x8192

## The rejected loop really is not a do-all loop

The border chunks compute `delta` in an `if / else if` chain over the 4 corners and 4 edges of the grid, without a
final `else`; `result[r*col+c] = temp[r*col+c] + delta;` follows unconditionally. The cells of a border chunk that
are not on the border of the grid take none of the branches and read the `delta` of an earlier cell, at the start
of a chunk the one of an **earlier chunk**:

| grid | stale reads of the same chunk | of an earlier chunk |
| --- | --- | --- |
| 1024 | 44595 | 15825 (first in chunk 127) |
| 8192 | 360435 | 130065 (first in chunk 1023) |

The profiler records it: e.g. `760@405 RAW 663@376|delta` (instruction 760 = line 130, 663 = line 119); the
states `..._loopstate12233` / `..._loopstate01133` differ in the bucket of the chunk loop (first digit, cycling
0 -> 1 -> 2 -> 0 per iteration), i.e. the dependency crosses chunk iterations.

Privatizing `delta` changes the result: the first chunk of a thread may read the private `delta` before writing
it, i.e. an indeterminate value (undefined behaviour). Output of 1024x1024, 2 iterations (`%g`, as compared by the
harness), compared with the serial program:

| threads | eb222a0b9 patch (`private(delta)`) | rodinia reference OpenMP |
| --- | --- | --- |
| 2, 3, 4, 5 | identical | identical (1-5, 8) |
| 6 | not run | 1 line differs |
| 7 | 5 lines differ | 5 lines differ |
| 12 | 4 lines differ | 4 lines differ |

With full precision (`%.9g`) the reference also differs at 3 (30 values) and 5 threads (60 values); 2, 4 and 8
threads stay identical, as their thread boundaries fall on chunks that write `delta` first. With the compiler used
(g++ -O2) the differences are at most 3.1e-5 (one float ulp at about 320 K); with undefined behaviour nothing
bounds them in general. The harness validates 4 threads with `%g`, so the old suggestion passed. The reference
implementation shares the bug (it is a bug of rodinia's hotspot: the interior cells of the border chunks should use
the interior stencil).

## Mechanism of the change

- eb222a0b9: none of the dynamic `delta` dependencies of the chunk loop reached the iteration contexts of the loop
  (probe in the do-all detector: 0 dynamic, only static RAW 1:83..1:125 -> 1:130). The static ones get the "second
  chance" and pass, because `delta` is in `init` (its first write in the program is inside the loop, see below).
  Presumably because the branching markers of the `else if` chain with `&&` conditions were unbalanced (side
  entries into the branch regions, which 08f83342 removes), so that the states of these cells could not be
  assigned to the right contexts (not traced further).
- 08f83342 makes the branch regions single-entry; the states are assigned, the dynamic RAW 1:119 -> 1:130 is
  attached across the iteration copies of the chunk loop, and the loop is rejected as "loop carried dependency".

So 08f83342 fixed a false do-all suggestion; it is no regression. Source fixed (final `else` with the interior
stencil, scratch copy, profiled with 1024): master suggests 70, 79, 80, 142, 144 again.

## Other rodinia benchmarks (old eb222a0b9 vs master b002767d vs reference OpenMP)

Explorer runs on the existing profiles (bfs re-profiled, its data was older than the profiler format), reference
outputs compared with the serial ones at 1, 4, 7, 12 and 36 threads.

- now found, reference output verified identical: bfs 136-150 (and inner 140-148), hotspot3D 162-179, pathfinder
  98-105, lud_base `j` loops 7-11 / 13-17 (checked with a hand-written pragma; the reference lud is a different,
  blocked algorithm). The old rejections were dependencies of the enclosing loop (pointer swaps, levels).
- found by both: lavaMD 112-191; rejected by both for a real histogram dependency: kmeans 3:160-173 (the
  reference uses per-thread partial sums and is not output-identical for more than one thread).
- newly rejected, but not parallelized by the references: loops with early exits, not executed or with too few
  iterations (kmeans, lavaMD argument parsing, lud common.c), a chained pointer dependency (kmeans 2:186-187), and
  the inner `sum -=` loops of lud (neither version offers `reduction(-:sum)` there).
- no loop parallelized by a reference is rejected for a dependency that is not real.

The reduced test cases differ from hotspot in that `r` and `c` are declared in the loops (hotspot: function scope,
old patch `private(c,delta,r)`) and there are 2 corner branches instead of 4; the `excludes` of `stale_read` do not
pin the reason of the rejection (the twins guard against unrelated rejections in part).

## Open points (concept)

1. **Privatization check of conditionally written variables** (test
   `do_all/simple/conditional_scalar/written_on_all_paths_initialized`, xfail). When every path through the if/else
   chain writes the variable before reading it, the loop is still rejected if the variable is initialized before
   the loop. `detect_doall_sharing_clauses` iterates the CUs of an iteration in the order of
   `get_contained_contexts_in_sequence`, which lists the merge CU (the read at the join point) *before* the arms of
   the branch: the variable becomes `firstread`, never `firstwritten`. Without the initializer the loop passes only
   because the first write of the program is inside the loop (`init`).
   Concept: decide "written before read in every iteration" as a must-write property over the branch structure that
   the TaskGraph now has (since 08f83342 every branch region is single-entry with balanced markers): a variable is
   written before a point if it is written before it in the sequential part, or in *every* arm of a branch region
   before it (a region whose arms do not cover all paths, i.e. an `if` without `else`, contributes nothing). The
   sequence order must follow the regions (arms before the merge CU). Further rules: a loop region (possibly zero
   trips) contributes nothing to the code after it, and nothing flows across a back edge (in hotspot the writes and
   the read lie inside the inner loops 79/80); an arm that leaves the region (`continue`, `break`, `return`) never
   reaches the read and counts as covering it; writes through calls or pointers count only if the dependencies show
   them. Must-write has to hold for *every* iteration context: today `firstwritten` is the union of the
   per-iteration-context sets, so one context that sees the write first suffices, which is unsound in the same way
   as `init` (2.).
2. **`init` as an escape of the second chance is unsound.** `init` only says that the first write of the whole run
   happened inside the loop, not that every iteration writes first. It let the stale read of hotspot pass as long as
   the dynamic dependency was missing. Once 1. exists, the static second chance should rely on must-write only.
   Do 1. and 2. together, and run the `conditional_scalar` cases, the e2e suite and the rodinia comparison above:
   `written_on_all_paths` passes today only through `init`, so removing the escape alone breaks it (it guards the
   order).
3. **Explain the rejection.** "A RAW dependency on 'delta' between different iterations" is correct but does not
   tell a user (or an LLM agent) what to fix. When the sink of a loop carried RAW on a scalar is reached on a path
   without a write (e.g. 1. finds no must-write before the read), say so: "the read at 1:130 can see the value of
   an earlier iteration, since not every path writes delta before it (conditional writes at 1:83..1:125)".
4. **Harness validation.** Validate parallel versions with several thread counts (e.g. 4, 7, 12) and, where the
   output format allows, with full precision; one run with 4 threads and `%g` output did not detect the race
   (whether a thread count exposes it depends on where the thread boundaries fall, not on divisibility). The
   expected speedups of the reference implementations / LLM agents for hotspot rest on the same non-equivalent
   transformation.
5. **Pattern regression suite on top of the harness.** Golden `pattern_decisions.json` per benchmark (accepted /
   rejected per loop, with the rejecting dependency), produced by profiling a small input with the current
   profiler (stored profiles break with profiler format changes, see bfs) and compared after explorer changes; a
   difference means "review", not "fail". Reproducible small cases go to `test/end_to_end/cases` as done here.

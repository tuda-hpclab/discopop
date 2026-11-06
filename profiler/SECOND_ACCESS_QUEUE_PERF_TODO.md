<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

# Second access queue performance work: state, todo, instructions

Temporary working document of the branch `perf/profiler-second-access-queue` (off `master`, 2026-11-06).
**Delete this file in the last commit of the branch.**

## Goal

The consumer of the second access queue (`ProcessSecondAccessQueue`, `profiler/rtlib/access_queue_workers.cpp`) is a
single thread. When it falls behind, the first queue workers block in `SecondAccessQueue::Push` and the whole profiling
run waits for it. Move work off that thread, preferably to the first queue workers (cheap to add more of) or to
dedicated cleanup workers, and make what is left cheaper.

## Done on the branch

1. `1fd0ef83` **Phase timers** (temporary, measurement only): `SecondQueuePhaseTimes` in `access_queue_workers.cpp`,
   printed to stderr at the end of the consumer when the environment variable `DP_SAQ_PHASE_TIMING` is set. Phases:
   `get_element` (queue lock), `wait_entry` / `wait_exit` (blocked on the first queue worker's promise), `analyze`
   (dependency analysis of the entry accesses), `merge` (bringing the persistent shadow up to the chunk's end state),
   `release` (freeing the chunk's data), `idle` (usleep, queue empty).
2. **Cleanup workers**: `GarbageQueue` / `RetiredChunk` (`runtimeFunctionsTypes.hpp`), `ProcessGarbageQueue`, threads
   started in `InitParallelization` and joined in `FinalizeParallelization` after the consumer. The consumer retires the
   entry vector, the exit shadow and the queue element instead of deleting them; if the bounded queue
   (`kCleanupQueueElementsPerCleanupWorker` = 2 per cleanup worker) is full it deletes inline as before.
   Option `CLEANUP_WORKERS` in `dp.conf` (default `kDefaultCleanupWorkers` = 1, `0` = old behaviour). Unit tests:
   `test/unit_tests/access_queues/test_garbage_queue.cpp`.

## Measurements so far (desktop, 8 cores, noisy; LULESH `-s 10`, ~760M accesses, 7589 chunks, 3 runs per setting)

| `NUM_WORKERS` | `CLEANUP_WORKERS` | release | merge | wall |
|---|---|---|---|---|
| 4 | 0 | 0.46-1.05 s | 4.6-6.3 s | 17.7-22.7 s |
| 4 | 1 | 0.03-0.08 s | 4.9-6.7 s | 18.1-22.5 s |
| 8 | 0 | 1.3-1.7 s | 5.7-7.1 s | 21.5-27.7 s |
| 8 | 1 | 0.18-0.35 s | 5.9-8.0 s | 22.4-28.1 s |

- The cleanup workers cut the consumer's release time by ~90 %, but the wall time did not change measurably: runs of
  one setting differ by up to 5 s (desktop with other load), and the consumer was often *waiting* for the first queue
  workers (`wait_entry` 6-11 s), i.e. it was not the bottleneck in these runs. With 8 workers the 11 threads
  (8 + consumer + main + cleanup) oversubscribe 8 cores.
- Earlier, quieter baseline (4 workers, before the cleanup workers, 13.7 s wall): analyze 5.3 s, merge 4.2 s,
  wait_entry 3.4 s, release 0.5 s.
- `merge` (4-8 s) is much larger than `release`; it is the bigger lever (todo 2).

## Todo

1. **Re-measure on a more capable machine** (the reason this document exists), see "How to measure". Questions: is the
   consumer the bottleneck there (`wait_entry` small, `analyze`+`merge` ~ wall time)? Does `CLEANUP_WORKERS=1` or `2`
   change the wall time? Use 5+ runs per setting and compare medians; try `NUM_WORKERS` 4, 8 and more than 8.
2. **Merge summary** (not started): the first queue worker builds, from its chunk-local shadow, a compact vector of
   unique `(addr, last_read, last_write)` and publishes it instead of the whole exit shadow (and deletes its shadow
   itself). The consumer's merge then is two plain writes per entry instead of `sig_read->at()`, `sig_write->at()`,
   `UpdateInRead`, `UpdateInWrite` (4 hash operations per entry, repeated for an address with several LIDs, see
   `access_queue_workers.cpp`, merge loop). The values written must stay identical to today's. Separate commit,
   measured separately (`merge` phase).
3. **Single lookup per shadow access** in `AnalyzeSingleAccess` (`dependency_analysis.cpp`) / `PerfectShadow2`
   (`memory/PerfectShadow.hpp`): `TestInWrite` is an `operator[]` (inserts zero entries on a miss), `InsertToRead`
   does `find` + a second lookup on a miss. Use a find-or-insert returning a reference; the consumer can hold a
   `PerfectShadow2*` instead of going through the virtual `AbstractShadow`.
4. **Software prefetch** in the analysis and merge loops: the entry vector is known up front, prefetch the buckets
   of entry `i+8` while handling entry `i` (the persistent shadow is large and accessed randomly).
5. **Possible correctness bug, verify with a test first**: the exit shadow's `TestInWrite` / `TestInRead` create zero
   entries via `operator[]`. A chunk that only *reads* an address has `write_cache_[addr] == 0`, and the merge calls
   `UpdateInWrite(addr, 0)`, which would erase the last-write information of earlier chunks (a later read on another
   line would miss its RAW). Conversely `read_cache_` may lack an address a chunk only wrote once, and `at()` on
   `emhash7` may throw / be undefined. Test idea: write in chunk 1, read in chunk 2, read on a different line in
   chunk 3.
6. **`Push` under the first queue's lock**: `FirstAccessQueue::Get` calls `SecondAccessQueue::Push` while holding the
   first queue's mutex; when the second queue is full the worker sleeps (`usleep(1000)`) in there with the lock held,
   blocking every other worker's `Get` and the main thread's `Push`. Needs a ticket/sequence number so the order of the
   second queue is kept without holding the lock. Design problem, separate step.
7. Smaller: the consumer polls with `usleep(1000)` and a mutex-protected `Get()` (up to 1 ms latency when empty);
   `DeferredAccessHash` (first queue deduplication) is a weak hash on a node based `std::unordered_set`;
   `entry_condition_accesses` is not reserved; `AccessInfo` is 40 bytes, the second queue needs few fields.
8. **Cleanup at the end**: remove the timing code (`SecondQueuePhaseTimes`, the `phase_times` calls, `<chrono>` /
   `<cstdlib>` includes if unused) in a separate commit after the final measurements, and delete this file. Decide
   whether `CLEANUP_WORKERS` stays at default 1 or 0 based on todo 1; document the option wherever the other `dp.conf`
   options are documented (`docs/`).

## How to measure

Always bound memory and keep other load off the machine: `systemd-run --user --scope -q -p MemoryMax=8G -p MemorySwapMax=0 <cmd>`.

```bash
# 1. profiler (NOT editable) into a scratch venv; rebuild after every change below profiler/
python3 -m venv $S/venv_prof
systemd-run --user --scope -q -p MemoryMax=12G -p MemorySwapMax=0 $S/venv_prof/bin/pip install --force-reinstall --no-deps ./profiler

# 2. LULESH from the benchmark harness, copied (do not dirty the harness): CMakeLists.txt, *.cc, *.h of
#    /home/lukas/git/new_benchmark_harness/benchmarks/LULESH/LULESH_SEQ into $S/lulesh
cd $S/lulesh && rm -rf build && mkdir build && cd build
PATH=$S/venv_prof/bin:$PATH cmake -DWITH_MPI=Off -DCMAKE_CXX_COMPILER=discopop_cxx .. && PATH=$S/venv_prof/bin:$PATH make
# the program must be rebuilt after every profiler rebuild (the runtime library is linked in)

# 3. the runtime reads options from dp.conf in the directory of the executable
printf "NUM_WORKERS=4\nCLEANUP_WORKERS=1\n" > dp.conf
DP_SAQ_PHASE_TIMING=1 ./lulesh2.0 -s 10 > /dev/null      # prints "[DP_SAQ_PHASE_TIMING] thread N: ..." on stderr
```

`CLEANUP_WORKERS=0` is the old behaviour (A/B switch in one build); the other options are `NUM_WORKERS`,
`FIRST_ACCESS_QUEUE_CHUNKS_PER_WORKER` and `SECOND_ACCESS_QUEUE_ELEMENTS_PER_WORKER` (see
`ReadRuntimeInfo` in `profiler/rtlib/runtimeFunctions.cpp`). Loop over reps x `NUM_WORKERS` x `CLEANUP_WORKERS`,
interleaved, and log wall time plus the timing line; compare medians. The harness
(`/home/lukas/git/new_benchmark_harness`, `memory_overhead` / `speedup`) can run other benchmarks (miniFE, NPB) once a
venv is registered, but the direct run above gives the consumer phases, which the harness does not.

Unit tests: `cmake -S . -B build_tests -DCMAKE_BUILD_TYPE=Release -DDP_BUILD_UNITTESTS=1 && cmake --build build_tests --target DiscoPoP_UT -j4 && build_tests/test/unit_tests/DiscoPoP_UT`.
Style: `clang-format -i` the changed files (profiler/.clang-format); the profiler's other checks are in `CLAUDE.md`.
Also run `venv/bin/python -m pytest -n 3 --dist loadgroup test/instrumentation test/profiler` and the leak check /
sanitizer scripts (`scripts/dev/run_profiler_sanitizers.sh thread` is the important one for the new threads) before a PR.

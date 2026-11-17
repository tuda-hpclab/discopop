<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License.  See the LICENSE file in the package base
directory for details.
-->
# Plan: threads instead of processes in the explorer (free-threaded Python)

Status: plan + compatibility test only; no explorer code changed yet. Branch `feat/explorer/free-threading`.

## Correction (2026-11-17): the relevant code and the first target

The active detectors are `new_do_all_detector.py` and `new_task_detector.py`; `do_all_detector.py` / `reduction_detector.py` (the two `Pool`s below) are no longer called by `pattern_detection.py`, and the `jobs` argument has no effect on detection any more. The sections "Where the explorer uses multiprocessing today" and the steps that build on them (3, 4) are therefore obsolete; the plan is to introduce threading where the time is spent in the current pipeline.

**First target: `PEGraphX.calculateFunctionMetadata`** (outcome: see "Results for the first target" below; the analysis in this paragraph was the starting point) (stage "[3/5] Calculating function metadata"). It used to be a process pool and was made serial because forked workers copied the graph (146 MiB -> 1.1 GiB on LULESH); threads share one graph, so that reason is gone.
- Measured on relearn (server, `discopop_explorer`): **476.6 s** for 15 240 functions (~32 functions/s, serial); loop metadata 0.6 s, whole PET construction ~43 s (local). On BT: 5.5 s. The cost grows with the size of the graph, so it matters exactly for the large inputs.
- The per-function work (`parallel_utils.pet_function_metadata_parse_func`) only reads the graph (`out_edges`, `node_at`, `nx.subgraph_view`, `nx.condensation`; no caches anywhere on that path) and writes only to its own `FunctionNode` (`children_cu_ids`); `calculate_reachability_pairs` builds its own dicts/sets. The parent merges the results serially (`reachability_pairs` per function, `parent_function_id` per child) in function order, so the result stays deterministic.
- So the change is small: `parallel_map` (step 2) over `all_nodes(FunctionNode)`, `pet` passed explicitly instead of the module global `global_pet` in `parallel_utils.py`, merge unchanged. `children_cu_ids` is the only node write inside the worker; it belongs to the function that is processed, and no other task reads it.
- Test: unit test comparing serial and threaded results on a graph with several functions (also shared children), run under `python3.14t`; measurement on relearn data (needs more memory than the local 30 GB: the PET alone is ~12 GB RSS; run on gh1).

Next candidates, to be ranked with the timings of the benchmark runs (BT local, see below): "Calculating loop metadata" (44 s on BT, 0.6 s on relearn - input dependent), "Constructing TaskGraph structure" (41 s on BT: "Adding work nodes" 7.7 s, "Adding branching nodes" 17.5 s, "Inlining function calls" 6.4 s - the per-function loops of `TaskGraph`), "Mapping static and dynamic dependencies" (18.5 s on BT), "Assigning state ids" (13.7 s), "Inserting data dependencies", and the per-loop scan of `identify_simple_doall_and_reduction`.

## Results for the first target (relearn, gh1, aarch64, python3.14.7t, 36 cores) - threads were not the answer

| `calculateFunctionMetadata` (15 240 functions) | time |
|---|---|
| serial, first version (graph view with an edge filter per function) | 544.9 s |
| same, 32 threads | not finished: 122 of 15 240 functions after 120 s (threads ~90% asleep) |
| serial, edges read once as plain id lists (`function_metadata_edges`) | **2.2 s**, result identical (digest) |
| same, 4 / 8 / 16 / 32 threads | 1.7 / 1.5 / 1.5 / 1.4 s, identical |

- The cost was algorithmic: for every function the reachability was computed on `nx.subgraph_view` of the whole graph (node filter, edge filter on the edge type). Iterating the nodes of such a view walks *all* nodes of the graph (the filter is a lambda), i.e. functions x nodes: ~19 ms per call on a graph of relearn's size (143 646 nodes) even with an edge filter that reads nothing, ~290 s over 15 240 functions (extrapolated from a synthetic graph, not measured on relearn); the rest of the 545 s are the edge type reads and successor lookups of the view. Reading the edges once into `children` / `successors` id lists (`parallel_utils.function_metadata_edges`) removes it: 250x, same output. At 2 s the stage is not worth threading (1.4 s with 32 threads; the edge pass and the merge stay serial), so `calculateFunctionMetadata` runs serially again (no `jobs` parameter).
- **Lesson for threading anything in the explorer: shared objects whose reference count changes are a serial bottleneck on the free-threaded build.** `d.etype == EdgeType.SUCCESSOR` reads the one `EdgeType.SUCCESSOR` member that all edges point to; with every thread updating its reference count, N threads each working on their own list took N times as long (micro-benchmark on gh1: 1 thread 0.20 s, 8 threads 3.7 s, 32 threads 15.0 s, i.e. 76x; a small int tag in place of the enum scaled perfectly: 0.12 s at 1 and at 32 threads). Not the GC (`gc.freeze()` of the 64M objects of the graph did not change the rate). The same holds for every hot loop that compares `EdgeType` / `NodeType` / `DepType` members, calls methods on one shared object, or uses shared constants: such code has to be changed (ints, ids, per-thread data) before it can scale, and the helper `parallel_map` alone does not help.
- Hardware note: the development machine (Core Ultra 7 258V) has 4 performance and 4 efficiency cores, no hyperthreading; 3x with 8 threads on a synthetic graph is its ceiling. Use gh1 (limited to cores 0-35) for scaling numbers.
- Second finding, same kind: `enforce_single_function_exit_node` searched all nodes of the graph for the highest id of the function's file for every function: 569 s on relearn. The highest id is now determined once per file (the exit node of a function counts for the next function of the file); measured on relearn (gh1): old implementation 730.7 s, new 1.80 s (405x), resulting graphs identical (digest of nodes, names, lines and edges; 15 240 exit nodes added); also identical on LULESH and BT and in the unit test (`test_enforce_single_function_exit_node.py`, which keeps the old implementation as reference).
- Timings of the other stages (relearn, server, serial): PET construction ~53 s, loading the AST ~58 s, TaskGraph structure 66.8 s (duplicating loop iterations 21.5 s, branching nodes 17.9 s, inlining calls 8.7 s), state ids 9.3 s, data dependencies 12.8 s, doall/reduction 53.7 s. BT (local): doall/reduction 201.8 s, TaskGraph 135.9 s, ContextTaskGraph 120.1 s, simplifying 86.6 s, data dependencies 79.0 s, loop metadata 44.1 s.

Revised order of work: look for per-element work that is quadratic or scans the whole graph (the recurring pattern in this codebase, see the stage measurements above) before threading; thread only stages that remain large and whose workers can be made to touch no shared enum members or shared objects.

## Where the explorer used multiprocessing (obsolete, see above)

Only two places (`grep -rn "multiprocessing\|Pool(" explorer`):

| Place | Pool | Work item | Result |
|---|---|---|---|
| `pattern_detectors/do_all_detector.py` `run_detection` | `Pool(initializer, initargs=(pet,))` (ignores `jobs`, uses `cpu_count`) | `__check_node(loop)` | `List[DoAllInfo]` |
| `pattern_detectors/reduction_detector.py` `run_detection` | `Pool(processes=jobs, ...)` | `__check_node(loop)` | `List[ReductionInfo]` |

`PEGraphX.calculate_function_metadata` already runs serially on purpose (a pool copied the graph per worker, 8 workers: 146 MiB -> 1.1 GiB on LULESH). Threads share one graph, so that argument disappears.
The `library` package has more pools (`discopop_optimizer`, `EmpiricalAutotuning`); they are out of scope here, see step 7.

Both pools hand the graph to workers through a module global (`global_pet`) set by an initializer; results are pickled back.

## Compatibility test (done)

`explorer/discopop_explorer/test_free_threading.py`:
- the GIL stays off after importing networkx / numpy / scipy / lxml / jsonpickle / the explorer (skipped on a GIL build),
- `__detect_do_all` / `__detect_reduction` called by 8 threads at once on one shared `PEGraphX` equal the serial result (20 rounds, barrier start),
- concurrent reads of the graph are consistent.

Environment (outside the repo): `uv venv --python 3.14t ~/venvs/discopop_ft`; `discopop-library` and `discopop-explorer` installed with `--no-deps` plus their dependencies by hand, because `PySide6` has no free-threaded wheel (the explorer does not need it) and `extrap` pulls in PyQt5 (builds from source, fails). Run:
`PYTHON_GIL=0 ~/venvs/discopop_ft/bin/python -m pytest explorer/discopop_explorer -n 3`.

Result 2026-11-17 (3.14.6t): all 909 explorer unit tests pass (1 skipped), GIL stays off, new tests pass; on 3.12 they pass too (GIL test skipped).
What this does not show: speedup (the test graphs are tiny), and the real end-to-end pipeline (no extrap, no PySide6 in that venv).

## Hazards that differ between processes and threads

1. **Mutation of nodes becomes visible.** `__check_node` sets `node.do_all` / `node.reduction`, `__detect_reduction` sets `root.contains_array_reduction`. In a process pool these writes happen on the worker's copy and are lost in the parent; only the serial path (`jobs <= 1`) keeps them. With threads they will be kept, so results can differ from today's parallel results (and become equal to the serial results). The do-all detector reads `node.reduction` / `contains_array_reduction`. Decide per attribute: keep (matches `--jobs 1`) or return as part of the result and apply in the parent. Preferred: workers are pure (return values only), the parent applies the flags in node order, so the outcome never depends on thread timing.
2. **Pattern ids.** `DoAllInfo` / `ReductionInfo` allocate ids in their constructor from `next_free_pattern_id.txt` under a `FileLock` (`PatternBase.request_pattern_id`). Threads in one process: `FileLock` is reentrant per instance but two instances in two threads still serialize on the file, which is correct but slow, and the id order follows thread timing (also true for processes today, so `patterns.json` ids are already unstable). Better: construct the info objects in the parent, in node order, after the parallel check (the check returns only "is a pattern", the constructor is the expensive-looking part only for `get_workload`; measure first). That also makes ids deterministic.
3. **`global_pet`.** Per-process globals worked because every worker had its own. Shared across threads it is read-only, but a module global is fragile (two detections in one process, e.g. the GUI or MCP server calling the explorer twice, would clash). Pass `pet` explicitly (`functools.partial(__check_node, pet)`), delete `global_pet` and both `__initialize_worker`.
4. **Hidden shared state in the detectors and in `PEGraphX`.** Anything memoized in a dict/list on `pet` or on a node while checking (e.g. `__get_parent_loops`, `subtree_of_type`, `out_edges` caches) is a data race when two threads fill it. Audit: grep `PEGraphX` and `utils`/`ASTUtils` for lazily filled attributes, `functools.lru_cache` (thread-safe but may compute twice), class-level mutable defaults (known review item "shared mutable defaults", see `project_explorer_review_bugs_todo`). The concurrency test only covers graphs without such caches: extend it with a real `PEGraphX` loaded from `test/end_to_end` data.
5. **`progress` / tqdm** is called from the parent only; keep it there (`as_completed` loop), no output from workers.
6. **Exceptions.** `imap_unordered` re-raises in the parent; `ThreadPoolExecutor` futures do the same through `.result()`. Keep the failing node id in the error message.
7. **Pickling goes away:** the `Info` objects no longer need to be picklable for this path (still needed for `jsonpickle` output).

## Steps

1. **Baseline** (no code change): record serial vs. multiprocessing results and times for the e2e cases and LULESH/miniFE (`--enable-patterns "reduction,doall"`, memory bounded with `systemd-run MemoryMax=8G`). This is the reference for step 4 (note: pattern counts are nondeterministic today, `project_explorer_nondeterministic_pattern_count`; compare sorted tags with node ids, not counts).
2. **One helper**, `discopop_explorer/parallel_utils.py` (already exists): `parallel_map(fn, items, jobs, desc) -> List[R]` on `concurrent.futures.ThreadPoolExecutor`, `jobs` None -> `os.cpu_count()`, `jobs <= 1` -> plain loop, results returned in input order (deterministic), progress in the parent. Unit-test it (ordering, exception propagation, `jobs=1`).
3. **Make the work function pure**: `__check_node(pet, node) -> Optional[...]`, no writes to `node`, no `global_pet`; the parent applies flags and builds the `Info` objects in node order (hazards 1-3). Do reduction first, then do-all, as now.
4. **Switch both detectors** to `parallel_map`; run the whole explorer + e2e suite on the regular interpreter. Expected: identical patterns to `--jobs 1`.
5. **Race audit** (hazard 4): add the real-graph concurrency test; run it 100x on 3.14t with `PYTHON_GIL=0`, and with the GIL on (3.12/3.13) to make sure nothing regresses there. Candidate tools: `PYTHON_GIL=0` stress loop; TSan-enabled CPython build if a finding is suspected.
6. **Measure**: on a GIL interpreter threads give **no** speedup for this pure-Python work (and the pool of processes is replaced, so `--jobs N` could get *slower* there). Only on `python3.14t` do the threads scale. Decide with numbers from step 1 vs. 6 on LULESH/miniFE:
   - free-threaded available and `sys._is_gil_enabled()` false -> threads;
   - else -> keep the process pool as fallback (a `--parallel-backend {auto,threads,processes}` option, `auto` picks by `sys._is_gil_enabled()`), or serial. Recommended: keep both backends; delete the process one only when 3.14t is the supported baseline (`requires-python` is `>=3.11` today).
7. **Packaging and CI**: the explorer imports `discopop_library`, which requires `PySide6` and `extrap` (no free-threaded wheels): move GUI/extrap dependencies of `library` into extras (`library[gui]`, `library[extrap]`) or make the explorer not depend on them, so `pip install explorer` works on `3.14t`. Add a CI entry (`python3.14t`, explorer unit tests + `test_free_threading.py` + the explorer part of the e2e tests with `PYTHON_GIL=0`); the e2e tests need the profiler/LLVM, which is Python-independent. Extra: `library/discopop_optimizer` and `EmpiricalAutotuning` pools follow the same recipe afterwards (the optimizer passes large `experiment` objects through `initargs`, which is where threads would also save memory).
8. **Docs**: `docs` page for `--jobs` (what it means now, backend, recommendation to use `python3.14t`), `CLAUDE.md` Testing section (the venv recipe above).

## Risks / open questions

- Single-thread slowdown of the free-threaded build (~5-10%) must be repaid by the parallel part; the explorer's detection stages that dominate (see `project_explorer_detection_stage_breakdown`: two silent PET passes, the doall check is only third) are **not** these pools, so the end-to-end gain may be small until those stages are parallelized too. Measure the share of time spent inside the two pools first (step 1).
- The task detector / `TaskGraph` code is not touched by this plan; it is serial and mutates shared state heavily.
- networkx makes no thread-safety promise; the plan relies on "no writer while readers run" and enforces it by structure (pure workers), not by locks.

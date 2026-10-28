<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

# Task suggestions in get_parallelization_suggestions — Plan & Todos

Status: MCP tool part implemented (task groups in `mcp_server/tools/task_groups.py`); the
rest of 3.1 and 3.2 is open. Branch:
`improvement/mcp_server/task_suggestions`, based on `improvement/mcp_server/interface`.

`get_parallelization_suggestions` lists task parallelism as type `pattern` with a bare
`#pragma omp parallel` (the fallback in `get_parallelization_suggestions.py`, because only
`do_all` and `reduction` are mapped). It should instead describe the surrounding parallel
region, the bodies of the contained tasks and the variable dependences between them. The
agent derives the actual pragmas and their positions from that description, because the
explorer's positions are not always applicable one to one.

---

## 1. Findings (2026-10-22, BOTS `serial/fft` and `serial/fib`)

- The explorer emits two kinds of objects under the key `task` of `patterns.json`:
  `TASK` (not standalone) and `PARALLELREGION` (standalone, `contains_patterns` lists its
  tasks). Only the regions have patches, so only they are listed today.
- (until 2026-10-22) `gather_data` ran the explorer with its default `--enable-patterns reduction,doall`;
  task detection has to be enabled by hand.
- Task entries have no decision-log entry, so the tool shows kind `Loop` and no hotspot.
  The printed line is the first line of the patch's `@@` header (context start), e.g.
  `fib.c:28` for a region starting at line 31.
- `region_*_line` are bare line numbers; the file id is only part of `start_line`
  (`"fid:line"`), which is the span of the enclosing CU, not of the region.
- `262143` as an end line is a sentinel for "unknown"; the side-effect export has it as
  `end_line` of 17 of the 35 functions of fft.
- `Hotspots.json` knows loops and functions only, by `(file id, start line)` without end
  line. Its function lines are one higher than the side-effect export's (`fft_aux` 2907
  against 2906), so match on file id and name.
- `side_effects.json.gz` lists all functions (file id, start line, end line) and is enough
  to find the function enclosing a region.
- fib: group at `fib.c` 31-32 is the real one, but task 2 is reported as 31-32 and thus
  overlaps task 1 (31-31); `x` and `y` are read at line 34 and nothing says the group needs
  a join before it. The other two groups are `sprintf` blocks in `bots_print_results` and
  a call plus the closing brace in `bots_get_params`.
- fft: none of the 26 groups is the parallelism in `fft_aux` (the recursive call in the
  `for` loop at line 2951). Most are branches of an `if ... else if` chain (mutually
  exclusive), a call plus its `return`, or a call plus a message print.

## 2. Output (sketch)

One entry per task group, hottest enclosing scope first:

    Suggestion 5: Task group in Function fib.c:26-35 (inside Hotspot Function fib, <runtime> s, <share>% of runtime)
      parallel region: fib.c:31-32
      task 3: fib.c:31-31   x = fib(n - 1);
      task 4: fib.c:32-32   y = fib(n - 2);
      dependences: none between the tasks
      read after the region: x (line 34), y (line 34)
      flags: ...

No pragmas are printed for tasks; the text says which constructs are needed (parallel
region, tasks, a join before the reads after the region, clauses for the dependences).
Implausible groups are flagged, not hidden (see 3.3).

## 3. Todos

### 3.1 MCP tool (this branch)

- [x] Map the `task` key; list one entry per `PARALLELREGION` with its tasks via
      `contains_patterns`; take the file id from `start_line`.
- [x] Print `in_dep` / `out_dep` / `in_out_dep` as dependences between tasks; RAW as the
      main information, WAR/WAW marked `(anti)` / `(output)`.
- [x] Hotspot of the enclosing function: find the function from the side-effect export, then
      match the hotspot by file id and name (not by line). Say "no hotspot data" if there is
      no match or no export. State that the runtime is the scope's, not the region's, and
      that recursive functions are counted inclusively.
- [x] Flags: identical spans of two tasks, overlapping spans, unknown end line (262143),
      task body that ends in a `return` or is a closing brace.
- [-] Single-statement flag: dropped. It is not helpful for a statement that is or contains a
      function call (maintainer), which covers the real fib tasks and most others. Only worth
      reconsidering for statements without any call (e.g. a plain assignment), if such groups
      turn out to be noise.
- [x] Do not use the first `@@` line or the default kind `Loop` for tasks.
- [x] Relations (`nested_in` / alternative) for task regions and doall loops, e.g. a region
      inside the loop of a doall suggestion.
- [x] `explain_parallelization` for task regions (names the group covering the lines; reasons
      for rejected groups need the decision log of 3.2); tool description and
      `docs/tools/MCP_server.md`.
- [x] Tests with fixtures from the fib and fft runs (`fft_task_groups_fixture.py`) (including the stale or missing
      hotspot and side-effect data).
- [x] `gather_data` detects `task,doall,reduction` by default (maintainer's decision). The
      explorer writes the list of detected pattern types as `enabled_patterns` into
      `patterns.json` (top level, beside `patterns`); the staleness check repeats the detection
      if one of the three is missing. The explorer writes the patches itself.

### 3.2 Explorer follow-ups (separate work)

- [x] **Fill `in_dep` / `out_dep` / `in_out_dep`** (done on `integration/task_detection`: WAW is read from the PET and shown as
      `(output)`; real-data test `test/end_to_end/task_dependences`; RAW and WAR between the tasks of a group cannot occur,
      they are the join, see 3.5). Old text: (`clauses_of_dependences`; `ParallelRegionInfo.task_dependences`
      carries variable and kind, RAW and WAR; WAW is not registered on contexts; the tool prints `(anti)`). Groups
      are built from tasks without a data edge between neighbours, so a dependence only shows for non-adjacent
      tasks of a group of three; untested with real data (unit tests only). Old note:
      Then the tool (`task_groups.dependences`) must be adapted: it prints the fields as
      `in x; out y; in/out z` without telling the kind of dependence. Per the agreed
      presentation, RAW is the main information and WAR/WAW are marked `(anti)` / `(output)`,
      which needs the kind per variable in the explorer's output (a new field or a tagged
      entry); add a test with real dependences (fib: none; take a case from `bots/omp-tasks`).

- [x] **Tests from `bots/omp-tasks`** (done: `test/end_to_end/task_omp_<app>` for eight apps, a test one level down in
      `classes/TaskGraph/test_ContextTaskGraph_simplification.py`, `test/end_to_end/task_only`). Old text: `pattern_detectors/test_new_task_detector.py`
      feeds `identify_simple_tasking` with the code scopes captured in a run on serial fib and
      bots_main/bots_common and states what omp-tasks does as the expectation; known deviations
      are `xfail(strict)`. Open: more applications (nqueens, knapsack, health, floorplan, uts,
      sort, strassen, fft: take the scopes of a run on `serial/<app>`, expectation from
      `omp-tasks/<app>`), and a test one level down (ContextTaskGraph simplification) because
      the scopes are stubbed. Findings so far: the overlap of fib's tasks comes from the CU
      generation, not from the detector: CU 3:237 starts at line 31 (`startsAtLine`) though its
      call is on line 32, and the scope of a task is the line range of its CUs.
- [x] **Loop and recursive tasking.** `identify_loop_tasking` (`new_task_detector.py`): a do-all loop whose body
      calls a hotspot function (any call without hotspot data) is one task per iteration (`loop_start_line` on
      task and region; fft: the loop of `fft_aux`, 2951). The do-all detection runs for it even if only `task` is
      requested. Open: loops with some dependences between the iterations (`depend`), the join analysis (done for loop tasks too,
      see Join points).
- [x] **Mutually exclusive branches / conditional tasks.** `identify_simple_tasking` drops tasks that do no work
      (CUs without variables and calls: `return`, the jump over an `else`) and tasks that lead to more than one CU
      outside of them (end in a conditional branch: `||` operands, `bots_message`), and groups with fewer than
      two tasks left. fft: 27 groups -> 14 (13 real pairs, one `sprintf` group). Possible later: do the check in
      `split_taskable_control_sequence` (note in `_is_valid_task_body`).
- [x] **Task bodies.** `return` statements and closing braces are no tasks any more (no-work rule, see above);
      spans of tasks leave out the lines that hold jumps only (the closing brace of a loop body), see
      `jumpInstructionIDs` in `Data.xml` and `PEGraphX.jump_only_lines`; fft: the loop task is 2952-2952. Not done:
      extending a span to the end of a statement that continues on lines without instructions (a lone `);`),
      which needs the AST (`ast_dump.json`); no span of fft ends mid-statement.
- [x] **Overlapping spans** (fixed by the CU split, `design/instruction_focus.md`). Task 2 of the fib group starts at the line of task 1
      (31-32 against 31-31); derive the spans per task without the shared scope lines.
- [ ] **Unknown end line.** Replace the sentinel 262143 by a real end line, or omit it.
- [x] **Join points.** `ParallelRegionInfo.after_dependences` (task, variable, RAW/WAR, first line after the region),
      from the dependences registered on the TaskGraph contexts (`pattern_detectors/task_dataflow.py`); the tool prints
      the join line. Loop tasks: `loop_after_dependences` queries the PET (RAW/WAR from the instructions of the loop to a later line of
      the file); the tool names the line, else it keeps the generic "after the loop". Writes through pointer parameters of callees
      (not in the task contexts) come from the PET (`after_dependences_of_instructions`: sources in the instructions of
      the task and of its callees, sinks in the function after the task, or in the callees of calls there, reported at
      the line of the call). Done on `integration/task_detection`: tasks that reach their own function (the code of the function counts as the
      task's work: an over-approximation, no `at_return`, see 3.7), reads in the caller after the function returns
      (`at_return`, `line = null`, printed as "complete before the function returns"), the names are names of the
      function's scope (heuristic, `""` if none). Open: the name heuristic needs the call arguments of the AST.
- [x] **Data sharing.** Filled from the accesses, not the types (`classify_variable`): declared in the task and not
      needed after: private; global, written, or written by a sibling: shared; otherwise firstprivate. Loop tasks take the sharing of the do-all loop, plus what the code after the loop reads as shared. Done: reductions and lastprivate (`reduction`, `last_private`, see 3.5). Open: reductions,
      last private, what pointers point to (side-effect export).
- [ ] **Enclosing loop.** Export the innermost enclosing loop (start line) of a region so
      that its hotspot can be matched; loops are not in the side-effect export.
- [ ] **Decision log.** Record task decisions (accepted and rejected groups) in
      `pattern_decisions.json` like doall and reduction do.
- [ ] **Side-effect export:** `static_callees` of `fib` is empty although it calls itself;
      check whether self recursion is excluded on purpose. A recursion flag per group
      (callee is the enclosing function) would let the output suggest a cut-off.
- [x] **Patch generation for task patterns** (`integration/task_detection`: the patches were wrong and are fixed,
      `test/end_to_end/task_patches` applies them and compiles; open: a task line that is a declaration cannot be patched,
      dependences between tasks use `taskwait` not `depend`, the region wraps the tasks, not the first call in the caller;
      the printed line of the tool does not come from the patch). Old text: Fix it: the patches of `PARALLELREGION` and `TASK` entries are not
      verified (what the patch generator makes of `PARALLELREGION` in the `task` list; `UnpackedSuggestion` handles
      `task` and `parallel_region` separately; the line the tool prints for a task patch is unexplained). Check the
      generated patches for fib, fft and the loop tasks, and fix what is wrong.
- [x] **Nondeterministic task detection.** The same profile gave different groups from run to run (sometimes none).
      Causes, all sets or dicts ordered by the address of objects: the iteration nodes copied by the loop
      duplication, the work nodes inserted, the calling nodes inlined, the function and iteration contexts created
      (`TaskGraph.py`); the contexts and dependences are kept in sets, so `Context.__hash__` and
      `Dependency.__hash__` are no longer the address. `split_taskable_control_sequence` now visits the nodes in
      program order, so of overlapping candidates (`put(&a); put(&b); if (a + b)`: the pairs (a, b) and (b, if)) the
      earlier is split first. The explorer gives the same result on one profile, with any `PYTHONHASHSEED`; fft: the same
      44 entries. Test: `test/end_to_end/task_pointer_flow`.
- [~] **omp-tasks cases as end-to-end tests** (`test/end_to_end/task_omp_<app>`: nqueens, knapsack, health, floorplan, uts,
      sort, strassen, sparselu; reduced reproductions, omp-tasks as the expectation; 4 pass, 42 `xfail(strict)`). Found by
      them, to fix (the xfail then turns into a failure that says so):
      - **Crash on loops with recursive calls** (health, floorplan, uts): fixed (`39af76fc`: a nested `Start IT` of the
        same loop counts like a nested end). Since then the explorer finishes on health (about 11 s) and uts (about 4 s);
        floorplan does not finish (120 s guard in the test: `ContextTaskGraph` construction of 45142 nodes slows down to
        under 100 nodes per second).
      - **health: groups not found:** fixed on `integration/task_detection`: the loops are pointer-chasing `while` loops
        (`while (v) { f(v); v = v->next; }`) with a carried RAW on the cursor, which only the update has; they are loop
        tasks now (`task_cursor_loops.py`), and groups with a dependence between neighbouring tasks are dropped (18 -> 6
        entries). Open: the join before `check_patients_realloc`, the sibling race on the parent's field.
      - **uts: no task pattern at all** (the do-all detection rejects the loop, RAW on `parent` between the iterations).
      - **Cost per recursive call site** (sort: 90 s guard in the test, strassen: memory limit of 4 GiB in the test):
        `ContextTaskGraph` construction grows about 9x per call site; seven self-calls of a function run out of memory in
        `__insert_data_dependencies_from_files`.
      - **Duplicates** (health, knapsack): fixed; `identify_simple_tasking` reports a group once per (parent PET node,
        line ranges and instruction ids of its tasks). Health: 594 -> 18 entries, knapsack: 17 regions -> 1 (its xfail is
        gone). Not checked on the fft profile (44 entries before; no BOTS profile on the second machine).
      - **Spans and joins** (nqueens, sparselu): fixed on `integration/task_detection`: the region and task cover the
        task statement (not the loop header, guard conditions or nested headers), one suggestion per nest (innermost
        loop), WARs on firstprivate variables are no after dependences; the joins of nqueens and knapsack are found.
        Open: sparselu fwd and bdiv are two regions (one taskwait in omp-tasks), the sharing of `csols` / `b` in nqueens
        and of the loop index in sparselu; one tiny region (`genmat`) remains by design.
      - Strassen, health, floorplan and the join/sharing expectations are guesses until the explorer gets that far.
- [x] **Docs** (done on `integration/task_detection`: `docs/data/Parallel_patterns/tasks.md`, `Explorer.md`, `Explorer_output.md`,
      `Patterns.md`, `Profiling_and_instrumentation_output.md`, `MCP_server.md`; keep it current when the fields change). Old text: Update the documentation where necessary (`docs/tools/MCP_server.md`, the explorer docs and the
      description of the new `patterns.json` fields `task_dependences`, `after_dependences`, `shared`, `private`,
      `first_private`, `jumpInstructionIDs` in `Data.xml`) once the data flow work is finished.
- [ ] **Trivial groups.** Groups of unprofitable code (a few `sprintf` calls in the shared
      BOTS sources) are reported with the same weight as real ones.

### 3.3 Recursion in the call path states (profiler)

The call paths of the profiler are cut at a recursive call (`path_enumeration.cpp`: a call to a function already on the
path continues in the state of its first occurrence), so all recursion levels share the states of the first one. The
explorer decides from the two call paths of a dependence whether a loop carries it (`__carried_frame_and_position`): a
write in an iteration of the caller and a read in an iteration of the callee therefore look like a dependence between
iterations of one loop execution, and the loop is rejected (uts: RAW on `parent`; test
`test/end_to_end/recursion_states`, `task_omp_uts`).

- [x] **Loop accounting of recursive instances** (runtime). `LoopManager::IsNewLoop` compared only the loop id, so the
      entry of a recursive instance of the loop on top counted as one more iteration of the caller's loop (maximum
      iterations per execution wrong, explorer: "fewer than two iterations"). It takes the function level now: an entry
      from a deeper level is a new loop. The landing pad of a function that catches an exception closes the loops and
      levels of the functions the exception left (otherwise the level stays too high and every later iteration starts a
      new loop; test `test/end_to_end/loop_accounting_exceptions`).
- [-] **States for the recursion levels: tried and dropped (2026-10-23).** A function may occur three times on a path
      (cyclic, the third level continues in the first). Reviewed critically; result:
      - the number of states grows by the product of (1 + s + s²) over the recursive functions of a chain (s = self
        calls): BOTS strassen 660 -> 2,086,892 (2.2 s and 1.1 GB to compile, 200 MB of state files, 700 MB to load the
        graph at start-up), sort 253 -> 64,641, floorplan 688 -> 57,472, uts 685 -> 24,891; state ids are int32 and
        packed into the upper half of the LID;
      - a bounded number of levels cannot be exact: carried-ness depends on the buckets of the frame where the two call
        paths diverge, which can lie arbitrarily far above both ends. With the wrap, a dependence between levels 3 and
        4 is compared as if both lay in the first frame; uts (5 levels) stays rejected. Saturation (the last level
        continues in itself) keeps the shallow levels exact but still rejects uts, and an explorer rule that ignores
        the evidence of the saturated frame would be needed;
      - `TaskGraph.__loop_context_at` assumes "a function occurs at most once on a callpath" and would have to select
        the copy by frame index.
      Open ideas: decide carried-ness in the runtime (an access timestamp per shadow entry, compared with the iteration
      start stamps of the loop stack: exact at any depth, costs memory); saturation plus the explorer rule.
- [x] **Warning for loops with recursive calls** (explorer). `identify_simple_doall_and_reduction` logs a warning once per
      loop whose body calls its own function (direct recursion, from `recursive_function_calls` of the CUs of the loop:
      the profiler lists a call to a recursive function as "<callee> <file>:<line>,"; the callee must be the function of
      the loop) and records a `recursion_in_loop` note in `pattern_decisions.json` (`notes` of the candidate: unlike
      reasons they do not decide the outcome and survive for accepted loops; the key is left out when there are none).
      `explain_parallelization` prints the notes. Open: mutual recursion (the loop calls a function that reaches the
      loop's function again) needs the call graph.
- [ ] **uts** stays rejected until one of these is done (see above); the xfail of `task_omp_uts` and
      `recursion_states::test_a_loop_is_not_rejected_for_the_reads_of_its_recursive_callee` document it.

### 3.4 Future work (profiler, found while reviewing 3.3)

- [ ] **Memory intrinsics are not instrumented.** `llvm.memset` / `memcpy` / `memmove` record no access (the pass has no
      handling for them), and `__dp_alloca` receives the address range of a stack object but does nothing
      (`memory/Scope.hpp` is dead code). Consequences: reads of elements a callee zeroed with `memset` look like reads of
      stale data of an earlier instance of the callee (stack reuse), i.e. spurious RAW; `memcpy` drops real RAWs (false
      negatives). Seen in nqueens (`memset(csols, ...)`, `memcpy(b, a, ...)`): with instrumented call paths per
      recursion level the loops at lines 26/48 were rejected for a RAW on `csols`; replacing the `memset` by a zeroing
      loop removed the rejection. Fix: instrument the intrinsics as range writes/reads; optionally let the alloca of a
      frame clear its shadow memory. Decided to leave this alone for now (2026-10-23).
- [ ] `LoopManager::CleanFunctionExit` does not update `max_iteration_count`, so loops left by `return` report a maximum
      of 0 (feeds the "fewer than two iterations" rejection).
- [ ] `LoopManager::IsSingleExit` ignores the function level (latent, no failing case found).
- [ ] Running with `DP_DEBUG=1` in `dp.conf` segfaults.
- [ ] `callpath_state_return_targets.txt` is written (31 MB for strassen) but never used by the runtime.
- [ ] `--enable-patterns doall` alone crashes the explorer (`'PatternStorage' object has no attribute 'reduction'`,
      `pattern_detection.py`); `doall,reduction` works.

### 3.5 Decisions of the maintainer on the data sharing work (2026-10-23)

Branch `improvement/task/data_sharing` (not merged yet), answers to its open questions:

- Loops with a reduction that call a hotspot function also yield loop tasks (one task per iteration, `reduction` filled
  in): desired, the implementation of the pragmas can use the information.
- WAW between adjacent tasks: they stay offered as parallel, reported as an output dependence. WAW does not prevent
  parallelization if the variable is privatized correctly, so the suggestion has to make the privatization visible
  (the data sharing of the group, `out` dependences in `task_dependences`).
- `last_private` as a hint on top of `shared` (OpenMP tasks have no lastprivate): acceptable, it conveys the
  information in an easily understandable way.
- Found by that work: groups are always pairs of tasks without a data edge between them, so RAW and WAR can never
  appear inside a group (they appear as the join before the dependent statement, `after_dependences`); the earlier note
  that "a dependence only shows for non-adjacent tasks of a group of three" is wrong. WAW is the only dependence that
  occurs inside a pair, since it registers no edge. Reductions across the tasks of a group are not reachable with real
  data (`sum += ...` in adjacent statements has an edge); the code path is covered by unit tests only.

### 3.6 Nested do-all loops: tasks and do-all patterns (2026-10-23)

Two contexts, two answers (maintainer):

- **Loop tasks** (a do-all loop whose body calls a hotspot function becomes one task per iteration): for nested do-all
  loops with the same statement the INNERMOST loop is reported. This matches omp-tasks (sparselu: the task sits in the
  inner loop with `firstprivate(kk, jj, ii)`) and the expectations of `task_omp_sparselu`; implemented on branch
  `improvement/task/spans_and_war` (not merged yet), nothing to change.
- **Do-all patterns** (nested do-all loops without tasks): the OUTERMOST loop is typically the best choice for
  parallelization, collapsing the nest is typically even better. The explorer finds collapsible nests
  (`pattern_detectors/loop_collapse_analysis.py`).

- [ ] Check that the do-all detection reports the outermost loop of a nest of independent loops, and the collapse where
      the loops are perfectly nested (not verified in this session).

### 3.7 Integration of the agent branches (2026-10-23)

Branch `integration/task_detection` merges `recursion_warning`, `spans_and_war`, `patch_generation`, `health_groups`,
`recursion_join`, `join_and_names` and `data_sharing` (all on top of `fix/profiler/recursion_states`). Full suites
(explorer, mcp_server, library, end-to-end, profiler, instrumentation): 1909 passed, 31 xfailed.

Where the branches met (commit "reconcile the merged task branches"):
- **Recursive tasks:** the join of the recursion branch (the function's own code counts as the task's work) and the
  names / `at_return` / callpath attribution of the join branch. For a task that reaches its own function the callpath
  attribution (`_belongs_to_task`) and `at_return` are not used: the states are cut at the recursive call, and stack
  memory left by the recursion looked like a read by unrelated code (nqueens: the second function's `csols`). The
  recursion item under "Join points" is done as an over-approximation (a join may be reported that is not needed).
- **Loop tasks:** the region covers the task statement, `loop_start_line` / `loop_end_line` hold the loop (the patch
  starts at the header). Cursor loops (`while (v) { f(v); v = v->next; }`, health) and reduction loops are loop tasks
  as well; the cursor stays firstprivate.
- New fields in `patterns.json`: `after_dependences[].at_return`, `reduction`, `last_private`, `loop_end_line`,
  dependence kind `WAW`; `pet.callpath_tree` (not stored).

Open questions of the agents, still undecided: the region of a group (wrap the first call in the caller, as omp-tasks,
instead of a parallel region per recursive function); `taskwait` or `depend` for dependences between tasks; whether
a group that cannot be placed keeps a comment-only patch; `variable = ""` for join entries without a name; the
name mapping of the join is a heuristic (no call arguments); a declaration as task line (fib: `int a = fib(n-1);`)
cannot be patched; sparselu: fwd and bdiv are one region in omp-tasks; the data sharing of `csols` / `b` in nqueens
(`&csols[i]` is only an address computation in the CU, the AST helper of the join branch could close it); the
sibling race on a parent's field in health (cut call paths).

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

- [~] **Fill `in_dep` / `out_dep` / `in_out_dep`** (`clauses_of_dependences`; `ParallelRegionInfo.task_dependences`
      carries variable and kind, RAW and WAR; WAW is not registered on contexts; the tool prints `(anti)`). Groups
      are built from tasks without a data edge between neighbours, so a dependence only shows for non-adjacent
      tasks of a group of three; untested with real data (unit tests only). Old note:
      Then the tool (`task_groups.dependences`) must be adapted: it prints the fields as
      `in x; out y; in/out z` without telling the kind of dependence. Per the agreed
      presentation, RAW is the main information and WAR/WAW are marked `(anti)` / `(output)`,
      which needs the kind per variable in the explorer's output (a new field or a tagged
      entry); add a test with real dependences (fib: none; take a case from `bots/omp-tasks`).

- [~] **Tests from `bots/omp-tasks`** (started): `pattern_detectors/test_new_task_detector.py`
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
      requested. Open: loops with some dependences between the iterations (`depend`), the join analysis (the
      tool always names a join after the loop).
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
      the line of the call). Open: tasks that reach their own function (recursion, e.g. the loop of fft: no join is
      reported, since the code around the recursive call cannot be told from it; needs the callpath state of the
      dependences), reads in the caller after the function returns, the variable names are those at the later access,
      and the group choice flakiness below.
- [x] **Data sharing.** Filled from the accesses, not the types (`classify_variable`): declared in the task and not
      needed after: private; global, written, or written by a sibling: shared; otherwise firstprivate. Loop tasks take the sharing of the do-all loop, plus what the code after the loop reads as shared. Open: reductions,
      last private, what pointers point to (side-effect export).
- [ ] **Enclosing loop.** Export the innermost enclosing loop (start line) of a region so
      that its hotspot can be matched; loops are not in the side-effect export.
- [ ] **Decision log.** Record task decisions (accepted and rejected groups) in
      `pattern_decisions.json` like doall and reduction do.
- [ ] **Side-effect export:** `static_callees` of `fib` is empty although it calls itself;
      check whether self recursion is excluded on purpose. A recursion flag per group
      (callee is the enclosing function) would let the output suggest a cut-off.
- [ ] **Patch generation for task patterns.** Fix it: the patches of `PARALLELREGION` and `TASK` entries are not
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
      - **Crash on loops with recursive calls** (health, floorplan, uts): `ValueError: Invalid iteration structure found at
        node: Start IT` in `TaskGraph.__assign_loop_contexts`, if an instance of such a loop runs zero times or loops are nested.
      - **Cost per recursive call site** (sort: 90 s guard in the test, strassen: memory limit of 4 GiB in the test):
        `ContextTaskGraph` construction grows about 9x per call site; seven self-calls of a function run out of memory in
        `__insert_data_dependencies_from_files`.
      - **Duplicates** (knapsack): the same region and tasks are reported once per recursion level (17 regions).
      - **Spans and joins** (nqueens, sparselu): the region and task spans include the header of the loop; the join and the
        sharing of recursive calls are empty (see recursion join above); spurious WAR on loop variables (`jj`, `ii`);
        tiny regions in initialisation loops (`genmat`).
      - Strassen, health, floorplan and the join/sharing expectations are guesses until the explorer gets that far.
- [ ] **Docs.** Update the documentation where necessary (`docs/tools/MCP_server.md`, the explorer docs and the
      description of the new `patterns.json` fields `task_dependences`, `after_dependences`, `shared`, `private`,
      `first_private`, `jumpInstructionIDs` in `Data.xml`) once the data flow work is finished.
- [ ] **Trivial groups.** Groups of unprofitable code (a few `sprintf` calls in the shared
      BOTS sources) are reported with the same weight as real ones.

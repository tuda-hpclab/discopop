<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

# Task suggestions — hand-over to a new session (2026-10-22)

Read `design/task_suggestions.md` (findings, todo checklists), `design/instruction_focus.md` (instruction IDs) and
`design/task_suggestions_resume.md` (decisions, BOTS setup) first. This file holds the state at the end of the session
that built the data-flow work, the omp-tasks tests and the first explorer fixes, and the next steps in order.

## 1. State of the repository

Repository `/home/lukas/git/discopop`. Nothing is pushed.

| Branch | Content |
|---|---|
| `improvement/mcp_server/interface` → `improvement/mcp_server/task_suggestions` → `improvement/profiler/instruction_ids` | PR chain (interface → task suggestions → instruction ids); not opened yet |
| `test/task_detection/omp_tasks_cases` (current, based on `improvement/profiler/instruction_ids`) | the omp-tasks end-to-end tests and one uncommitted explorer fix |

Last commits on `improvement/profiler/instruction_ids`, newest first: `bfcf8758` deterministic task detection,
`596bb922` pointer writes of callees, `f82361dd` / `d5b84890` join and sharing of loop tasks.
On the test branch: `a4900c13` the eight `test/end_to_end/task_omp_<app>` directories, `667e1606` design note.

**Uncommitted:** `explorer/discopop_explorer/classes/TaskGraph/TaskGraph.py`, in `__assign_loop_contexts`: a nested
`Start IT` of the same loop (an inlined recursive instance in the body) is counted like a nested end instead of
raising `ValueError: Invalid iteration structure found at node: Start IT ...`. Explorer and MCP tests pass (1049); the
end-to-end/profiler/instrumentation run exited 0 but its summary line was not read, so rerun it before committing.

## 2. What the omp-tasks tests show

`test/end_to_end/task_omp_<app>`: reduced C reproductions of nqueens, knapsack, health, floorplan, uts, sort, strassen
and sparselu; the omp-tasks version is the expectation; failures are `xfail(strict)` with a reason. Full run before the
fix: 4 passed, 42 xfailed (6 min 28 s with `-n 8`; sort needs about 90 s, strassen about 2 min). Findings, in order of
how much they block:

1. **Crash on loops with recursive calls** (health, floorplan, uts): fixed by the uncommitted change above. After it the
   explorer finishes on health (10 s) and uts; floorplan was not checked (its explorer run was killed).
2. **Duplicates per recursion level** (health: 594 task entries on about 12 distinct line ranges; knapsack: 17 identical
   regions). Cause: `identify_simple_tasking` emits one group per context instance, and the recursive inlining makes
   copies.
3. **Cost per recursive call site** (sort, strassen): `ContextTaskGraph` construction grows about 9× per call site;
   seven self-calls run out of memory (13 GB) in `TaskGraph.__insert_data_dependencies_from_files`. The sort test has a
   90 s guard, the strassen test a 4 GiB `RLIMIT_AS`.
4. **uts: no task at all.** The do-all detection rejects the loop (RAW on `parent` between iterations at line 28 in
   `pattern_decisions.json`). Suspected: the loop-iteration bookkeeping of the profiler mixes the iterations of the
   recursive instance with those of the caller (see `test/end_to_end/loopstate_positions`); not confirmed.
5. **Spans and sharing** (nqueens, sparselu): region and task spans include the loop header (26-32 where 29-32 is
   expected); empty joins and sharing for recursive calls; spurious WAR on loop variables (`jj`, `ii`); tiny regions in
   initialisation loops (`genmat`).

The health and floorplan expectations about joins and sharing, and all strassen expectations, are guesses until the
explorer gets that far; adjust them to the omp-tasks code, not to the explorer output.

## 3. Next steps, in order

1. **Floorplan check.** Build the profile (`test/end_to_end/pipeline.build_and_profile`) and run
   `discopop_explorer --enable-patterns task` in it with a time limit; floorplan was slow before (about 11 s) and may be
   much slower now.
2. **Update the three `xfail` reasons** (`task_omp_health`, `task_omp_floorplan`, `task_omp_uts`; they still say the
   explorer aborts) and add a non-xfail test per directory that the explorer finishes on the program. Check with
   `pytest --runxfail` what each test fails on now.
3. **Commit the crash fix** on the test branch (conventional commit, `Co-Authored-By: Claude Sonnet 5.5
   <noreply@anthropic.com>`), after the full suites pass.
4. **Deduplicate groups** in `identify_simple_tasking` (`pattern_detectors/new_task_detector.py`): emit a group once per
   (parent PET node, task line ranges, task instruction ids). Check fft (44 entries) and fib stay the same; knapsack
   should drop to one region; add a unit test.
5. Then, by value: the cost per recursive call site (3.), the do-all result for loops with recursion (4.), the span
   including the loop header (5.).

## 4. Todo list from `design/task_suggestions.md` (not started)

- Patch generation for task patterns (verify the patches of fib, fft and loop tasks, `PARALLELREGION` handling, the
  printed line).
- Docs (`docs/tools/MCP_server.md`, explorer docs, the new `patterns.json` fields `task_dependences`,
  `after_dependences`, `shared`, `private`, `first_private`, and `jumpInstructionIDs` in `Data.xml`).
- Step 1b leftovers (open items under "Join points"):
  1. tasks that reach their own function (recursion): no join is reported; needs the callpath state of the dependences,
     which the parser strips;
  2. reads in the caller after the function returns (a task writes through a pointer parameter or a global, the caller
     reads it): the join should be "before the function returns". A prototype was written and reverted: it takes the RAW
     dependences whose sink is outside the function and not in the task, as an `AfterDependence` with `line = None`,
     and the tool prints "complete before the function returns"; it found nothing on fib/fft/`ptr.c`, and gave
     `res RAW` on a program where `h(int *res)` writes through callees and `main` reads it;
  3. the variable names are those at the later access (a callee writing `*dst` shows as `res`).
- Reductions and lastprivate in the data sharing; WAW dependences; a real-data test for dependences between tasks.
- Enclosing loop export; decision log for tasks (`pattern_decisions.json`); unknown end line 262143; `static_callees`
  of a self-recursive function; trivial groups (a few `sprintf` calls); loops with `depend`.
- A test one level down (ContextTaskGraph simplification); a `--enable-patterns task` alone test.
- MCP server items: stale server output, `dp_common/` paths in the output, stale `get_project_status` after a manual
  run, GUI fallback default.
- Open the PR chain: interface → task_suggestions → instruction_ids (and decide where the test branch goes).

## 5. How to work

- Use `venv/bin/python`. Checks: `black -l 120`, `ruff`, `mypy --config-file=mypy.ini explorer mcp_server`, pytest.
  Explorer and MCP tests: `venv/bin/python -m pytest -n auto -q explorer mcp_server`. End-to-end:
  `PATH=$PWD/venv/bin:$PATH venv/bin/python -m pytest -n auto --dist loadgroup -q test/end_to_end test/profiler
  test/instrumentation` (needs `discopop_cc` on `PATH`; do not edit explorer code while it runs, the subprocesses read
  the working tree).
- Run a single explorer on a saved profile: `cd <dir>/.discopop && discopop_explorer --enable-patterns task`; write
  big outputs to a file, not to the terminal.
- The maintainer's directions still apply: instruction IDs stay behind the MCP server's abstract layer; old `Data.xml`
  files are not supported; omp-tasks is the ground truth for tests; failing new tests are acceptable (strict xfail,
  the maintainer decides later which move to the wip tests); do not push; use a new branch for new work.
- Delegation: the Qwen route in `~/.claude/CLAUDE.md` was not used. Four Sonnet agents wrote the omp-tasks tests; their
  reports (xfail reasons) are reflected in section 2 but were not re-verified one by one.

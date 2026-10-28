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
| `test/task_detection/omp_tasks_cases` (current, based on `improvement/profiler/instruction_ids`) | the omp-tasks end-to-end tests and the explorer crash fix |

Last commits on `improvement/profiler/instruction_ids`, newest first: `bfcf8758` deterministic task detection,
`596bb922` pointer writes of callees, `f82361dd` / `d5b84890` join and sharing of loop tasks.
On the test branch: `a4900c13` the eight `test/end_to_end/task_omp_<app>` directories, `667e1606` design note.

**Update (2026-10-22, later):** the crash fix is committed (`39af76fc`). The venv needed `requirements-dev.txt` and a
reinstall of `./profiler` (non-editable; the installed one predated the instruction IDs and the explorer failed with
`no such child: instructionIDs`). Steps 1-3 of section 3 are done; the xfail reasons of health, uts and floorplan are
current, health and uts have a passing "explorer finishes" test, floorplan a 120 s explorer guard (it does not finish).
The full suites were not rerun after the fix; the counts below are from before it.

## 2. What the omp-tasks tests show

`test/end_to_end/task_omp_<app>`: reduced C reproductions of nqueens, knapsack, health, floorplan, uts, sort, strassen
and sparselu; the omp-tasks version is the expectation; failures are `xfail(strict)` with a reason. Full run before the
fix: 4 passed, 42 xfailed (6 min 28 s with `-n 8`; sort needs about 90 s, strassen about 2 min). Findings, in order of
how much they block:

1. **Crash on loops with recursive calls** (health, floorplan, uts): fixed by `39af76fc`. After it the
   explorer finishes on health (11 s) and uts (4 s); floorplan does not finish within 400 s (ContextTaskGraph
   construction, 45142 nodes, slows to under 100 nodes/s).
2. **Duplicates per recursion level** (fixed on `improvement/explorer/task_dedup`; was: health: 594 task entries on about 12 distinct line ranges; knapsack: 17 identical
   regions). Cause: `identify_simple_tasking` emits one group per context instance, and the recursive inlining makes
   copies.
3. **Cost per recursive call site** (sort, strassen): `ContextTaskGraph` construction grows about 9× per call site;
   seven self-calls run out of memory (13 GB) in `TaskGraph.__insert_data_dependencies_from_files`. The sort test has a
   90 s guard, the strassen test a 4 GiB `RLIMIT_AS`.
4. **uts: no task at all** (analysed 2026-10-23, see `design/task_suggestions.md` 3.3: the cut call paths, not fixable with a bounded number of levels; open). The do-all detection rejects the loop (RAW on `parent` between iterations at line 28 in
   `pattern_decisions.json`). Suspected: the loop-iteration bookkeeping of the profiler mixes the iterations of the
   recursive instance with those of the caller (see `test/end_to_end/loopstate_positions`); not confirmed.
5. **Spans and sharing** (nqueens, sparselu): region and task spans include the loop header (26-32 where 29-32 is
   expected); empty joins and sharing for recursive calls; spurious WAR on loop variables (`jj`, `ii`); tiny regions in
   initialisation loops (`genmat`).

The health and floorplan expectations about joins and sharing, and all strassen expectations, are guesses until the
explorer gets that far; adjust them to the omp-tasks code, not to the explorer output.

## 3. Next steps, in order

1. ~~Floorplan check~~, 2. ~~xfail reasons and finishing tests~~, 3. ~~commit the crash fix~~: done (see the update above).
4. ~~Deduplicate groups~~: done on `improvement/explorer/task_dedup` (health 594 -> 18, knapsack one region; fft not rechecked).
5. Then, by value: the cost per recursive call site (3.; floorplan too), the do-all result for loops with recursion (4.), the span
   including the loop header (5.).

## 4. Todo list (state 2026-10-23, branch `integration/task_detection`, see `design/task_suggestions.md` 3.2 to 3.7)

Done and merged on `integration/task_detection`: patch generation for task groups, docs for the fields, joins of
recursive tasks and before the function returns, variable names in the function's scope, reductions / lastprivate /
WAW, spans of loop tasks, spurious WAR, health (cursor loops), the tests one level down and for `task` alone, the
warning and the note for loops with recursive calls.

Open (details in the design notes):
- uts and every loop with recursive calls: the call paths are cut at a recursive call (3.3); future profiler work: the
  memory intrinsics, the maximum of iterations after `return`, `IsSingleExit`, `DP_DEBUG`, the unused return targets
  file (3.4).
- Decisions of the maintainer still needed (3.7): the region of a group (wrap the first call), comment-only patches,
  `variable = ""`.
- Decided: `depend` for dependences between tasks, `taskwait` only when a following statement needs the results of
  the tasks (3.8); implemented on `improvement/patch/depend_clauses` (`312d4fe1`), not yet pushed.
- Sharing of `csols` / `b` (nqueens) and of the loop index (sparselu); sparselu fwd + bdiv as one region.
- Enclosing loop export; decision log for tasks (`pattern_decisions.json`); unknown end line 262143; `static_callees`
  of a self-recursive function; trivial groups (a few `sprintf` calls); loops with `depend`; mutual recursion for the
  warning; the outermost loop / collapse check for plain do-all (3.6).
- MCP server items (skipped): stale server output, `dp_common/` paths in the output, stale `get_project_status` after a
  manual run, GUI fallback default.
- Hotspot information for `task` / `parallel_region` patterns (needed by the autotuner; plan in 3.9): today such
  patterns are never classified YES/MAYBE/NO, because only loop hotspots contained in the CU lines are matched.
- Performance (parked): the cost per recursive call site, floorplan.
- Open the PR chain (interface -> task_suggestions -> instruction_ids ...) and decide where the branches go.

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

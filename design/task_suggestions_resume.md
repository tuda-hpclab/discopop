<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

# Task suggestions — notes for resuming in a later session

Written 2026-10-22 at the end of the planning session. Read `design/task_suggestions.md` first
(findings, output sketch, todo checklists); this file holds what it does not: decisions, the
test setup, the state of the working trees, and what was verified.

## Where we are

- Branch `improvement/mcp_server/task_suggestions` (based on `improvement/mcp_server/interface`).
  `design/task_suggestions.md` is committed; the core of the MCP tool part is implemented
  (`mcp_server/tools/task_groups.py`, see the checklist in the design file for what is open).
- The goal: `get_parallelization_suggestions` (`mcp_server/tools/get_parallelization_suggestions.py`)
  reports task parallelism as parallel region + task bodies + dependences between tasks, without
  ready-made pragmas, so that the agent decides on pragmas and positions.

## Decisions by the maintainer

- Output is text, in the style of the doall and reduction lines.
- Dependences: RAW is the main information; WAR and WAW are listed marked `(anti)` /
  `(output)`. The maintainer fills `in_dep`, `out_dep`, `in_out_dep` in the explorer by hand;
  the tool only prints what those fields hold.
- Adding fields to `TaskParallelismInfo` / `ParallelRegionInfo` is fine.
- Implausible groups are **flagged**, not dropped (the maintainer debugs them manually).
- The hotspot mapping is part of the plan; the maintainer was unsure how well regions map.
- Explorer improvements are separate work (section 3.2 of the design file).
- While developing, `.discopop` files may be read directly (the "never read .discopop" rule of
  the MCP server applies to using the server, not to developing it).
- All implementation goes on the branch above.

## Test projects (BOTS, repository `/home/lukas/git/bots`)

Both `serial/fib` (simple: one real group) and `serial/fft` were set up with DiscoPoP. Start
with fib. Neither the `bots` repository nor the setup files are committed; untracked there:
`serial/<app>/.discopop/`, `serial/<app>/dp_common/`, and the binary `serial/<app>/<app>`.

- **Compile script** (`.discopop/project/configs/compile.sh`), the Makefile needs `./configure`,
  and `main()` is in `../../common/bots_main.c`, outside the project root. DiscoPoP then fails
  with "'PEGraphX' object has no attribute 'main'". Workaround: stage the common sources:

      set -e
      mkdir -p dp_common
      cp ../../common/bots_main.c ../../common/bots_common.c ../../common/*.h dp_common/
      $CC $CFLAGS -Idp_common -I. \
        -DCDATE='"n/a"' -DCC='"cc"' -DLD='"cc"' -DCMESSAGE='""' -DLDFLAGS='""' -DCFLAGS='""' \
        dp_common/bots_main.c dp_common/bots_common.c <app>.c -lm -o <app>

  Paths in the output therefore read `dp_common/bots_main.c` (a staging artifact).
- **Configurations:** fib `small` = `./fib -n 15`, `medium` = `./fib -n 20`; fft `small` =
  `./fft -n 65536 -c`, `medium` = `./fft -n 262144 -c`. Base flags `-O0 -g`. The `-c` flag of fft
  prints `Verification = n/a` in the serial build.
- **Task detection is part of `gather_data` and of the explorer's default now** (`reduction,doall,task`,
  recorded as `enabled_patterns` in `patterns.json`); older notes below about running it by hand
  apply to results made before that. After `gather_data` run by hand, inside `<project>/.discopop`, with the venv on `PATH`
  (`/home/lukas/git/discopop/venv/bin`):

      discopop_explorer --enable-patterns task,doall,reduction
      discopop_patch_generator

  Then `get_parallelization_suggestions` lists the task groups. The explorer must be re-run
  after every `gather_data` that re-runs pattern detection.
- fft's `.discopop` holds the maintainer's own run (different settings, 26 groups, 30
  suggestions); fib's holds the run described above (3 groups).

## Verified, and not

Verified by reading data and code:
- Key and fields of `task` in `patterns.json` (fib and fft samples), the `+1` offset between
  `Hotspots.json` and the side-effect export, the 262143 sentinel, the function table in
  `side_effects.json.gz` (all 35 functions of fft, file id and lines).
- Why the type shows as `pattern`: `_PATTERN_TYPE_KEYS` and the `fact.get("type", "pattern")`
  fallback in `get_parallelization_suggestions.py`.

Not verified:
- Where the 262143 sentinel originates: found later, a decoded unset line ID of the profiler
  (2^18-1); see `design/instruction_focus.md`.
- What the patch generator makes of `PARALLELREGION` entries in the `task` list
  (`UnpackedSuggestion` has separate handling for `task` and `parallel_region`); only the
  pragma shown by the tool (`#pragma omp parallel`) was seen, not a patch.
- Whether the side-effect export excludes self recursion on purpose (`fib` has no callees).
- Why the printed line is off: assumed to be the first line of the patch's `@@` header
  (`_summarize_patch`), not tested on a task patch.
- How the maintainer's manual explorer run differs in settings from the commands above.

## Further todos not in the design file

- The staged `dp_common/` paths in the output (see above); decide whether to map them back to
  `common/` or leave them.
- `get_project_status` reported the hotspot and profiling data as stale after the maintainer's
  manual run (source timestamp newer than the profiling). Check whether the compile script's
  copy step into `dp_common/` is the cause; it would make every re-run look stale.

## Next step

Continue with the open items of section 3.1 of the design file, then the explorer (3.2). Run pytest, mypy, black and ruff
as in `CLAUDE.md`.

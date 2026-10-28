<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

# Instruction focus: CUs made of instruction IDs — Plan

Status: stages 1-3 done (2026-10-22). Branch `improvement/profiler/instruction_ids` (based on
`improvement/mcp_server/task_suggestions`).

Goal (maintainer): instruction IDs become the identity of what the analysis works with — CUs,
dependences, contexts, patterns — and are carried through the whole pipeline. Lines and columns
become a view derived from the IDs (`instructionID_to_lineID_mapping.txt`), used for output and
for matching data of other builds. The line focus is to be replaced by an instruction focus over
time. Old `Data.xml` files need not be supported.

## 1. Trigger: the CUs of BOTS fib

Lines 31/32 of `fib.c` are `x = fib(n - 1);` / `y = fib(n - 2);`. IR at -O0, per line:
`load n, sub, call fib, store` (instruction IDs 847-850 for line 31, 851-854 for line 32).

`createCUs.cpp` closes a CU right *before* a call if it has phase lines, so the tail of statement
N and the head of statement N+1 end up in one CU:

| CU | instructions (derived from the code) | span |
|---|---|---|
| 3:236 | load n(31) | 31-31 |
| 3:237 | call(31), store x(31), load n(32), sub(32) | 31-32 |
| 3:238 | call(32), store y(32) | 32-32 |

Calls are attached afterwards by searching the first CU of the block whose line *range* contains
the call's line, so call 31 lands on 3:236 and call 32 on 3:237 (matches `Data.xml`: one CU off).
The task detector's scopes (`[31]`, `[31, 32]`) follow from that; see
`design/task_suggestions.md` and the strict xfail in `test_new_task_detector.py`.
Verified with the instruction lists of stage 1 (fib, `Data.xml`): exactly as in the table.

## 2. What exists

- Every instruction gets a unique ID (metadata `dp.md.instr.id`, `instruction_id_assignment.cpp`),
  unique across modules; `instructionID_to_lineID_mapping.txt` maps it to `file:line:column`.
- Dynamic dependences are recorded per instruction ID (`602@475 NOM RAW 308@12|var`), with the
  callpath state after `@`.
- Calls in `Data.xml` carry their ID (`callInstId`).
- The explorer drops both: `parser.py` converts IDs to `file:line` and removes the state;
  `PEGraphX` maps a line to *all* CUs whose read/write phase lines contain it.
- Pass order (`runOnFunction.cpp`): CUs are built on the uninstrumented IR (stage 1), IDs are
  assigned while instrumenting (stage 2), `Data.xml` is written after that (stage 3), the hybrid
  analysis erases only inserted callbacks (stage 4). So `Instruction*` kept per CU in stage 1 can
  be written as IDs in stage 3.

## 2a. Findings of stage 1 (fib, 220 CUs)

The lines derived from the instruction lists differ from `instructionLines` for 96 CUs, for two
reasons, both in the line bookkeeping of `createCUs.cpp`:

- **The line of a call is counted in the CU before the call** (95 CUs, e.g. `1:2`): the line is
  inserted into the current CU before the split, the call itself starts the new CU. The old CU
  claims a line it has no instruction of; the new one lacks the line of its own call. This is
  also why calls are attributed one CU off.
- **The cautious-property split erases a whole line** (`3:238`): it removes the line of the
  moved load from the old CU, although another instruction of that line (`load x`, line 34)
  stays there.

The instruction lists are therefore the reference, not `instructionLines`. Stage 1 places a call
in the CU the split starts (where it belongs by the split), and the moved load in the new CU.

Other findings:
- Static dependences are instruction-ID based too (`113 NOM WAR 111|i`).
- Every instruction of an instrumented function gets an ID (`RunOnBasicBlock`), those without
  position map to `*`.
- The TaskGraph warns "TODO: update available data to use instructionIDs instead of lineIDs as the
  default." (`__insert_data_dependencies_from_files`): the same direction, planned before.
- `262143` / `16383` is a decoded unset line ID (2^18-1, 2^14-1); dummy nodes of called
  functions carry it as `startsAtLine` (`16383:262143`).
- The fixtures in `explorer/test/state_assignment` were stale (profiler output changed since):
  regenerated; `trycatch` now also records the WAR of `g_caught += 1` (load 98 -> store 100), so
  7 record ends at cut lines instead of 6. Checked that the profiler without the stage-1 change
  gives the same dependences (up to memory region ids).

## 3. Stages

1. **Additive — done.** `CU` holds its `llvm::Instruction*` in program order; `Data.xml` gets
   `<instructionIDs count="n">id,...</instructionIDs>` per CU node. The explorer requires them
   (`parse_cu` rejects a `Data.xml` without them) and stores them on `CUNode.instruction_ids`;
   `Dependency` has `source/sink_instruction_id` and `source/sink_state_id`, set by the PET parser
   and by the TaskGraph. No change in behaviour (end-to-end, profiler, instrumentation, explorer
   and pass unit tests pass). The derived lines do *not* equal `instructionLines`, see 2a.
2. **Exact mapping — done.** Call → CU: the call goes to the CU that holds its instruction
   (`createCUs.cpp`, no line-range search). Dependence → CU: `parser.instructionToCUIdMap`
   (instruction id → CU) is used by `PEGraphX`; lines remain only as fallback for an end without
   an id or an id no CU holds. On fib the calls 849/853 now sit in 3:237/3:238 (one CU off before).
   The line maps have no other consumer (GUI, optimizer: checked).
3. **Split position — done.** A call's statement is not torn apart: the head (the trailing
   instructions of the CU that evaluate the call's operands, after the last store, call or
   terminator) moves into the CU of the call, or, if the head is the whole CU, the call joins it;
   the CU ends with the statement of its call (the next instruction on another line starts a new
   CU). `account`/`rebuild` in `createCUs.cpp` derive lines, phases, sizes and counts from the
   instruction list, so a moved head or a cautious-property split leaves no stale lines (2a: both
   findings are gone). The fib xfail passes: the real run gives the tasks (31,31) and (32,32).
   Arguments on continuation lines (later lines than the call, e.g. `fft_twiddle_gen`) belong to the head too; before,
   the call was split from them and fft got three bogus task entries (84 → 87). Not done: CUs of statements without a call still end where they did (phase/scope/cautious
   splits); the incremental data of the scope split is not rebuilt. fft: still 4 doall (incl.
   `fft_aux`, line 2951).
4. **Migration.** `instruction_scope` beside `get_code_scope` in the task graph contexts;
   instruction IDs of loop bodies and tasks in `patterns.json` (added beside existing fields);
   explorer queries move module by module (explorer: 138 uses of `LineID` in 27 files, 236 of
   `start_line`/`end_line`; library about 130). The MCP server stays line-based (presentation).

Stage 4 progress: `Context.get_instruction_scope` (done); `instruction_ids` on TASK and
PARALLELREGION entries of `patterns.json` (done; fib: task 31 = 847-850, task 32 = 851-854);
`instruction_ids` of do-all and reduction (done: the instructions of the loop context, as the pattern node is only the header CU of the loop);
TaskGraph: dependence ends are looked up by instruction id first (exact CU/context),
lines only for ends no CU holds (done; no change on the fixtures, fib, fft); open: the other line queries
module by module (inventory: `LineID` 139 uses in 206 files; most in `TaskGraph.py` 19, `GPULoop.py` 13, `Context.py` 10,
the do-all/reduction/task detectors 7-9 each, `Node.py` 8). The line view: `PEGraphX.instruction_lines` (from
`instructionID_to_lineID_mapping.txt`) and `get_line_ids_of_instructions`; `affected_line_ids` of do-all and reduction
are derived from the pattern's instructions (lines of called functions in the body included, comment lines not).
The task detector takes the spans of the tasks and of the parent from the lines of their instructions (the line range of
the nodes only for a context that holds no instruction); fft: same 84 task entries and spans as before. The other
`start_position()` uses in the detectors are node identities that key line-based data (loop data, reduction variables)
and stay. `Data.xml` lists the jumps of a CU (`jumpInstructionIDs`: br, switch, ret, unreachable; optional for the explorer);
the lines whose instructions are all jumps (`PEGraphX.jump_only_lines`) are left out of task spans (the closing brace
of a loop body carries the back-edge). The MCP server does not show instruction ids:
they are too detailed for it and stay behind a more abstract layer (maintainer).

Each stage gets its own tests and commit.

## 4. Caveats

- **IDs are valid within one build only** (a counter over the compiled modules). Anything compared
  across builds stays on lines/columns: `Hotspots.json` (separate instrumentation build), saved
  GUI suggestions and patches, comparisons between runs.
- **Instructions without debug location** (line 0, e.g. some phis) and instructions inserted by
  instrumentation: need a rule (keep in their CU, contribute no position).
- **Columns are expression positions, not statement extents** (`store x` has the column of `=`);
  statement extents for task bodies come from the AST (`ast_dump.json`).
- **Optimized builds:** the 1:1 relation of IR instructions to source holds at -O0 only.

## 5. Open checks

- [x] Every relevant instruction gets an ID (all of an instrumented function, see 2a).
- [x] Format of the static dependences of the hybrid analysis: instruction IDs.
- [x] Other consumers of the line → CU mapping: only `parser.py`, `PEGraphX` and one test.
- [x] Profiler rebuild and reinstall (`pip install ./profiler`, ~1 min), pass unit tests
      (`DiscoPoP_Pass_UT`), profiler/instrumentation tests.

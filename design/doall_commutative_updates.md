<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

# Doall loops made parallel by atomic updates

Status: phase 1 done; plan revised after review (2026-11-04). Branch `feature/doall-commutative-updates` (based on `feature/analysis-record`).

## Motivation

The doall/reduction detector (`explorer/discopop_explorer/pattern_detectors/new_do_all_detector.py`,
`identify_simple_doall_and_reduction`) rejects a loop as soon as it finds one dynamic loop-carried
dependency. A large class of such loops is nevertheless parallel: those whose only carried
dependencies are *commutative read-modify-write updates* of shared memory with an indirect index —
finite-element assembly, histograms, scatter-adds:

| Benchmark | Loop | Blocking update |
|---|---|---|
| miniFE | `perform_element_loop.hpp:80-87` | `row_coefs[loc-row_indices] += …` (`SparseMatrix_functions.hpp:157`), `vec_coefs[idx] += …` (`Vector_functions.hpp:104`), both in callees |
| LULESH | `lulesh.cc:520-558` (IntegrateStressForElems) | `domain.fx(gnode) += fx_local[lnode]` (+ fy, fz) |
| LULESH | `lulesh.cc:779-961` (hourglass forces) | `domain.fx(n0si2) += hgfx[0]` … 24 statements |
| LULESH init | `lulesh-init.cc:159-178`, `494-497` | `nodalMass(idx) += …`, `regElemSize(r)++` |
| rodinia kmeans | `kmeans_clustering.c:170-172` | `new_centers_len[index]++`, `new_centers[index][j] += …` |
| NPB IS | `is.cpp:585/630/648` | `work_buff[key_array[i] >> shift]++` |

Making each such statement `#pragma omp atomic` makes the loop a valid doall. The profiler's
reduction detection cannot find these: it scans only the loop's own basic blocks (callees are
opaque), needs the key to resolve to one alloca/global, and has no notion of indirect indices.

The decision log of the same benchmarks also shows what must **not** be accepted, though it looks
the same in the dependency data (a RAW dependency from a line to itself):

- prefix sums: `row_offset_ptr[i+1] += row_offset_ptr[i]` (miniFE `generate_matrix_structure.hpp:139`),
  `costDenominator += …; regBinEnd[i] = costDenominator;` (LULESH `lulesh-init.cc:438-439`);
- a captured counter used as an index: `regndx = regElemSize(r)++` (`lulesh-init.cc:506`) —
  race-free under `atomic capture`, but the result is permuted;
- order-dependent I/O counters, induction offsets (`gv_offset += …`).

Conversely, "source line == sink line" is not necessary: LULESH's hourglass loop is recorded with
a dependency `945 -> 929`, two *different* statements both doing `domain.fx(…) += …`.

## The criterion (per group of update instructions, not per variable name)

Revised after review. The first version identified a location `V` by `memory_region` or
`var_name`, which does not work:

- `memory_region` is the address of the interned *name string* (one per name and translation
  unit), not an allocation;
- a dependency carries only the **sink's** name, and the same memory appears under different
  names (`coefs`, `coefs42`, `Acoefs` at `SparseMatrix_functions.hpp:426/475/523`; `vec_coefs`
  is recorded as `call`).

What does work is the **column**. The profiler reports the load and the store of a read-modify-write
`x op= e` at the column of the operator itself (`instructionID_to_lineID_mapping.txt` is
`id file:line:col`; miniFE `SparseMatrix_functions.hpp:157:34` and `Vector_functions.hpp:104:20`
are the `+=` columns), while every other access of the statement has its own column. Every
dependency carries the instruction ids of both ends (`source_/sink_instruction_id`), so it can be
tied to the operator of one specific update statement without looking at any name.

Definitions, for a loop `L`:

- An **update site** is an AST statement `lhs op= e`, `lhs++`, `++lhs`, `lhs--` or `--lhs` with
  `op` in `+ - * & | ^`, of builtin arithmetic (for `++`/`--`) or scalar type, that is an expression
  statement (its value is not used: not `y = h[k]++`), that starts its line and is alone on it (the
  pragma has to precede exactly this statement), and whose operator location is `file:line:col`.
  Templates appear once per instantiation in the AST: sites are deduplicated by source range, and
  the instantiations must agree (same operator, builtin types).
- An instruction **is at** a site when its `file:line:col` is the site's operator location.
- `D(L)`: the PET DATA edges (any type, WAR included, carried or not) whose both ends lie in CUs of
  `L` or of functions called from `L` (`subtree_of_type(..., ignore_called_functions=False)`).
  Taken from the PET, not the task graph: the task graph drops same-iteration dependencies
  without a carried loop (`TaskGraph.py` ~4787), and `intra_iteration` is never set in the current
  profiler format, so the task graph cannot answer "is `V` read anywhere else in the iteration".
  Ends outside `L` are irrelevant: what happens before or after the parallel loop is not
  reordered.

A dynamic carried blocker `b` of `L` is **fixable** if the closure `S(b)` of update sites, built as
follows, exists:

1. both ends of `b` are at update sites; these are in `S`;
2. for every edge of `D(L)` with one end at a site in `S`, the other end is at an update site too,
   which joins `S` (repeat until nothing changes);
3. all sites in `S` have the same operator class: `+ - ++ --`, or `*`, or one bitwise operator;
4. statically, no reference to the LHS base declaration of a site of `S` occurs in its RHS `e`
   (catches the prefix sum even where the profile did not happen to show the RHS read), and the
   LHS is not the loop variable.

The loop is accepted as doall-with-atomics when every dynamic blocker is fixable; the atomics are
the union of the closures. Any other blocker (a static dependency that cannot be privatized, an
end at a non-site column, an unresolved instruction id, a missing AST) keeps the loop rejected.
Unknown means rejected.

Why this rejects what it must (all checked against the miniFE profile or to be checked):

- prefix sum `row_offset_ptr[i+1] += row_offset_ptr[i]` (`generate_matrix_structure.hpp:139`,
  tab-indented): RAW `9:139:24 -> 9:139:27`, the second end is the RHS read at column 27, not the
  operator column 24 → step 1 fails;
- `costDenominator += …; regBinEnd[i] = costDenominator;` (LULESH `lulesh-init.cc:438-439`): the
  read on line 439 is an edge of `D(L)` from the site to a non-site → step 2 fails;
- `regndx = regElemSize(r)++` (`lulesh-init.cc:506`): the value is used, not a site → step 1 fails;
- mixing `+=` and `*=` on one array → step 3.

And accepts what it should: the hourglass dependency `945 -> 929` connects two different
`domain.fx(…) +=` statements, both sites; the closure contains both.

Remaining coverage caveat, as for every doall: an access never observed during profiling is not
protected. The pragma protects a statement, not an address, so an input with other indices is still
correct as long as no *other* statement touches the same memory unobserved.

## Phases

### Phase 1 — collect all blocking dependencies per loop (done, a493eca4)

- Every distinct dynamic blocker is recorded as a `LOOP_CARRIED_DEPENDENCY` reason, across every
  task-graph copy of the loop: a copy of an already rejected loop is rescanned (the dependency
  scan only, the carried index once per PET loop, no clause classification).
- Detection result unchanged: miniFE 116/116 patterns, hotspot 4/4; reasons 61→119 and 6→46;
  runtime unchanged (miniFE ~74 s → ~71 s). LULESH could not be measured: its profile is in an
  old format and has to be re-profiled.
- `explain_parallelization` groups the dependencies of one variable into one line and cuts the
  locations after 5 instead of truncating reasons.

### Phase 2 — classify the blockers

No new suggestions; the decision log and the explanation become precise.

- Keep the column: the instruction mapping (`TaskGraph.py` ~4408/4859, `parser.py` ~145) parses
  `file:line:col` and drops `col`. Keep an `instruction id -> (file_id, line, col)` map on the PET
  (one int tuple per instruction).
- AST: `ASTQueries.update_sites(file_id, line)` → the update sites on that line with operator
  location, operator class, LHS base declaration id, whether the RHS references it, whether the
  statement is alone on its line and an expression statement; deduplicated over template
  instantiations. Wrapped by `ASTPatternDetectionHelper`.
- New module `pattern_detectors/commutative_updates.py`: `classify_blockers(loop, blockers, pet,
  data_edge_index, sites) -> Dict[DependencyRecord, Classification]`, where a classification is
  either `fixable(closure: frozenset of sites, operator class)` or `not_fixable(why)`, with `why`
  one of a small fixed set (`end_not_at_update`, `read_elsewhere: <line:col>`, `mixed_operators`,
  `rhs_references_lhs`, `value_used`, `no_ast`, `unresolved_instruction`). Pure function; the
  edges of `D(L)` are collected once per PET loop and cached (copies share them).
- Called from the detector only for loops in `dependency_prevented_loops`, after the scan of all
  copies. The classification is stored in the reason's `details`; `explain_parallelization` says
  "would be parallel with `#pragma omp atomic` at SparseMatrix_functions.hpp:157, Vector_functions.hpp:104"
  or, per variable group, why not.
- Validation: miniFE decision log — element loop fixable with both sites; the prefix sum
  `generate_matrix_structure.hpp:139` not fixable (`end_not_at_update`).

Checked before implementing (2026-11-04, a small `h[idx[i]]++` / `++h[…]` / `h[…]--` / `acc[k] += v`
in a callee, profiled with `discopop_cxx`, and the miniFE profile):

- Every profiled dependency is its own PET edge with both instruction ids (`PEGraphX` is a
  `MultiDiGraph`, one edge per `DependenceItem`, nothing merged by line).
- The RMW load and store sit at the operator column for all forms: postfix `++` `11:18`, prefix
  `++` `12:9`, postfix `--` `13:29`, `+=` `6:12`. The three `h` statements form one closure; their
  other ends (`17:38` in a later sum loop, `printf`) lie outside the loop. miniFE: the other ends of
  `157:34` and `104:20` are all in functions run outside the element loop (MatrixInitOp, the
  Vector constructor, `zero_row_and_put_1_on_diagonal`, `matvec`), so scoping to `D(L)` removes them.
- Clang's JSON gives expressions no `loc`, only a `range`. The operator column therefore is: prefix
  unary `range.begin.col`; postfix unary `range.end.col` (the last token is the operator);
  `op=` strictly between the LHS's `range.end.col` and the RHS's `range.begin.col`. Only sites whose
  range lies on one line are accepted (clang omits `line` in range ends when unchanged, and a
  multi-line update is rare).

### Phase 3 — accept loops whose blockers are all fixable

- **Opt-in by its own explorer flag**, `--atomic-updates` (default off), not a pattern type:
  `--enable-patterns '*'` selects every pattern type, so a new type would be enabled silently by
  every caller passing `*`. The flag is recorded in the AnalysisRecord's `pattern_detection`
  parameters (so `gather_data` does not reuse a result computed without it), and passed through
  by the ProjectManager/MCP only when asked for. Off by default because results stop being
  bitwise reproducible (atomic `+=` reorders a floating-point sum) and profitability is unproven.
- In the detector: with the flag, a loop whose dynamic blockers are all fixable is not added to
  `prevented_loops`; it goes the normal path (clause classification, static second chance,
  duplicate checks). The decision is per PET loop, taken after every copy was scanned, so all
  copies are accepted or rejected together.
- Static blockers on a site's variable in the second-chance path still reject (no change).
- The pattern stays `DoAllInfo`/`ReductionInfo` with a new field `atomic_updates:
  List[{"file_id", "line", "column", "operation", "variable"}]`, empty for every existing pattern
  and omitted from `patterns.json` when empty, so existing outputs stay byte-identical.
- Clauses: a site's variable is removed from `private`/`firstprivate`/`lastprivate`; no `shared(V)`
  is emitted, since `V` may be a name not in scope at the loop (callee locals, `domain.fx(n)`), and
  shared is the default anyway.
- Consumers of `DoAllInfo` that would silently drop the atomics: loop tasking, the GPU patterns,
  geometric decomposition and loop collapse. First version: they skip patterns with non-empty
  `atomic_updates` (collapse: never collapses across such a loop). Union for collapse later.

### Phase 4 — fix strategy: emitting the pragmas

- `UnpackedSuggestion.__get_do_all_and_reduction_pragmas` emits one
  `Pragma("#pragma omp atomic", file_id, line, line, BEFORE_START)` per atomic update besides the
  `parallel for`. `CodeGenerator._insert_pragmas` routes pragmas by file; the patch generator
  writes one `.patch` per file; the applicator is all-or-nothing per suggestion — also for the
  comment fallback (no partial "commented out" variant of a suggestion with atomics).
- Two suggestions adding an atomic to the same statement (nested loops, two loops calling the same
  `sum_into_row`): deduplicate at patch time (the applicator checks whether the line above already
  holds the identical pragma) rather than exclusion, since `build_exclusion_map` is only used by
  auto-tuning algorithm 6 and every algorithm has to be safe.
- MCP `get_parallelization_suggestions`: one entry per suggestion, not per patch file; the atomics
  are listed as part of the loop's entry and marked as required ("plus `#pragma omp atomic` at …,
  required").
- `domain.fx(n) += v` (a member call returning `Real_t&`) is a valid `atomic update` lvalue;
  check in an end-to-end test, and check the LULESH column/naming after re-profiling.

### Phase 5 (later, optional) — further fix strategies

- **Array-section reduction** `reduction(+:arr[:n])` when `V` is visible at the loop, small and of
  known extent (kmeans centers, IS buckets): often faster than atomics; needs the extent from the
  AST/type. Offer as an alternative suggestion and let the auto-tuner choose.
- **Critical sections** for multi-statement commutative updates — needs a stronger commutativity
  argument than the per-statement one above; not planned yet.
- Conditional max/min (`if (m < x) m = x`, LULESH `lulesh-util.cc:206`) is a separate gap in the
  reduction detection, not part of this work.

## Tests

- Unit: phase 1 (done); phase 2 classifier truth table on fixture graphs with a stub site table
  (scatter-add through a callee, two statements forming one closure, prefix sum, read elsewhere,
  mixed operators, value used, missing AST, unresolved instruction id); AST queries on small JSON
  ASTs in `testdata/` (templates, a statement not alone on its line).
- End-to-end cases under `test/end_to_end/cases/atomic/`: positive — histogram `h[idx[i]]++`,
  scatter-add through a callee, two statements on one array; negative — prefix sum, counter read
  after the update, `y = h[k]++`. With and without `--atomic-updates`.
- Regression: miniFE, hotspot and (re-profiled) LULESH — identical `patterns.json` without the
  flag; the loops in the table become suggestions with it; then a harness run: compile, validate,
  speedup.

## Open points

- The column rule rests on the debug locations clang gives the RMW load/store at `-O0` (the
  profiling build); confirmed for `op=`, prefix and postfix `++`/`--`.
- A site in a callee called from inside and outside `L`: PET edges are context-insensitive, so
  `D(L)` also contains edges from other call contexts. That only adds edges, i.e. can only reject
  more — conservative.

## Review of phase 2 (2026-11-04) and what followed

An Opus review profiled small counterexamples against c4cc4d0b. Fixed afterwards:

- **Hidden reads.** The profiler keeps one last reader per address. Before an update's store, its own
  RMW load is that reader, so a read of the address earlier in the loop (`out[i] = g[i]; g[i/2]++;`)
  is never an end of any dependency. Such a loop was classified fixable and races. This is a profiler
  limitation; the principled fix is to keep the readers since the last write. Stopgap in the classifier:
  the variable an update reaches its memory through must not be named anywhere else in the loop or its
  callees (`referenced_elsewhere`). Aliases under other names are not covered.
- **Indirect calls.** A function called through a pointer or a virtual method has no CALLSNODE edge,
  so its accesses are not in `D(L)`. Any such call in the loop or its callees now rejects the loop
  (`indirect_call`).
- An edge with an unknown end fails closed (`unresolved_instruction`). A template instantiated with
  a class type (an overloaded operator) is `instantiations_differ`. Locations are deterministic. The
  per-loop caches are dropped after the loop is classified.
- `explain_parallelization` no longer claims that the atomics make a rejected loop parallel. It names
  them as what would make the blocking dependencies safe.

Not fixed here, because it is pre-existing and affects plain doall in the same way: dependencies between
iterations of type WAR are skipped as privatizable (`new_do_all_detector.py`, "WAR dependencies between
iterations are non-critical"), but nothing checks that the variable is then privatized. So
`o[i] = q[i+1]; q[i] = 0;` is suggested as doall without clauses, and with `--atomic-updates` a loop
like `ob[i] = qb[i+1]; qb[i] = 0; hb[idx[i]]++;` is accepted. A hidden read can also make a plain doall
wrong (`o[i] = q[i+1]; q[i]++;`).

## Follow-ups after the review (plan of 2026-11-04)

Status markers: `[ ]` open, `[x]` done (with commit). Resume from the first open item.

### A. Shared atomics when suggestions are combined (PatchApplicator) `[x]` a58e0928

Two suggestions can insert `#pragma omp atomic update` before the same statement (miniFE: the
element loop and the loop in `sum_into_row`, which it calls). Every patch is a diff against the
original sources, so applying both inserts the pragma twice and the build fails. The auto-tuner
loses every combination of the two, and a search that picks the inner loop first can never add the
outer one.

Fix in the applicator, without changing the patch layout (many tools list `patch_generator/`):
- An *atomic line* of a patch is an added line whose text is exactly `#pragma omp atomic update`
  (the commented `//<DiscoPoP-IGNORED>` fallback is not one). Its *site* is (file id, line number in
  the original file of the line after it), read from the hunk header. All patches share that
  coordinate system, so the key is the same across suggestions.
- Apply S: an atomic line whose site is also in a suggestion already applied becomes a context line
  (the pragma is checked to be there, and left alone). The filtered patch is written to a temp file.
- Roll back S: the original patch, filtered against the suggestions that stay applied. So the pragma
  is removed by whichever sharing suggestion is rolled back last, in any order.
- The filter is a pure function (patch text, set of sites taken) -> patch text, unit tested; plus an
  end-to-end test with two suggestions in both apply and rollback orders.
- Traps: the hunk header's old count grows by one per converted line; a hunk whose only change was
  the atomic is dropped, and a file patch left without hunks is skipped (success, no `patch` call).
  The pragma is matched with whitespace stripped (PatchRepair may reindent).
- First check that every tool combining suggestions goes through `apply_patches`/`rollback_patches`
  (auto-tuner, PatchRepair, ProjectManager services, ParallelRegionMerger); one that runs `patch`
  itself needs the same filter.

### B. `--atomic-updates` beyond the command line `[x]` 012ef49d, 8543a1d6

- MCP `gather_data`: argument `atomic_updates` (default false) adds the flag. Skipping pattern
  detection requires the recorded options to equal the requested ones (today: any option means
  "not current"), so switching it on or off reruns the explorer. The tool text says it is
  experimental.
- ProjectManager: `ExplorerRequest.atomic_updates`, `explorer_command`, a checkbox in the Tk mixin
  (subprocess and in-process paths) and the Qt pattern detection panel. (Sonnet helper, own
  worktree, reviewed by me.)
- Every reader of the recorded explorer options (`get_project_status`, `analysis_status`, ...)
  must agree with `gather_data` on what counts as current. The default stays false, since the
  harness's `--llm-discopop-prep` relies on the explorer defaults.
- Not in this batch: a harness explorer variant `atomic_updates` (other repo); offer it.

### C. Brace-less loop bodies as update sites `[x]` (commit below; else branches stay rejected: the AST has no position for `else`)

`for (...)\n  h[k]++;` is rejected (`not_a_statement`), so the histogram shape is missed. Accept an
update that is the *body* (not the condition or increment) of `for`/range-for/`while`/`do`, or a
branch of `if`, when it is alone on its line. First check that clang accepts
`for (...)\n#pragma omp atomic update\n  h[k]++;` (an atomic construct is a statement). A one-line
`for (...) h[k]++;` stays rejected (the pragma needs a line of its own), and so do `else h[k]++;`
and `do h[k]++; while (...)` on one line. The body is identified by position (clang's JSON `ForStmt`
has `{}` placeholders; the body is the last child), with negative tests for the increment and the
condition.

### D. LULESH `[x]` (no code change)

Result (scratch copy, `-s 5`, `--enable-patterns doall,reduction --atomic-updates`): no loop gets
atomics. The two force loops are rejected only by `referenced_elsewhere`: IntegrateStressForElems
520-558 (3 blockers, other reference `domain.nodelist(k)` at 522) and its inner node loop 551-556,
and the hourglass loop 779-961 (51 blockers, all `referenced_elsewhere`, other reference
`domain.nodelist(i2)` at 788). So a refinement would make the hourglass loop fixable. It is not a
matter of member names alone: `domain.fx(n)` and `domain.nodelist(k)` are method calls, so a sound
refinement has to show that no other method reached through `domain` in the loop touches the
member `fx` returns (`m_fx`), transitively, since the profiler may hide those reads too. Not done:
offered to the user.

Also found (pre-existing, not this branch): with the default patterns the explorer crashes on
LULESH in the task detector, `task_dataflow._sharing`: `sorted(variables.items())` with a None
name (TypeError: '<' not supported between 'str' and 'NoneType').

Original plan for D:

Re-profile a scratch copy of LULESH, never inside the harness's `benchmarks/` (the ProjectManager
rewrites tracked settings files there). Time-boxed. The profiling data on disk is in the old format.
Re-profile it and run the explorer with the
flag. Expected: the force accumulation `domain.fx(n) += ...` is rejected as `referenced_elsewhere`,
because the check is name-based and `domain` is used everywhere. If so, decide whether a refinement
by member (`fx`) is sound enough to do: it needs its own argument and an Opus review.

### E. Review `[x]` 43c9f65e

Opus review of A-D (code, not my conclusions). Five findings, all fixed in 43c9f65e; the reviewer's
reproducers and 40 seeds of their fuzzer (4 of which failed before) are clean:
1. a context line made of a shared atomic could unbalance a hunk's context, which GNU patch rejects
   away from the file's start/end; it then left the other hunks (the loop's `parallel for`) in place
   while the suggestion counted as not applied - a loop parallel without its atomic. Now: balanced
   hunks, a dry run of every file of a suggestion first, a failed file restored from its copy;
2. an atomic followed by a changed line (a rewritten update) got the next statement as its site;
3. the commented atomics of the CodeGenerator fallback took the line of another suggestion's atomic;
4. `str.splitlines` also splits at form feeds;
5. a `)` without an AST node before a brace-less body: now only whitespace may precede a site.
Also found and fixed on the way: AST paths beginning with `../` matched no FileMapping entry
(104fe204), so every AST query for miniFE's `utils/` headers found nothing.

### F. Next: soundness of plain doall (after A-E) `[ ]`

Pre-existing, affects every doall suggestion, so a separate change with its own plan:
1. A carried WAR dependency is skipped as "privatizable" without checking that the variable then is
   private. Accept it only if the variable ends up in a private/firstprivate/lastprivate clause of
   the suggestion or is declared inside the loop; otherwise it blocks, with a reason. Only sound for
   scalars: for a pointer or array base (`q` in `o[i] = q[i+1]; q[i] = 0;`) a private copy is of
   the pointer, not the data, so such a WAR always blocks. Measure how
   many current suggestions this removes (miniFE, the trivial suite, polybench, rodinia).
   Status: implemented on branch `feature/doall-war-soundness` (see its commit). The rule as built
   (replacing the plan below, whose "not visible at the loop" rule does not work: the visibility query
   knows only the function's own locals, not globals, parameters or members):
   - harmless if the variable gets a copy per thread (a clause, a reduction, a loop variable) and the
     access is to its own storage (not `GEPRESULT_`);
   - or proven at the *sink* (the profiler names a dependency after the access that completes it,
     `AddDep(..., access.var, ...)` in `profiler/rtlib/dependency_analysis.cpp`): the name is an
     automatic variable there (`ASTUtils/LocalStorage.py`: resolved by scope, no static variable of
     that name a bare name could mean), of a callee or declared in the loop body, and an element
     access only through an array or an object by value, a direct one not through a reference;
   - or, with atomic updates, between two update sites the pattern makes atomic.
   Measured: the races of the test programs (`scratchpad/war`, `war2`: shared array, pointer
   parameter of a callee, pointer declared in the body) are rejected, the per-iteration arrays
   accepted. False rejections that remain, all because the profiler does not say which object or
   which execution of the loop a dependency belongs to: miniFE 12:462 (a body-local pointer written
   through a reference parameter), the miniFE element loop with `--atomic-updates` (named `this1`, by
   the ElemData constructor), LULESH 1004/1495 (array parameters, i.e. pointers), LULESH
   2003/2041/2053/2211/2348 (temporary heap arrays reused from call to call, reported as carried).
   Open: the user decides between taking that loss, recording the WAR as a reason without rejecting,
   and the profiler work first.

   Analysis of the five LULESH heap cases (2026-11-04, debug print of the rejecting record and its
   callpath states). In every one the two ends access **different objects** at a reused heap
   address: the read is of one temporary, the write of another one allocated later at the same
   address (2003: read `compression[i]`, write `pbvc[i]`; 2041: `e_old` / `e_new`; 2053 and 2211:
   `compHalfStep` / `q_new` and `pbvc`; 2348: `compression` / `bvc`). The report names the sink's
   variable, which hides this. `__dp_new` and `__dp_delete` are instrumented (malloc/new/free/delete),
   but both are no-ops in the runtime.
   - 2041, 2053, 2211: the ends lie in different invocations of the function. The callpath states
     are identical because every enclosing loop's bucket (iteration mod 3) happens to match, and the
     loop's own bucket differs because the two objects' offsets differ. So the record is attributed
     to that loop.
   - 2348 (the region loop): the ends are in different iterations of the *same* run, since each
     region allocates its own temporaries in `EvalEOSForElems`.
   - 2003: the ends come through different call sites, so the states already say "not carried"
     (`__carried_frame_and_position` returns None). `carried_by_pet_loops` is then None, which the
     detector treats as unknown and decides from the iteration copies instead. Fixable in the
     explorer: when both ends have states and the callpaths part, the record is carried by no loop
     past the parting frame.
   Encoding a loop run in the loopstate (the user's question) does not reach these cases. The
   callee's state is derived from (caller state, call site) on every entry, so a static run digit
   restarts with each invocation. Within one invocation a loop is re-entered only through an
   enclosing loop, whose bucket already changes. A run counter kept by the runtime across calls,
   encoded into spare bits of the 32-bit state field, would cover 2041/2053/2211, but not 2348 (same
   run). Clearing the shadow memory of the range `__dp_new` reports covers all five. That is the
   profiler change to make first: it forgets information instead of tracking more. The cost is
   proportional to the allocated bytes. The clear has to be ordered with the queued accesses of
   every worker; check `access_queue_workers.cpp`. Stack objects reused across calls have the same
   problem (`__dp_alloca`). The other remaining false rejections (miniFE 12:462 and `this1`, LULESH
   1004/1495) are naming and proof issues, not run issues.

   Original plan for F.1 (from reading `identify_simple_doall_and_reduction`):
   - Where: both scans skip `EdgeType.DATA` + `DepType.WAR` (the carried index of the loop, and the
     dependencies by iteration copies). Instead of dropping them, collect them per loop and decide
     after `detect_doall_sharing_clauses`, where the clause sets are known.
   - A carried WAR on `v` is harmless iff the storage it is on is per iteration once the loop runs in
     parallel:
     a. `v` is not visible at the loop (`ast_helper.get_variables_at_location` at the loop line):
        declared in the body, or a local of a callee, so every iteration has its own (caveat: a
        `static` local of a callee; checked via the AST if cheap, else noted);
     b. or the access is to `v`'s own storage (not `is_gep_result_dependency`: the profiler marks
        element accesses `GEPRESULT_v`) and `v` is in private/firstprivate/lastprivate or a
        reduction variable of the suggestion;
     c. anything else blocks, recorded as its own reason kind (`UNPRIVATIZED_WAR`), with the
        dependency. Without an AST, (a) cannot be decided and only (b) accepts.
   - The second pass (atomic updates) uses the same rule; a WAR is never an atomic site.
   - Measure: patterns before/after on miniFE, hist, LULESH, the review programs, and a few of the
     harness benchmarks; every removed suggestion is inspected (a real race, or an imprecision of
     the rule?).
3. Found on the way (pre-existing): a reduction variable used for something else in the loop. In
   miniFE `fem/Hex8.hpp` the loop over m gets `reduction(+:offset)`, but `offset++` is the index of
   `elem_mat[offset++]`, so each thread writes the wrong elements.
2. Hidden reads: the profiler keeps one last reader per address, so a read followed by a write of
   another iteration can vanish. Find where the profiler drops it, decide between keeping several
   readers and a cheaper conservative marker, and measure the profiling overhead.

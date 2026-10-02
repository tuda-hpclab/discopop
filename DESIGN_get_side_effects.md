<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License. See the LICENSE file in the package base
directory for details.
-->

# get_side_effects — Design & Implementation Plan

Status: first version implemented (uncommitted). The plan below is revision 3 (after the
proof of concept, §6, and two design review rounds); §8 lists where the implementation
deviates from it and what is known not to work yet.

Adds a read-only MCP tool `get_side_effects` that reports which data a function
was observed to read and write *outside of itself*, including through its
callees: globals, the memory its pointer/reference parameters point to, and
other memory that outlives the call. It answers "is this call pure / thread-safe
/ memoizable / safe to reorder?" during code review and refactoring as well as
for parallelization. Results are only valid for the profiled inputs.

---

## 0. Background: what already exists

- **TaskGraph** (`explorer/discopop_explorer/classes/TaskGraph/TaskGraph.py`) is
  built on every explorer run (`pattern_detection.py`, "Constructing
  TaskGraph"), but discarded afterwards; `DetectionResult` keeps only the PET.
- **Function instances.** Every inlined call is an `InlinedFunctionContext`
  (`call_instruction_id` = the call instruction; its
  `TGStartInlinedFunctionNode.pet_node_id` is the *calling* CU,
  `TaskGraph.py:2441`) that contains a `FunctionContext` copy of the callee, whose
  `TGStartFunctionNode.pet_node_id` is the callee's PET function node. Inlining is
  depth-limited (`call_path_limit = 6`, `__inline_function_calls`). The
  top-level copies directly below the root carry no dependencies.
- **Dependency mapping.** `__read_dependencies_from_files` builds
  `{type: {first_column_loc: {state: {other_loc: {state: [var_info]}}}}}`, then
  `__apply_dependency_overwrites`; `__insert_data_dependencies_from_files` maps
  each end to work contexts via `__get_work_contexts_by_location_and_state_id`,
  registering edges from the first-column end (the dependency's *sink*, the later
  access, `runtimeFunctions.cpp:166-190`) to the other end. WAW and INIT are
  skipped there. Static (`STAT_*`) records never cross a function.
- **Dependency file format** (current runtime): `<instr>@<state> NOM <TYPE>
  <instr>@<state>|<var>(<alias id>) ...`; dynamic INIT has `0@0` as its other end;
  records without `@` are static (hybrid analysis, local scalars and the
  parameters' own stack slots). `<call instr as 0:N> BGN func <callee start LID>`
  lists executed call edges (`FunctionManager.hpp:76-79`); `main` has no `BGN func`
  record, only `START <main start LID>` (`dp_func_entry.cpp`).
- **Variable names** are the name *at the first-column instruction*.
  `GEPRESULT_<base>` = access through pointer/array `<base>`; struct members are
  named by the member only (`names.cpp:90-125`); `this` for methods; LLVM
  temporaries like `call101` for pointers returned by calls.
- **Data.xml variable info is unusable here.** `<globalVariables>` means "used in
  more than one basic block" (`populateGlobalVariablesSet.cpp:34-38`),
  `defLine="GlobalVar"` is sticky (`populateGlobalVariablesSet.cpp:20-31`), and
  every `funcArguments` entry is `RW` (the parameter's own slot). Static facts are
  taken from the **AST** (`ast_dump.json`, loaded by the explorer's
  `ASTPatternDetectionHelper`) instead: file/namespace-scope `VarDecl`s with
  `name`/`mangledName`, `ParmVarDecl`/`VarDecl` per function with types,
  `DeclRefExpr` with `referencedDecl`, `CallExpr`.
- Accessed memory sizes are not used (not reliable).
- **Not profiled:** memory accesses inside library code that is not compiled with
  DiscoPoP (`printf`, `memset`, STL in system headers if not instrumented, ...).
- **Stack slot reuse.** `DP_STACK_ACCESS_DETECTION` is off, so stack addresses are
  not cleared on return; address-taken locals of sibling calls can produce
  dependencies across function boundaries that are not real data flow.

## 1. Semantics

Notation: `F` the queried function; `inst(F)` all `FunctionContext` copies of
`F` that can carry dependencies; `sub(F)` the work contexts in the subtrees of
`inst(F)`; `fn(x)` the function an instruction `x` lies in.

**Access kind of a record end.** A record's first-column instruction is a
*write* for INIT, WAR, WAW and a *read* for RAW; the other end is a write for RAW
and WAW, a read for WAR. INIT has no other end.

Only dynamic (`DYN_*`) records with a state on every mapped end are used.

### 1.1 Name classification (at the accessing instruction, relative to `fn(x)`)

The name of the first-column end is the record's var; the name of the other end
is `instruction_names[other_instr]`. If that table has no entry, the other end is
not classified (its effect, if any, is reported under the inside name only when
the inside end is the first column; otherwise it only contributes
`outside_names`).

0. a `MemberExpr` with that member name on the access line (AST
   `member_accesses`) → classify by the `MemberExpr`'s base with the rules below
   (`s->x` with pointer param `s` → param `s`; `this` → param `this`); if the base
   is unknown → **other**. Struct members are named by the member only
   (`names.cpp:90-125`), so without this step they collide with locals/globals.
1. strip `GEPRESULT_` → `base`, `through_pointer = true`
2. `base` is a parameter of `fn(x)`:
   - pointer / reference / array type (or `this`): **param** of `fn(x)`. This
     also holds without the prefix: `*x` of a scalar pointer is recorded under
     the plain name `x` (PoC: `100@87 RAW 124@85|x` in `bump`); the parameter's
     own slot only appears in static records, which are ignored
   - by-value: **local** of `fn(x)` (its own copy)
3. `base` is a local `VarDecl` of `fn(x)`:
   - `static` / `thread_local` storage → **global** (persistent state)
   - pointer / reference / array-of-pointer type → **other** (with or without
     `GEPRESULT_`: `*q` is named `q`, `names.cpp:141-143`; the pointer's own slot
     only appears in static records)
   - else **local**
4. `base` is a project global or a static data member (AST, display name):
   **global**
5. otherwise **other** (temporaries such as `call101`, unknown)

Locals and parameters shadow globals of the same name (rule order). If the AST
has no facts for `fn(x)` (`ast_facts: false`, e.g. the build ran outside the
project root and `filter_ast_dump.py` pruned everything, or code in system
headers), every name is **other** and the result is flagged (§1.3).

### 1.2 Effects of F

`inst(F)` = the *outermost* `FunctionContext` copies of `F` below `main`'s
top-level `FunctionContext` (the root links only to `main`,
`TaskGraph.py:657-665`); a copy nested inside another copy of `F` (recursion)
belongs to the outer one. `sub(I)` = work contexts in the subtree of instance
`I`; `own(I)` = those whose closest `FunctionContext` ancestor is `I` itself.

| class | rule | covers |
|---|---|---|
| **global** | any record end in `sub(I)` with a global name → read/write by the end's access kind, *regardless of where the other end is* | repeated calls, `++g` in a loop, recursion past the limit, write-only (INIT/WAW) |
| **param of F** (`via = null`) | same as global, but only ends in `own(I)` classified as a param of `F` | `write_through_param(p)`; not the inner instance's `*p` in `f(int*p){int l; f(&l); *p=1;}` |
| **callee param / other** | the record **crosses** `I`: one end of a mapped (first ctx, other ctx) *pair* in `sub(I)`, the other end mapped and outside; the inside end gives the access kind | memory a callee touches that belongs to `F`'s caller; escaping heap memory |
| **local** | dropped (stack reuse) | |

Effects of `F` = union over `I ∈ inst(F)`; crossing is decided per instance, so
two calls of `F` exchanging data through a callee's parameter still count.
Pairs come from the export as filtered by the same-state rule of dependency
insertion (`TaskGraph.py:3683-3690`), never re-built as a cross product.

- A callee's param effect that does not cross `I` is `F`-internal (e.g. `F`
  passes its own buffer) and is not reported.
- `via`: function chain from `F` to `fn(x)` (instance ancestry), `null` if `fn(x) = F`.
- `name` = the name at the inside instruction from the instruction-name table
  (§2.2); for a crossing record also `outside_names`.
- `source`: `observed`.

**Static fallback (globals only).** A global referenced (AST `DeclRefExpr`) in a
function of `F`'s static call closure and not observed → `read` (or `write` if it
is the LHS of an assignment, if cheaply derivable; else `access: "unknown"`) with
`source: static`. Covers constant tables and reads before any write. Parameter
fallback is dropped.

**Unprofiled calls.** `CallExpr`s in the static call closure to functions without
a definition in the project → `unprofiled_calls` (demangled names). Their memory
effects are unknown.

### 1.3 Coverage

Executed call edges `(caller, call instr c, callee)` come from `BGN func`
(`main` from `START`). A first column that is not a call instruction (the
`lastProcessedLine` fallback for callbacks from library code,
`FunctionManager.hpp:57-58`) counts as an *unmatched* edge.

- `not_executed`: `F` is the callee of no executed edge (and is not `main`).
  Only static facts are reported.
- `untracked`: executed, but no executed edge `(·, c, F)` matches an
  `InlinedFunctionContext` of `F` with `call_instruction_id == c` (beyond the
  inlining depth, function pointer, callbacks, constructors, ...). No observed
  effect can be reported.
- `partial`: some but not all executed edges into `F` are matched, or an executed
  edge whose call instruction lies in `own(I)` of an instance of `F` or of a
  callee below it has no matching `InlinedFunctionContext` there (depth limit,
  recursion).
- `executed`: otherwise.
- `unmapped_records` (record ends located in `F`'s lines that matched no work
  context) is reported as a number, not folded into coverage; the threshold for
  a downgrade is decided after measuring it on LULESH in step 1.
- `ast_facts: false` for `F` or a contributing callee adds a note and makes
  `pure_on_observed_inputs` null.

**`pure_on_observed_inputs`** (true / false / null):

- **false** if any *observed* write is reported (any coverage), or file I/O.
- **null** if coverage is not `executed`, or a static entry has
  `access: "unknown"`, or `unprofiled_calls` is non-empty (minus a short
  allowlist of known pure functions, e.g. `<cmath>`), or `ast_facts` is missing,
  or there is a read of a mutable global or of `other` memory (the result then
  depends on state outside the arguments: not memoizable, may not be reorderable).
- **true** otherwise: no writes, reads only through `F`'s own parameters or of
  `const` globals.

The note always says "on the profiled inputs".

**Ambiguity of `BGN func`.** It is keyed by the callee's start LID; functions
sharing a start line (one-line definitions, template instantiations) cannot be
told apart. Documented, accepted.

## 2. Architecture

```
explorer run                                        MCP server (on request)
TaskGraph + PET + AST + dependency dict
   └─► side_effects/export.py ──► .discopop/explorer/side_effects.json.gz
                                              │ load + index once (cached by mtime)
                                              ▼
                          side_effects/analysis.py: compute_side_effects(index, F)
                                              ▼ (cached per function)
                          mcp_server/tools/get_side_effects.py: rank, cut, word
```

### 2.1 Decisions

- **Compute on request** from a compact export (user concern: cost on large code
  bases). Explorer cost = one extra pass; measured below 1% of the explorer run on
  LULESH (§6).
- **The export is a separate pass**, run after the TaskGraph is built, over the
  same dependency dict (after overwrites), for RAW/WAR/WAW/INIT, reusing
  `__get_work_contexts_by_location_and_state_id` and the same-state filter of
  dependency insertion. `__insert_data_dependencies_from_files` is not modified,
  so the TaskGraph and the detection results are unchanged by construction.
  The dependency dict and the mapping caches are kept on the TaskGraph instance
  only if the export is enabled, and released after it.
- **Not jsonpickle** of the TaskGraph: the context relations are too deep for
  recursive encoders (`INVARIANTS.md` §7). The export holds only function
  instances, not the full Loop/Iteration/Branch tree.
- **One package for writer, schema, reader and analysis**:
  `explorer/discopop_explorer/side_effects/`. `mcp_server` already imports
  `discopop_explorer` (`get_data_dependencies.py:149`). The reader and the
  analysis import nothing heavy (no TaskGraph, no PET), so the server never loads
  the 18 MB+ PET dump for this tool.
- **Failure isolation:** export errors are logged as warnings and do not fail the
  explorer run; the tool then reports the export as missing.
- **Staleness:** the explorer deletes an existing export at the start of every
  run (also on `--load-existing-doall-and-reduction-patterns`, which builds no
  TaskGraph). The export stores mtime and size of `dynamic_dependencies.txt`; the
  tool rejects a mismatch with "run gather_data again".
- `--ignore-dependency-states` makes every record static: the export records the
  flag and the tool refuses the query with an explanation.

### 2.2 Export schema (`side_effects.json.gz`, `format_version: 1`)

```jsonc
{
  "format_version": 1,
  "discopop_version": "…",
  "ignore_dependency_states": false,
  "dependency_file": {"mtime": 1727870000.0, "size": 374103},
  "files": {"1": "/abs/path/code.cpp"},
  "globals": [{"name": "g_counter", "const": false},         // AST display names, incl.
              {"name": "g_table", "const": true}],           // static data members
  "functions": [{
     "id": "1:5",                                            // PET function node id
     "name": "_Z12write_globali", "display_name": "write_global(int)",
     "file_id": 1, "start_line": 19, "end_line": 19,
     "ast_facts": true,                                      // AST knows this function
     "params": [{"name": "v", "reachable": false}],          // pointer/reference/array/this
     "locals": [{"name": "i", "pointer": false, "static": false}],
     "member_accesses": {"27": {"second": "s"}},             // line -> member -> base name
     "performs_file_io": false,
     "static_callees": ["1:11"],                             // PET CALLSNODE
     "unprofiled_calls": ["printf"],
     "global_refs": [{"name": "g_table", "line": 35, "access": "read"}],
     "executed": true
  }],
  "instances": [                                              // FunctionContext copies
     {"id": 0, "function": "1:39", "parent": null, "call_instruction_id": null}],
  "work_contexts": {"17": 0},                                 // work ctx id -> instance id
  "records": [                                                // dynamic only
     {"type": "RAW", "var": "g_counter",
      "first": [186, 16, "1:16"], "other": [106, 54, "1:19"],
      "pairs": [[17, 23]]},                                    // (first ctx, other ctx), same-state filtered
     {"type": "INIT", "var": "g_sink", "first": [32, 34, "1:22"], "other": null,
      "first_contexts": [9]}],
  "instruction_names": {"58": ["GEPRESULT_p"]},
  "executed_calls": [["1:39", 111, "1:28"]],                  // caller fn, call instr (null if unmatched), callee fn
  "unmapped_records": {"1:28": 0}                             // per function: ends without context
}
```

Record end = `[instruction id, state id, line id]`. Pairs are produced exactly
like the edges of dependency insertion (same lookup, same-state filter), so the
analysis never rebuilds a cross product. `ast_dump.json` is concatenated JSON
(one document per TU, `CXX_wrapper.sh:94`) and is read with the existing
`ClangASTLoader`.
`instruction_names` comes from all records whose first column is that
instruction (INIT, WAR, WAW for writes; RAW for reads). Instance ancestry is
built iteratively with a visited set (`INVARIANTS.md` §7 permits one-sided
links); orphaned work contexts are counted and logged.

### 2.3 Index (server, at load)

- Pre/post order numbers over the instance tree → "work context in subtree of
  instance" in O(1).
- `function id -> instances`, `demangled base name -> function ids`.
- Per instance: the records with an end in its own work contexts.
- `ToolContext` caches the index by `(path, mtime)`, like the detection result,
  and per-function results inside the index object.

## 3. The MCP tool

```
get_side_effects(project_path, function, file_path?, line?,
                 access?: "read"|"write", kinds?: ["global","parameter","other"],
                 var_name?, include_callees=true)
```

- `function`: demangled name without or with signature (`write_global`,
  `write_global(int)`), or the mangled name. `file_path`/`line` (any line inside
  the definition) disambiguate; an ambiguous name returns `status: "ambiguous"`
  with the candidates (display name, file, lines).
- Output:

```jsonc
{"status": "success",
 "function": {"name": "write_through_param(int*, int)", "file": "…", "start_line": 25, "end_line": 30},
 "coverage": "executed", "pure_on_observed_inputs": false,
 "performs_file_io": false, "unprofiled_calls": [],
 "summary": {"num_effects": 3, "by_access": {"write": 2, "read": 1},
             "by_kind": {"global": 0, "parameter": 1, "other": 0},
             "contributing_callees": []},
 "writes": [{"name": "p", "kind": "parameter", "through_pointer": true, "source": "observed",
             "num_sites": 1, "sites": [{"line": 27, "via": null}], "outside_names": ["GEPRESULT_buf"]}],
 "reads": [],
 "truncated": false,
 "notes": ["Effects were observed on the profiled inputs only …"]}
```

- One entry per (name, kind, access); `sites` capped at 3 (all sites with
  `var_name`). Files other than the function's own as `{file, line}`.
- **Ranking** when cutting to `MAX_EFFECTS = 100`: writes before reads;
  global > parameter > other; own before callee, shallower callee first;
  observed before static; then name. Summary, coverage and flags are never cut.
- `next_step` for: truncation (filters), ambiguity, `not_executed` / `untracked`
  / `partial` (what it means, what to do), missing / stale export or
  `ignore_dependency_states` (run gather_data).
- Registered in `_ALL_TOOLS` (also in the "analysis" set). The server
  instructions get one short clause next to `get_data_dependencies`, keeping
  them within 2048 chars.

## 4. Implementation steps

1. **Export (explorer)** — `side_effects/schema.py` (TypedDicts, version
   constant, `load_export`), `side_effects/export.py` (`build_export(task_graph,
   pet, ast_helper, dependency_dict, …)`, `write_export`), minimal hooks:
   `TaskGraph` keeps the dependency dict + mapping inputs when asked;
   `pattern_detection.py` passes them on; `discopop_explorer.run` deletes the old
   export and writes the new one.
2. **Analysis** — `side_effects/analysis.py`: index, classification (§1.1),
   effects (§1.2), coverage (§1.3), result dataclasses (§3 shape without ranking).
3. **MCP tool** — `mcp_server/tools/get_side_effects.py`, ranking, cutting,
   wording, `ToolContext.get_side_effects_index`, registration, instructions,
   `docs/` MCP page.
4. Tests (§5), mypy, black on changed paths only.

The schema in §2.2 is the interface: after step 1's `schema.py` exists, steps 2
and 3 can be developed in parallel against hand-written exports (agents).

## 5. Testing

**Ground-truth program** `test/end_to_end/mcp_server/src/side_effects/code.cpp`,
one function per case, each annotated with its expected effects:

| function | expected |
|---|---|
| `pure_add(a, b)` | none, pure |
| `read_global()` | read `g_counter` |
| `write_global(v)` | write `g_counter` |
| `write_only_global(v)` | write `g_sink` (INIT only) |
| `write_through_param(p, n)` | write param `p` (pointee) |
| `wrapper(q, n)` | write param `p` via `write_through_param` — crossing; `F` passes `q` |
| `local_buffer()` | none: passes a local array to `write_through_param`. **Limitation candidate**: stack reuse can make it look like a crossing (§7) |
| `next_value()` called twice + `++g` in a loop | read+write `g_seq` (B5) |
| `address_taken(v)` | none: by-value parameter whose address is passed to a callee |
| `sibling_a()` / `sibling_b()` | none expected; **documented limitation** if the shared stack slot of `bump`'s parameter pointee shows up as a crossing (§7). The test asserts the actual outcome and names the limitation |
| `clear(p, n)` with `memset` | `unprofiled_calls: [memset]`, not pure (B7) |
| `set_member(s)` | write param `s` (member `second`, via the AST `MemberExpr` rule); the PoC records it as `INIT GEPRESULT_s` |
| `shadow()` | local `g_counter` shadows the global: none |
| `count_calls()` called twice | read+write the function-static `calls` (kind `global`) |
| `read_const_table(i)` | read `g_table`, `source: static` |
| `never_called()` | `not_executed` |
| `recurse(n)` | read+write `g_counter`; `partial` (the deepest instance has an executed edge, instruction of the recursive call, without a child) |
| `chain1` … `chain7` | only 5 levels below `main` are inlined, so `chain6`/`chain7` have no instances: `chain1` is `partial`, `g_chain` appears as `source: static` only; `chain7` itself is `untracked` |
| `call_via_pointer(f)` | `pointer_target` has no static call site and runs only through the pointer: `untracked`; `call_via_pointer` is `partial` (executed edge without inlined context) |
| `log_value(v)` | file I/O (`performs_file_io`), `unprofiled_calls: [printf]` |

Some rows will probably reveal limits (e.g. struct members, function
pointers); a row may be changed to a documented limitation, never silently.

| level | what | where |
|---|---|---|
| unit (export) | small dependency files + hand-built contexts, following `test_read_dependencies_from_files.py` (the conftest `build_task_graph` sets `contexts = []`): records, both ends mapped, INIT end `null`, instruction names incl. WAR, executed calls, `main` via `START`, stale export deleted, flag on `--ignore-dependency-states`, export failure does not fail the run | `explorer/discopop_explorer/side_effects/test_export.py` |
| unit (analysis) | hand-written exports, one test per rule of §1.1–§1.3 and per row above that can be expressed without the profiler | `.../side_effects/test_analysis.py` |
| unit (tool) | name resolution (demangled, signature, mangled, ambiguous, file/line), ranking order, truncation + `next_step`, summary never cut, filters, missing / stale / unknown version / ignore-states export, cache invalidation | `mcp_server/tools/test_get_side_effects.py` |
| detection unchanged | in **one process**: build the TaskGraph, digest all contexts' `outgoing_dependencies`/`incoming_dependencies` (lines, type, var, context creation index), run the export pass, digest again: equal. Cross-process pattern equality is not deterministic (state-id assignment short-circuits over set order, `TaskGraph.py:3158-3164`), at most a smoke check | `.../side_effects/test_export.py` (synthetic) + e2e on the ground-truth program |
| e2e (MCP) | full pipeline on the ground-truth program, `get_side_effects` per function, asserted against the table | `test/end_to_end/mcp_server/test_workflows.py` (skipped without profiler) |
| tool listing | tool present in "all" and "analysis"; instructions ≤ 2048 chars | `test_stdio_server.py` |
| performance | LULESH: export time, size, load, query for `main` and a leaf; recorded in §6 | manual |

All of: `venv/bin/python -m pytest`, MCP e2e, explorer e2e, mypy for
`discopop_explorer`, `discopop_library`, `mcp_server`.

## 6. Proof of concept (done, 2026-10-02)

Ground-truth program (first version), real pipeline, TaskGraph captured
in-process; the scripts live outside the repository.

- Confirmed: edge direction, function identity via `FunctionContext` copies,
  name = sink-side name (`p[i] = i` appears as `GEPRESULT_buf`), WAW/INIT needed
  (`write_only_global` only produces `INIT 0@0|g_sink`; the first
  `write_through_param(buf)` call is only visible via WAW).
- State ids do not mean "executed": `never_called` inherits them; `BGN func`
  records are the coverage source (`main` via `START`).
- With TaskGraph edges alone the expected crossings appear for `read_global`,
  `write_global`, `wrapper`, `recurse`; none for `pure_add`, `log_value`, `main`.
- **LULESH measurement**, fresh build of this checkout, `-s 6 -i 10`,
  2 977 states, `--enable-patterns doall,reduction`: explorer 12.1 s (TaskGraph
  5.6 s), 9 683 contexts, 74 021 context dependencies. Prototype export
  (contexts + edges + lines): 0.12 s, **7.6 MB plain / 0.5 MB gzip**; load + index
  0.04 s; query over the largest subtree 0.01 s; explorer peak RSS 575 MB. The
  record-based export (§2.2) will be larger (WAW/INIT, both ends); re-measured in
  step 1.
- The first LULESH data set (2026-08-11) was unusable (3 states). A fresh build
  first also froze at 2 states: `initial_stateID.txt` had two lines, `main` and
  `_Z11DumpToVisitR6Domainiii` ("Do**main**"), and the runtime takes the last one.
  Compiling `lulesh.cc` last avoided it. **This is a profiler bug outside this
  feature** (`DiscoPoP::save_initial_path` matches `"main"` as a substring); to
  be reported separately.

## 7. Risks / limits (v1)

- Variable names are those at the access; callee parameter names are not mapped
  back to the caller's arguments (possible later with
  `DP_MEMORY_REGION_DEALIASING`).
- Struct members are named by member only; classified via the AST `MemberExpr`
  on the access line, else `other`.
- **Stack reuse.** `DP_STACK_ACCESS_DETECTION` is off, so two sibling calls that
  pass `&local` to the same callee can exchange dependencies through the reused
  slot; this looks exactly like a real callee-param crossing (the overwritten
  `write_through_param(buf)` case) and cannot be told apart in v1. Follow-up:
  measure the cost of a runtime built with stack access detection
  (`clearStackAccesses`, `dp_func_exit.cpp:65-80`).
- Static locals and static data members count as globals; locals in system
  headers have no AST facts (`ast_facts: false`).
- The cross product of dependency insertion (`TaskGraph.py:3683-3712`) can pair
  different instances; requiring a state on both ends and applying the same-state
  filter limits this. Remaining false crossings show up as `other` effects.
- Accesses of unprofiled library code are invisible (`unprofiled_calls`).
- Reads that occur before any write in the program are only found by the static
  fallback (globals only).

## 8. As built (2026-10-02)

**Deviations from the plan above**

- `executed_calls` entries are objects `{caller, call_instruction_id, callee}`
  (`schema.ExecutedCall`), not triples. `main`'s `START` and callbacks from library
  code have `call_instruction_id: null`; an edge matches an instance when the call
  instruction ids are equal (null matches only main's root instance).
- The export has `linker_names` (linker name -> source name): the profiler records
  function-static locals and static data members under their linker name
  (`_ZZ11count_callsvE5calls`).
- No explicit deletion of an old export: `setup_explorer` removes the whole
  `explorer/` directory at the start of every run.
- The PET takes a node's file id from its node id, which is wrong for node `"0:0"`
  (the first function); the export takes the file id its CUs agree on
  (`export._function_file_ids`). Pre-existing bug, not fixed in the PET.
- The MCP documentation lives in `mcp_server/README.md` (there is no page in `docs/`).
- The tool lists entries with `access: "unknown"` (static fallback) in a separate
  `unknown_access` list.
- `set_member(s)`: the profiler records `s->second = 7` as `GEPRESULT_s`, so the effect
  is the parameter `s` (the `MemberExpr` rule applies to plain member names only).

**Verified**

- Unit tests (`side_effects/test_export.py`, `test_analysis.py`,
  `mcp_server/tools/test_get_side_effects.py`) and the end-to-end ground-truth test
  (`test/end_to_end/mcp_server/test_workflows.py::TestSideEffects`).
- In one process, a digest of all context dependencies before and after
  `TaskGraph.map_dynamic_dependency_records` is equal, on the ground-truth program and
  on LULESH: the export does not perturb detection.
- Export cost on LULESH (fresh build, 2 977 states): 1.2 s of a ~13 s explorer run,
  44 KB gzip.

**Known not to work yet: TaskGraph state assignment on larger programs**

On LULESH, `TaskGraph.__assign_state_ids` assigns only **2 of 2 977** observed states
to any context, so only 15 of 42 371 dynamic records can be attributed to a function
instance (39 097 record ends are reported as `unmapped_records`). `get_side_effects`
then reports almost no observed effects; the static facts (globals referenced,
unprofiled calls, file I/O, coverage) are unaffected. This is a pre-existing problem
of the TaskGraph and also affects which dynamic dependencies pattern detection sees.
Two causes were identified:

1. The contexts of the first iteration copy of `main`'s loop body are detached: the
   `InlinedFunctionContext` of a call in it has a `WorkContext` without parent as its
   only ancestor, so the state search from the root never reaches it.
2. After a loop-state match the head of the callpath is only consumed if it is the last
   element (`len(callstate) == 1` in `compute_assignment`), so no callpath that
   continues into a call inside a loop can match. Removing that condition raises the
   number of assigned states from 2 to 22 only, so (1) and possibly more are needed.

On the small ground-truth program the same effect is visible in a reduced form: the
reads of `g_seq` in the loop calls of `next_value` are lost (13 unmapped ends).

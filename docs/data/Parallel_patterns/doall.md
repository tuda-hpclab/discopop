---
layout: default
title: Do-All
parent: Parallel patterns
grand_parent: Data
nav_order: 1
---

# Do-All loop

In a do-all loop, no iteration depends on the result of another iteration, so the iterations can run in parallel. The explorer detects do-all loops by default.

## Reporting

The explorer reports the loop `for (int i = 0; i < N; i++) { Arr[i] = i % 13; }` of `example/example.cpp` in `.discopop/explorer/patterns.json` (excerpt of `patterns` / `do_all`):

```json
{
  "pattern_id": 0,
  "node_id": "1:7",
  "start_line": "1:20",
  "end_line": "1:20",
  "applicable_pattern": true,
  "standalone_pattern": true,
  "pattern_tag": "DoAllInfo@1:20-1:20_p([])_s(['N'])_fp([])_r([])_lp([])_c(1)",
  "affected_cu_ids": ["1:7"],
  "iterations_count": -1,
  "pragma": "#pragma omp parallel for",
  "first_private": ["N"],
  "private": [],
  "last_private": [],
  "shared": [],
  "reduction": [],
  "scheduling_clause": "static",
  "collapse_level": 1,
  "collapsed_pattern_ids": [],
  "affected_line_ids": ["1:20"],
  "affected_functions": ["0:15:main"]
}
```

The fields shared by all patterns are described on the [Parallel patterns](Patterns.md) page. In text form (printed instead of the JSON file if you disable the JSON output) the pattern looks like this:

```text
Do-all at: 1:7
Start line: 1:20
End line: 1:20
pragma: "#pragma omp parallel for"
collapse: 1
private: []
shared: []
first private: ['N']
reduction: []
last private: []
scheduling clause: static
```

## Interpretation

* `node_id` / `Do-all at`: `<file id>:<node id>` of the entry CU of the loop. Look up the file id in [`FileMapping.txt`](../Filemapping.md) and the node in [`Data.xml`](../Profiling_and_instrumentation_output.md).
* `start_line` / `end_line`: `<file id>:<line>` of the first and last line of the loop.
* `pragma`: the OpenMP pragma that parallelizes the loop.
* `private`, `shared`, `first_private`, `last_private`: the data sharing clauses of the loop; the text form writes `first private` and `last private`. The loop index is not listed. A do-all pattern has an empty `reduction` list.
* `sharing_notes`: one sentence for every variable whose data sharing was decided from the syntax tree without evidence from the profile (see below); the MCP suggestion list shows them as `flag:` lines. Empty if the profile covered every variable.
* `scheduling_clause`: the scheduling the patch uses, `static`.
* `collapse_level`: the number of perfectly nested do-all loops the pattern covers (`collapse(<n>)`). Nested do-all loops yield additional patterns with a higher `collapse_level`; `collapsed_pattern_ids` names the patterns that were folded into one. They are alternatives: applying a collapsed pattern excludes applying the ones it folds, because a pragma between two collapsed loops does not compile.

## Implementation

You do not insert the pragma by hand. The [patch generator](../../tools/Patch_generator.md) creates a patch for the pattern that adds the clauses, and the [patch applicator](../../tools/Patch_applicator.md) applies it. For the pattern above, `.discopop/patch_generator/0/1.patch` contains:

```diff
@@ -17,6 +17,7 @@
   long sum = 0;
   int Arr[N];

+  #pragma omp parallel for firstprivate(N)
   for (int i = 0; i < N; i++) {
     Arr[i] = i % 13;
   }
```

Besides the clauses of the data sharing lists, the pragma carries `collapse(<n>)` if `collapse_level` is larger than 1, and `default(none)` unless the explorer ran with `--no-doall-default-none`.

### Variables the profile does not name
The profiler names an access after the value it goes through. A variable which the loop only reaches through calls (a `std::span`, a smart pointer, the methods of an object) or only reads in its loop header (`i < n`) leaves no dependence under its own name. The explorer therefore also takes the variables the loop refers to from the syntax tree, and classifies the ones the profile did not:

* Nothing in the loop can write the variable (it is `const`, or it is only read, and no non-const method is called on it): `shared`. Writes into the elements of a container or through a pointer (`out[i] = x`) are not writes to the variable.
* The variable is written in the loop, or its address escapes: `firstprivate`, with a note.
* A local object whose non-const methods are called (`tmp.reset()`), where the profile does not attribute the writes made inside the methods: `private` if its declaration shows a default constructor, `lastprivate` if it is used after the loop, `firstprivate` otherwise. The note asks to check that every iteration initializes it.
* A parameter, a reference, a container or an array passed on by mutable reference: `shared`, with a note, as the calls write its elements.
* A lock, an atomic, a stream or another type which cannot be copied or whose purpose is to be shared (`std::mutex`, `std::atomic`, `std::ostream`, ...): `shared`, with a note.
* A global variable of the translation unit: `shared`.

Typedefs and aliases are resolved first (`using real = double` is a scalar). Without a loaded AST, only the variables of the profile are classified.

Limits of `default(none)` (the default; `--no-doall-default-none` switches it off): `default(none)` also asks for globals declared in headers which are not part of the project (`std::cout`) and for variables of namespaces. These have no unqualified name in the loop, and the explorer does not list them, so the compiler rejects such a pragma until the variable is named (clang accepts `shared(std::cout)`) or `default(none)` is removed.

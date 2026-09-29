<!--
This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)

Copyright (c) 2020, Technische Universitaet Darmstadt, Germany

This software may be modified and distributed under the terms of
the 3-Clause BSD License.  See the LICENSE file in the package base
directory for details.
-->

# TaskGraph structural invariants

`TaskGraph` (`TaskGraph.py`) builds a single control-flow graph (`self.graph`, an
`nx.MultiDiGraph` of `TGNode`s) for the whole program, then runs a sequence of
passes in `__construct_from_pet` that progressively restructure it. Several of
these passes only produce correct results if the graph satisfies structural
invariants that are never fully validated at runtime - when one breaks, the
usual symptom is a confusing failure several passes later (e.g. a `ValueError`
in `__calculate_context_nesting`), far from the pass that actually violated it.
This document makes those invariants explicit.

## 1. Matched Start/End pairing

Every construct that can be "entered" - `TGStartFunctionNode`, `TGStartLoopNode`,
`TGStartIterationNode`, `TGStartBranchParentNode`, `TGStartBranchNode`,
`TGStartWorkNode`, `TGStartInlinedFunctionNode` - must have a corresponding
End-type node reachable on every forward path, and conversely **no End-type
node may be reachable without first passing through its Start counterpart** on
that same path.

`__calculate_context_nesting` implements this as a simple stack machine: it
does a BFS from every node with zero predecessors, pushing a context on Start
nodes and popping on End nodes. It has no recovery path if an End node is
encountered with an empty stack - that raises
`ValueError("Current context must not be None during processing!")` directly.
Concretely, this means: **a node with zero predecessors must never be an
End-type node** (see invariant 3).

## 2. Single-entry/single-exit (SESE) regions

Branch/loop/work/inlined-function wrapping is only valid if the wrapped region
has exactly one entry edge and one exit edge crossing its boundary.
`__add_branching_nodes_for_function`'s docstring states this explicitly:
dominance/post-dominance is used specifically to *guarantee* properly nested
SESE regions, because the context-nesting stack walk (invariant 1) only
produces one consistent enclosing context per node when the regions it walks
are properly nested. A purely local in/out-degree heuristic can instead wrap
unrelated, non-nested merge points into the same marker, which silently
corrupts context assignment depending on graph traversal order.

## 3. No zero-predecessor End-type / zero-successor Start-type nodes

This is implied by invariant 1, but is the one that actually gets violated in
practice and is worth stating on its own: no `TGEndBranchParentNode` (or any
other End-type node) may end up with zero predecessors, and no
`TGStartBranchParentNode` (or Start-type node) may end up with zero
successors. Such a node is either unreachable (harmless, but dead weight) or -
far more commonly - a node with **zero predecessors that IS reachable**
because it has zero predecessors globally, making it a bogus entry point for
invariant 1's BFS.

`__add_branching_nodes` validates this directly after `__add_branching_nodes_for_function`
and `__add_branching_nodes_fallback_cleanup` run (`TaskGraph.py`, the
"validating amounts of node successors and predecessors" loop), raising
`ValueError("Invalid graph structure!")` immediately if it's violated - turning
a would-be confusing crash deep in context nesting into an immediate, precisely
located one.

Two concrete ways this invariant used to break in `__add_branching_nodes_for_function`
(both fixed - see `test_TaskGraph.py`):

- **A branch point can dominate none of its merge point's current
  predecessors.** `m = ipdom(n)` only guarantees that all paths from `n`
  eventually reach `m` - not that `n` is the sole way to reach `m`. If `m` is
  also reachable from outside `n`'s subtree (e.g. two independent branches
  that happen to reconverge at the same point), `n` can end up dominating none
  of `m`'s current predecessors. Wrapping `n` anyway would create a
  `TGEndBranchParentNode` with zero predecessors. Fix: compute the claimed
  predecessor set before mutating anything, and skip wrapping `n` entirely
  (leaving it for `__add_branching_nodes_fallback_cleanup`, which is designed
  for exactly this case) if the claim is empty.
- **A branch point can be one of its own merge point's direct predecessors.**
  An "if" with no "else" has one arm going straight to the merge point `m`,
  so `n` trivially dominates itself and is included in the claimed-predecessor
  set computed from `m`. But the *next* step unconditionally retargets all of
  `n`'s own outgoing edges (including that direct arm to `m`) onto a freshly
  created `start_branch_parent_node`. By the time the claimed-predecessor loop
  runs, `(n, m)` no longer exists - only `(start_branch_parent_node, m)` does.
  Removing it a second time raises `nx.NetworkXError` and aborts the
  function's wrapping partway through, leaving whatever
  `TGEndBranchParentNode` was under construction behind with however many
  predecessors happened to be wired before the abort (possibly zero). Fix:
  substitute `start_branch_parent_node` for `n` when processing the claimed
  set, since that's the live stand-in for `n`'s own contribution after the
  rewiring above.

## 4. Acyclicity per function

`__break_cycles` and `__duplicate_loop_iterations` turn each function's
control-flow subgraph into a DAG before any pass that relies on it (dominance
for branching nodes, the context-nesting BFS) runs - loops are unrolled into
two linear copies instead of kept as back-edges. All later passes assume no
cycles remain and none of them re-checks it, so `__validate_graph_structure`
does: it reports every remaining strongly connected component (and self-loop)
with the function it belongs to, as an error, directly after loop unrolling.

The consequences of a surviving cycle are severe and all of them surface far
away from their cause: dominance-based region wrapping (invariant 2) is unsound,
the context-nesting stack walk (invariant 1) assigns whichever enclosing context
a path happens to arrive with, and `__calculate_context_successions` **does not
terminate at all** if the cycle enters a different number of contexts than it
leaves - it dedupes its traversal on `(node, level)`, so each lap around such a
cycle shifts the level by the imbalance and produces a state it has not seen
before. That last one presents as unbounded memory growth minutes later, with
nothing pointing back here, which is what makes the check worth its runtime.

Two ways this is known to break, both observable on LULESH:

- **Cycles in detached control flow.** `__break_cycles` searches with
  `nx.find_cycle(self.graph, source=<function node>)`, so it only ever sees
  cycles reachable from a function entry node. It also removes edges and rewires
  predecessors, and in doing so detaches a few hundred nodes from their function
  root (~470 of 4600 on LULESH). Any cycle inside that detached part is
  invisible to it and survives - which is exactly what happens since the
  control-flow edges restored for invariant 6 made a few more cycles land there.
  The detached nodes are a problem in their own right: their heads have no
  predecessors, so invariant 1's BFS treats them as program entry points.
- **The crude fallback gives up.** When no loop header/exit can be derived, the
  fallback removes one edge and *adds* one (to an outside successor, or to the
  function's exit node), which can create a new cycle, then advances
  `search_source` to the next descendant rather than restarting the scan - and
  `break`s out of the function entirely once that queue is exhausted.

## 5. `iteration_nodes` closure

Used by `__get_iteration_nodes` / `__copy_iteration_subgraph` /
`__fix_loop_structures`: a node belongs to "one iteration" iff it has a
forward path to the iteration's end node. Edges from a member of this set to a
non-member are expected to be pruned by `__fix_loop_structures` *before*
`__duplicate_loop_iterations` copies the set. If one slips through anyway,
`__copy_iteration_subgraph` silently drops it when copying (visible as a
`"could not draw edge ... due to a KeyError"` warning) rather than raising -
usually harmless in isolation, but the same "unvalidated invariant" pattern as
invariant 3, and a candidate root cause if a similar orphaned-node crash shows
up again elsewhere in construction.

## 6. Complete control flow after `__visit_pet`

Every `EdgeType.SUCCESSOR` edge of the PET graph must have a counterpart in the
TaskGraph once `__visit_pet` returns. The traversal creates an edge when it
*visits the target*, taking the predecessor from the queue entry - so any
successor that is deliberately not queued needs its edge added explicitly.
`__visit_branching` must skip queueing already-visited successors (otherwise the
traversal never terminates on cyclic control flow, since `__visit_CUNode`'s
single-successor path queues unconditionally), which is exactly where an edge
can get lost.

This is the invariant `__break_cycles` depends on: it derives a loop's header,
its iteration entry/exit points and its exit node purely from the shape of the
cycle it finds. A missing exit edge makes the loop look exit-less, and the only
node that then still matches the "one successor inside the cycle, one outside"
header pattern is a branch *inside the loop body* - because `nx.find_cycle`
returns a single simple cycle and therefore contains only one arm of that
branch. The pass then anchors `TGStartLoopNode`/`TGEndLoopNode` at the wrong
node, removes the wrong edge as the "back edge", leaves the real cycle in place
for the crude fallback to sever, and the resulting `TGStartLoopNode` has zero
predecessors and no path to its `TGEndLoopNode`. The symptom surfaces much
later, in `__assign_loop_contexts`, as
`ValueError("Could not determine loop end node for loop: ...")`.

The shape that triggered this in practice (miniFE, via libstdc++'s
`__insertion_sort`): a function whose early return shares its exit CU with the
loop exit, plus an `if`/`else` inside the loop body. The early return reaches the
exit CU first, so the loop header's exit edge targets an already-visited node.
See `test_TaskGraph.py`.

## 7. Acyclic, two-sided `Context` relations

The `Context` objects carry two relations, both built after the graph passes above:

- **containment** — `parent_context` / `contained_contexts`, built by
  `__calculate_context_nesting` (plus `__assign_branching_contexts` and
  `__assign_loop_contexts`)
- **succession** — `predecessor` / `successor`, built by
  `__calculate_context_successions`

Every traversal of them - in `Context` itself, in the pattern detectors, in
`ContextTaskGraph` - assumes containment forms a forest and the successor chains
are acyclic. Nothing in the building passes guarantees that: both assign
`parent_context` / `successor` unconditionally, so the last write wins, and
`__calculate_context_successions` dedupes its BFS on `(node, level)` while
discarding the context stack, so a node reached twice at the same nesting level
along different paths can be linked into two different sequences. An unbalanced
Start/End pair (invariant 1) corrupts `current_level` and has the same effect.

A cycle introduced that way stays invisible until some traversal walks it, which
surfaces as a `RecursionError` or a hang arbitrarily far from the cause -
originally in `Context.get_contained_contexts_in_sequence`, called per loop
iteration from `new_do_all_detector`.

`__validate_context_structure` runs directly after
`__calculate_context_successions` and enforces this: it breaks cycles in both
relations (logging an error, since a cycle always means one of the passes above
is wrong) and reports links recorded on only one of their two ends, which it
cannot repair unambiguously. `Context.add_contained_context`,
`register_parent_context` and `register_successor_context` additionally refuse
the cycles they can detect in constant/depth-bounded time; longer successor
cycles are left to the validation pass, because scanning the chain on every
registration would make building the relation quadratic.

Independently of acyclicity, **the relations are also too large to traverse
recursively**: successor chains grow with the amount of inlined code and
containment nesting with the inlining depth, so any recursive walk hits Python's
recursion limit on well-formed input alone. All traversals in `Context` are
iterative for that reason. `get_contained_contexts_in_sequence` is additionally
bounded to the region it was asked about, so a successor chain leaving that
region cannot pull unrelated contexts (and their CUs) into a caller's result.
See `Contexts/test_Context.py` and `test_TaskGraph.py`.

## 8. One set of loop/iteration markers per loop

`__break_cycles` wraps each loop in exactly one `TGStartLoopNode`/`TGEndLoopNode`
pair, with one `TGStartIterationNode` per iteration entry point and one
`TGEndIterationNode` per iteration exit point in between. Two Start markers of
the same kind for the same PET node must never end up nested inside each other -
`__assign_loop_contexts` pairs an iteration start with its end by walking forward
and counting equivalent nodes on the way, and a second start it reaches before
that end has no matching end to consume, which raises
`ValueError("Invalid iteration structure found at node: ...")`.

Keeping this to one wrapping requires **all of a loop's back edges to be cut in
the same restructuring step**, and that is what makes it fragile: `nx.find_cycle`
returns a *single simple cycle*, so a loop with more than one latch - a
`continue`, or a nested loop whose exit branches back to the outer condition -
appears as several distinct cycles, and the nodes of the one that gets returned
contain only one of the latches. Restructuring from those nodes alone leaves the
loop's other back edges intact, the very same loop is found again on the next
pass, and it is wrapped a second time - this time with the previous
`TGStartLoopNode` as its "header", so the duplicate markers nest.

`__break_cycles` therefore widens the cycle it found to its whole strongly
connected component (`__get_cyclic_region`) before deriving anything from it.
For a loop that is the loop with everything nested inside it, which makes all of
its latches predecessors of the header *within the region* and - just as
importantly - restricts the exit-edge candidates to edges that really do leave
the loop, rather than including body edges that merely leave the one cycle found.

The shape that triggered this in practice (rodinia kmeans, `kmeans_clustering`'s
outer loop): a `for` loop whose body both `continue`s and contains a nested loop
whose exit leads back to the outer loop's condition. See `test_TaskGraph.py`.

## Where this bites in practice

All of the invariants above are enforced (or silently violated) inside
`__construct_from_pet`'s single linear pipeline. The passes run in this order,
and each one's correctness assumption depends on the previous ones having held:

```
__visit_pet -> __break_cycles -> __fix_loop_structures -> __duplicate_loop_iterations
  -> __validate_graph_structure (checks invariant 4) -> __add_work_nodes
  -> __assign_loopstate_positions_within_functions -> __inline_function_calls
  -> __add_branching_nodes -> __assign_contexts -> __assign_node_levels
  -> __calculate_context_nesting -> __calculate_context_successions
  -> __validate_context_structure
```

When debugging a "malformed graph" failure, first identify *which* invariant
broke and on *which* node (the exception message and node label are usually
enough), then look at the pass responsible for maintaining that invariant
rather than the pass that happened to crash - by the time invariant 1 or 3
breaks, the actual mistake was usually made several passes earlier.

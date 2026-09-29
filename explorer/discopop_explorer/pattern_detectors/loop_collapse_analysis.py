# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Identification of do-all loop nests which can be parallelized as a single construct using
OpenMP's `collapse` clause.

This is a post-processing step on the list of patterns reported by the do-all detection. It does
not perform any dependency analysis of its own: a nest is collapsible only if every loop in it has
already been reported as a plain do-all pattern.

The clauses of the collapsed construct are obtained by merging the clauses of the individual
loops. That merge is only sound because of the strict perfect-nesting requirement enforced here:
with nothing in the outer loop body but the inner loop, a variable which was private per outer
iteration is only ever touched inside the inner loop, so privatizing it per collapsed iteration
preserves the original semantics.
"""

import logging
from typing import Dict, List, Optional, Set, Tuple

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.variable import Variable
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import in_edges
from discopop_explorer.functions.PEGraph.traversal.children import direct_children
from discopop_explorer.pattern_detectors.clause_classification import filter_classifications, merge_classifications
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo
from discopop_explorer.pattern_detectors.reduction_detector import ReductionInfo
from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper

logger = logging.getLogger("Explorer").getChild("LoopCollapse")


def identify_collapsible_loop_nests(
    tg: TaskGraph,
    ast_helper: ASTPatternDetectionHelper,
    patterns: List[DoAllInfo | ReductionInfo],
) -> List[DoAllInfo]:
    """Identifies cleanly nested do-all loops among the given patterns and creates a new do-all
    pattern with an increased collapse level for every collapsible nest.

    The returned patterns are additional alternatives, they do not replace the patterns they were
    derived from. Each records its origin in `collapsed_pattern_ids`.
    """
    logger.info("Identifying collapsible loop nests...")

    loop_variables_by_node_id = __collect_loop_variables(tg)
    base_patterns_by_loop_node = __collect_collapsible_base_patterns(tg.pet, patterns)

    collapsed_patterns: List[DoAllInfo] = []
    # keyed by (loop entry node, collapse level): the same nest is reachable from a pattern list
    # which contains more than one copy of the same loop
    known_collapses: Set[Tuple[NodeID, int]] = set()

    for loop_node_id, base_pattern in base_patterns_by_loop_node.items():
        chain = __get_cleanly_nested_chain(tg.pet, loop_node_id, base_patterns_by_loop_node)
        if len(chain) < 2:
            continue
        logger.debug(
            "Collapsible nest of depth "
            + str(len(chain))
            + " starting at "
            + str(base_pattern.start_line)
            + ": "
            + str([p.start_line for p in chain])
        )
        # every depth is a valid alternative, so report all of them and let the user or the
        # optimizer pick
        for depth in range(2, len(chain) + 1):
            if (base_pattern.node_id, depth) in known_collapses:
                continue
            known_collapses.add((base_pattern.node_id, depth))
            collapsed_patterns.append(
                __create_collapsed_pattern(tg.pet, ast_helper, chain[:depth], loop_variables_by_node_id, depth)
            )

    logger.info("Identified " + str(len(collapsed_patterns)) + " collapsible loop nests.")
    return collapsed_patterns


def __collect_loop_variables(tg: TaskGraph) -> Dict[NodeID, Set[str]]:
    """Collects the loop variables of every loop in the task graph, keyed by the pet node id the
    loop's patterns are reported for (see TaskGraph.__determine_loop_variables)."""
    loop_variables_by_node_id: Dict[NodeID, Set[str]] = dict()
    for node in tg.graph.nodes():
        if not isinstance(node.created_context, LoopParentContext):
            continue
        if node.pet_node_id is None:
            continue
        loop_variables_by_node_id.setdefault(node.pet_node_id, set()).update(
            [name for name, _ in node.created_context.loop_variables]
        )
    return loop_variables_by_node_id


def __collect_collapsible_base_patterns(
    pet: PEGraphX, patterns: List[DoAllInfo | ReductionInfo]
) -> Dict[NodeID, DoAllInfo]:
    """Maps the id of a loop node to the non-collapsed do-all pattern reported for it.

    Loops which carry a reduction are excluded: collapsing changes which iterations share the
    reduction target, so folding a reduction loop into a nest is not semantics preserving.
    """
    # a loop can be reported as a do-all and as a reduction at the same time, in which case the
    # reduction is the trustworthy one
    reduction_node_ids = set([p.node_id for p in patterns if isinstance(p, ReductionInfo)])

    base_patterns_by_loop_node: Dict[NodeID, DoAllInfo] = dict()
    for pattern in patterns:
        if not isinstance(pattern, DoAllInfo):
            continue
        if pattern.collapse_level != 1:
            continue
        if pattern.node_id in reduction_node_ids or len(pattern.reduction) > 0:
            continue
        loop_node = __resolve_loop_node(pet, pattern.node_id)
        if loop_node is None:
            logger.debug("Could not resolve a loop node for pattern at " + str(pattern.start_line))
            continue
        # patterns are iterated in their reported order, so the first one wins deterministically
        base_patterns_by_loop_node.setdefault(loop_node.id, pattern)
    return base_patterns_by_loop_node


def __resolve_loop_node(pet: PEGraphX, node_id: NodeID) -> Optional[LoopNode]:
    """Returns the loop node a pattern reported for `node_id` belongs to.

    Patterns are reported for the entry CU of a loop rather than for the loop node itself, so the
    loop node is usually the CU's parent along a CHILD edge. Handles both cases, as the pet node
    of a loop's task graph node is not guaranteed to be the entry CU.
    """
    node = pet.node_at(node_id)
    if isinstance(node, LoopNode):
        return node
    for source_id, _, _ in in_edges(pet, node_id, EdgeType.CHILD):
        parent = pet.node_at(source_id)
        if isinstance(parent, LoopNode):
            return parent
    return None


def __get_cleanly_nested_chain(
    pet: PEGraphX,
    outermost_loop_node_id: NodeID,
    base_patterns_by_loop_node: Dict[NodeID, DoAllInfo],
) -> List[DoAllInfo]:
    """Walks down from the given loop for as long as the nesting stays clean and every nested loop
    is a collapsible do-all loop. Returns the do-all patterns of the resulting chain, outermost
    first."""
    chain: List[DoAllInfo] = [base_patterns_by_loop_node[outermost_loop_node_id]]
    visited: Set[NodeID] = {outermost_loop_node_id}
    current_loop_node_id = outermost_loop_node_id

    while True:
        inner_loop = __get_cleanly_nested_child_loop(pet, current_loop_node_id)
        if inner_loop is None:
            break
        # the child relation is supposed to form a tree, but do not rely on it for termination
        if inner_loop.id in visited:
            logger.warning("Cyclic child relation detected below loop " + str(current_loop_node_id) + ".")
            break
        if inner_loop.id not in base_patterns_by_loop_node:
            # the nested loop is not a collapsible do-all loop
            break
        visited.add(inner_loop.id)
        chain.append(base_patterns_by_loop_node[inner_loop.id])
        current_loop_node_id = inner_loop.id

    return chain


def __get_cleanly_nested_child_loop(pet: PEGraphX, loop_node_id: NodeID) -> Optional[LoopNode]:
    """Returns the single loop perfectly nested inside the given loop, or None if the given loop
    does not perfectly enclose exactly one loop.

    The nesting is considered clean if the loop contains exactly one nested loop and none of its
    remaining children represents work, i.e. every other child is confined to the enclosing
    loop's header line, the enclosing loop's last line, or the nested loop's header line. Those
    are the CUs which the loop structure itself is made of (condition, increment and the nested
    loop's initialization).
    """
    outer_loop = pet.node_at(loop_node_id)
    children = direct_children(pet, outer_loop)
    nested_loops = [child for child in children if isinstance(child, LoopNode)]
    if len(nested_loops) != 1:
        return None
    nested_loop = nested_loops[0]

    if nested_loop.file_id != outer_loop.file_id:
        return None
    # sanity check on the containment of the nested loop
    if nested_loop.start_line < outer_loop.start_line or nested_loop.end_line > outer_loop.end_line:
        return None

    structural_lines = {outer_loop.start_line, outer_loop.end_line, nested_loop.start_line}
    for child in children:
        if isinstance(child, LoopNode):
            continue
        if child.file_id != outer_loop.file_id:
            return None
        if child.start_line not in structural_lines or child.end_line not in structural_lines:
            # the child represents work located between the two loops, so they are not perfectly
            # nested and must not be collapsed
            return None

    return nested_loop


def __create_collapsed_pattern(
    pet: PEGraphX,
    ast_helper: ASTPatternDetectionHelper,
    chain: List[DoAllInfo],
    loop_variables_by_node_id: Dict[NodeID, Set[str]],
    collapse_level: int,
) -> DoAllInfo:
    """Creates a do-all pattern for the collapsed nest, based on the outermost loop of the chain."""
    outermost_pattern = chain[0]

    # The loop variables of all collapsed loops become the iteration variables of the collapsed
    # construct and are private to it implicitly. They must not appear in any clause: a loop
    # iteration variable of an associated loop is not allowed in a data sharing clause. Note that
    # each loop's own variable is already excluded from its own clauses, but the variables of the
    # enclosing and nested loops are not.
    associated_loop_variables: Set[str] = set()
    for pattern in chain:
        associated_loop_variables.update(loop_variables_by_node_id.get(pattern.node_id, set()))

    first_private: Set[str] = set()
    private: Set[str] = set()
    last_private: Set[str] = set()
    shared: Set[str] = set()
    for pattern in chain:
        first_private.update([str(v.name) for v in pattern.first_private])
        private.update([str(v.name) for v in pattern.private])
        last_private.update([str(v.name) for v in pattern.last_private])
        shared.update([str(v.name) for v in pattern.shared])

    first_private -= associated_loop_variables
    private -= associated_loop_variables
    last_private -= associated_loop_variables
    shared -= associated_loop_variables

    # a variable may have been classified differently by the individual loops, so resolve the
    # union down to a single valid classification
    first_private, private, last_private, shared = merge_classifications(first_private, private, last_private, shared)

    # Drop everything which is not in scope where the pragma will be inserted. This is what keeps
    # variables declared inside the outer loop body - including a nested loop's own index, if it
    # is declared in the loop header - out of the collapsed construct's clauses.
    if ast_helper.is_ast_loaded():
        outermost_node = pet.node_at(outermost_pattern.node_id)
        known_vars = set(
            [v[0] for v in ast_helper.get_variables_at_location(outermost_node.file_id, outermost_node.start_line)]
        )
        first_private, private, last_private, shared = filter_classifications(
            known_vars, first_private, private, last_private, shared
        )

    collapsed = DoAllInfo(pet, pet.node_at(outermost_pattern.node_id))
    collapsed.collapse_level = collapse_level
    collapsed.first_private = __to_variables(first_private)
    collapsed.private = __to_variables(private)
    collapsed.last_private = __to_variables(last_private)
    collapsed.shared = __to_variables(shared)
    collapsed.reduction = []
    collapsed.scheduling_clause = outermost_pattern.scheduling_clause
    collapsed.collapsed_pattern_ids = [p.pattern_id for p in chain]
    collapsed.pattern_tag = collapsed.get_tag()
    return collapsed


def __to_variables(var_names: Set[str]) -> List[Variable]:
    """Converts variable names into the Variable objects the patterns are expected to carry. Sorted
    to keep the reported clauses reproducible across runs."""
    return [Variable(type="UNKNOWN", name=VarName(name), defLine="UNKNOWN") for name in sorted(var_names)]

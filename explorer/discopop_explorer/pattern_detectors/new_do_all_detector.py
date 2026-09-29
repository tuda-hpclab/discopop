# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import itertools
import logging
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple, cast

from discopop_explorer.aliases.LineID import LineID
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.TaskGraph.Aliases import PETNodeID
from discopop_explorer.classes.TaskGraph.ContextTaskGraph import ContextTaskGraph
from discopop_explorer.classes.TaskGraph.Contexts.BranchingParentContext import BranchingParentContext
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.InlinedFunctionContext import InlinedFunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.LoopParentContext import LoopParentContext
from discopop_explorer.classes.TaskGraph.Contexts.TaskParentContext import TaskParentContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.Loops.TGStartLoopNode import TGStartLoopNode
from discopop_explorer.classes.TaskGraph.TGNode import TGNode
from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.pattern_detectors.clause_classification import filter_classifications, merge_classifications
from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo
from discopop_explorer.pattern_detectors.loop_collapse_analysis import identify_collapsible_loop_nests
from discopop_explorer.pattern_detectors.task_parallelism.classes import (
    ParallelRegionInfo,
    TPIType,
    TaskParallelismInfo,
)

from discopop_explorer.utils import classify_loop_variables
from discopop_explorer.functions.PEGraph.queries.data_edge_index import DataEdgeIndex
from discopop_explorer.classes.variable import Variable
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import MemoryRegion, VarName
from discopop_explorer.enums.DepOrigin import DepOrigin
from discopop_explorer.pattern_detectors.reduction_detector import ReductionInfo
from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper
from discopop_library.StatusReporting.console import progress, stage

logger = logging.getLogger("Explorer").getChild("DoAll")


def run_detection(
    pet: PEGraphX, task_graph: TaskGraph, ast_helper: ASTPatternDetectionHelper
) -> List[DoAllInfo | ReductionInfo]:
    logger.info("Starting new do_all and reduction detection...")
    result: List[DoAllInfo | ReductionInfo] = []
    # built once, since the PET graph is not modified during pattern detection
    data_edges = DataEdgeIndex(pet)

    with stage("Identifying doall and reduction loops", 1, total=2):
        result += identify_simple_doall_and_reduction(task_graph, ast_helper, data_edges)
    # collapsible nests are derived from the identified patterns, so this must run afterwards
    with stage("Identifying collapsible loop nests", 2, total=2):
        result += identify_collapsible_loop_nests(task_graph, ast_helper, result)

    show_plot(task_graph)

    return result


def show_plot(tg: TaskGraph) -> None:
    if tg.plottable() == False:
        return

    def draw_plots() -> None:
        ax = tg.create_plot("Context Graph")
        logger.debug("Plotting task graph (context graph)...")
        if len(tg.graph.nodes()) < 500:
            tg.plot_context_graph(ax)

        ax2 = tg.create_plot("Context Debug Graph")
        logger.debug("Plotting task graph (context debug graph)...")
        if len(tg.graph.nodes()) < 500:
            tg.plot_context_debug_graph(ax2)

        ax3 = tg.create_plot("Task Graph")
        logger.debug("Plotting task graph...")
        if len(tg.graph.nodes()) < 500:
            tg.update_plot(ax3)

    def on_filter(filter_text: str) -> None:
        logger.debug("Filter text: " + filter_text)

        # Extra processing here

    tg.clear_visualizer()
    tg.set_filter_callback(on_filter)
    draw_plots()
    tg.run_visualizer()


def collect_reduction_variables(
    reduction_info: List[Tuple[Context, Context, Dependency, Dict[str, str]]],
) -> List[Variable]:
    """builds the deduplicated list of reduction variables described by the reduction
    dependencies which were found for a loop candidate. Depends only on the dependency scan,
    not on the variable classification."""
    reduction_vars: List[Variable] = []
    known_names: Set[VarName] = set()
    # reduction_info is filled while iterating sets of contexts and dependencies, so its order
    # is not reproducible across runs. It is only ever used to derive the reduction variables,
    # which go into the pattern's clauses and its duplicate key, so sorting them by name here
    # makes both reproducible. The operation is part of the key as well: entries now carry the
    # operation of the reduction they describe rather than a single one shared by all of them,
    # so with the name alone, which of two conflicting operations for one variable survives the
    # deduplication below would again depend on the unreproducible order.
    for ri in sorted(reduction_info, key=lambda ri: (ri[2].var_name or "", ri[3].get("operation", ""))):
        if ri[2].var_name is None:
            continue
        var = Variable(type="unknown", name=VarName(ri[2].var_name), defLine="LineNotFound")
        # correct operation
        red_op = ri[3]["operation"]
        logger.debug("RED OP: " + red_op + " var: " + var.name)
        if red_op == ">":
            red_op = "max"
        if red_op == "<":
            red_op = "min"
        var.operation = red_op
        # prevent duplicates
        if var.name in known_names:
            continue
        known_names.add(var.name)
        reduction_vars.append(var)
    return reduction_vars


def get_pattern_key(
    pet_node_id: PETNodeID, loop_parent_ctx: LoopParentContext, reduction_vars: List[Variable]
) -> Optional[Tuple[Any, ...]]:
    """the key identifying the pattern which a loop candidate would register, or None if it
    cannot register one.

    Multiple copies of the same loop exist in the task graph, and a copy whose key has already
    been seen contributes nothing. Everything the key is derived from is known as soon as the
    dependency scan is done - the variable classification only supplies clauses, which are
    assigned to the pattern after its construction - so the duplicate check can, and does, run
    before the classification."""
    if len(reduction_vars) == 0:
        # a DoAllInfo is a function of the node it is built from
        return ("DoAllInfo", pet_node_id)
    if loop_parent_ctx.parent_loop is None:
        # no node to attach a ReductionInfo to
        return None
    # a ReductionInfo additionally covers the reduction variables, which are the only clauses
    # passed to its constructor
    return (
        "ReductionInfo",
        loop_parent_ctx.parent_loop,
        tuple((v.operation, v.name) for v in reduction_vars),
    )


def identify_simple_doall_and_reduction(
    tg: TaskGraph, ast_helper: ASTPatternDetectionHelper, data_edges: DataEdgeIndex
) -> List[DoAllInfo | ReductionInfo]:
    """Analyzes the results of the graph simplification and create simple doall patterns.
    Implementation is fundamentally similar to the original doall detector, but implemented in a more maintainable fashion.
    Checks for clean doall opportunities."""
    patterns: List[DoAllInfo | ReductionInfo] = []
    # everything a pattern's tag is derived from, for the patterns collected in `patterns` - see
    # the duplicate check below. Kept alongside the tags themselves, which are only known once a
    # pattern has been built.
    known_pattern_keys: Set[Tuple[Any, ...]] = set()
    # shared by every candidate, see detect_doall_sharing_clauses
    clause_cache: Dict[ClauseCacheKey, SharingClauses] = dict()
    known_pattern_tags: Set[str] = set()
    logger.info("Identifying trivial doall suggestions.")

    show_plot(tg)

    prevented_loops: Set[NodeID] = set()
    # candidate accounting, reported once at the end. The variable classification is by far the
    # most expensive part of a candidate, so the ratio of classified to skipped candidates is
    # what tells whether this pass is doing avoidable work.
    counts: Dict[str, int] = {
        "candidates": 0,
        "skipped_prevented": 0,
        "skipped_too_few_iterations": 0,
        "skipped_dependency_found": 0,
        "skipped_before_classification": 0,
        "classified": 0,
        "discarded_after_classification": 0,
    }

    # collect the candidates up front so the scan has a known length and can report progress.
    # This pass used to run without any output at all, which on large inputs (deeply nested,
    # heavily duplicated loop nests) is indistinguishable from a hang. The order of
    # tg.graph.nodes() is preserved, so the detection result is unaffected.
    loop_parent_nodes = [n for n in tg.graph.nodes() if isinstance(n.created_context, LoopParentContext)]

    for node in progress(loop_parent_nodes, desc="Checking loops for doall/reduction"):
        # check if node is LoopParent
        if not isinstance(node.created_context, LoopParentContext):
            continue
        counts["candidates"] += 1
        # check if loop is not already preventedvariables
        if node.pet_node_id in prevented_loops:
            counts["skipped_prevented"] += 1
            continue
        # get child iterations. Sorted, because get_contained_contexts returns a set: contexts
        # are hashed by identity, so its iteration order follows memory addresses and varies
        # between runs. The order is observable - detect_doall_sharing_clauses accumulates
        # gep_result_access / ptr_type_access across iterations and classifies each iteration
        # against the accumulated state - so an arbitrary order makes the clauses irreproducible.
        iteration_contexts = sorted(
            (ctx for ctx in node.created_context.get_contained_contexts() if isinstance(ctx, IterationContext)),
            key=lambda ctx: ctx.creation_index,
        )
        if len(iteration_contexts) < 2:
            counts["skipped_too_few_iterations"] += 1
            continue
        # get subtrees of iteration contexts
        subtrees: Dict[IterationContext, Set[Context]] = dict()
        # The iteration each context belongs to. Replaces building, per source iteration, the
        # union of every other iteration's subtree: deciding whether a dependency crosses
        # iterations is then an integer comparison instead of a set membership test against a
        # set which had to be assembled first - quadratically often in the iteration count.
        # A context which belongs to more than one iteration (only reachable through a malformed
        # containment relation) was part of every one of those unions, so it counts as
        # cross-iteration regardless of where the dependency starts.
        iteration_index_of: Dict[Context, int] = dict()
        shared_by_iterations: Set[Context] = set()
        for source_index, ic in enumerate(iteration_contexts):
            subtrees[ic] = ic.get_contained_contexts(inclusive=True)
            # the iteration context itself is a valid target, but not a source - as before
            for ctx in itertools.chain((ic,), subtrees[ic]):
                if iteration_index_of.setdefault(ctx, source_index) != source_index:
                    shared_by_iterations.add(ctx)
        # get loop variables for later check
        loop_variables = node.created_context.loop_variables
        # tested once per dependency below, so not as the list it is stored as
        loop_variable_keys = set(loop_variables)
        # The reduction entries which could apply to this loop, per variable name, each paired
        # with the line its reduction happens on. The loop_line condition only involves the
        # candidate, so it is evaluated here rather than per dependency, and the remaining
        # conditions become a lookup by variable name. The whole entry is kept, not just the
        # line, because the matching one carries the operation the reduction is reported with.
        # A list rather than a set, so that a variable reduced on more than one line inside the
        # same loop matches these in the order of pet.reduction_vars, i.e. reproducibly.
        loop_code_scope = node.created_context.get_code_scope_set(tg.pet)
        reduction_entries_by_var: Dict[str, List[Tuple[LineID, Dict[str, str]]]] = dict()
        for red_var_dict in tg.pet.reduction_vars:
            if red_var_dict["loop_line"] in loop_code_scope:
                reduction_entries_by_var.setdefault(red_var_dict["name"], []).append(
                    (LineID(red_var_dict["reduction_line"]), red_var_dict)
                )
        # check for dependencies
        dependency_found = False
        reduction_info: List[Tuple[Context, Context, Dependency, Dict[str, str]]] = []
        potential_breaking_dependencies: List[Tuple[Context, Context, Dependency]] = []
        for source_index, ic_source in enumerate(iteration_contexts):
            # check for do-all preventing dependencies
            for subnode in subtrees[ic_source]:
                # only needed for reduction candidates, and then at most once per subnode
                subnode_code_scope: Optional[Set[LineID]] = None
                for out_dep_target, dep in subnode.outgoing_dependencies:
                    # WAR dependencies between iterations are non-critical, as they overwrite data and thus can be privatized
                    if dep.etype == EdgeType.DATA and dep.dtype == DepType.WAR:
                        continue

                    if out_dep_target in shared_by_iterations:
                        crosses_iterations = True
                    else:
                        target_iteration_index = iteration_index_of.get(out_dep_target)
                        crosses_iterations = (
                            target_iteration_index is not None and target_iteration_index != source_index
                        )
                    if crosses_iterations:
                        # check if the preventing dependency is a reduction dependency: does a
                        # reduction of this variable happen on a line which both ends of the
                        # dependency cover?
                        matched_reduction_entry: Optional[Dict[str, str]] = None
                        candidate_reduction_entries = reduction_entries_by_var.get(dep.var_name)  # type: ignore[arg-type]
                        if candidate_reduction_entries is not None:
                            if subnode_code_scope is None:
                                subnode_code_scope = subnode.get_code_scope_set(tg.pet)
                            target_code_scope = out_dep_target.get_code_scope_set(tg.pet)
                            for reduction_line, reduction_entry in candidate_reduction_entries:
                                if reduction_line in subnode_code_scope and reduction_line in target_code_scope:
                                    matched_reduction_entry = reduction_entry
                                    break
                        is_reduction_dependency = matched_reduction_entry is not None
                        if matched_reduction_entry is not None:
                            # not a valid doall loop. The operation has to come from the entry
                            # which matched: reporting the last entry of pet.reduction_vars
                            # instead labelled every reduction of a project with the operation of
                            # whichever one happened to be listed last in reduction.txt, e.g.
                            # reduction(max:delta) for a "delta += 1.0" accumulation.
                            reduction_info.append((subnode, out_dep_target, dep, matched_reduction_entry))
                        #                            dependency_found = True
                        #                            break

                        # check for and allow accesses to the loop variable
                        if (dep.var_name, dep.memory_region) in loop_variable_keys or is_reduction_dependency:
                            # dependency on loop variable or reduction variable
                            pass
                        else:
                            # check if dep.origin is static. If so, give it a "second chance", which is tested after classifying variables in the loop.
                            # --> In this case it is a valid doall, if the variable is firstwritten inside the loop
                            # the message is built eagerly, and get_code_scope(inclusive=True) is the
                            # uncached, fully recursive variant. Building it unconditionally in this
                            # innermost loop dominated the whole analysis (measured on LULESH: 88s of
                            # a 146s run, 120M LineID objects), so it is only assembled when a DEBUG
                            # handler will actually consume it.
                            if logger.isEnabledFor(logging.DEBUG):
                                logger.debug(
                                    "Prevents doall: "
                                    + str(dep.dtype)
                                    + " "
                                    + str(dep.source_line)
                                    + " "
                                    + str(dep.sink_line)
                                    + " "
                                    + str(dep.var_name)
                                    + " "
                                    + str(dep.memory_region)
                                    + " "
                                    + "origin: "
                                    + str(dep.origin)
                                    + " "
                                    + "source: "
                                    + str(subnode.get_code_scope(tg.pet, inclusive=True))
                                    + " "
                                    + "out_dep_target: "
                                    + str(out_dep_target.get_code_scope(tg.pet, inclusive=True))
                                    + " "
                                    + "source_ctx: "
                                    + str(ic_source)
                                    + " "
                                    + "target_ctx: "
                                    + str(out_dep_target)
                                )
                            if dep.origin == DepOrigin.DYNAMIC_ANALYSIS:
                                # dependency is trustworthy and definitely breaks doall
                                dependency_found = True
                                break
                            else:
                                # dependency is static and may be too pessimistic.
                                # dependency is not problematic, if the variable is first written in the loop
                                potential_breaking_dependencies.append((ic_source, out_dep_target, dep))
                if dependency_found:
                    break
            if dependency_found:
                break
        if dependency_found:
            # node is not a valid doall loop
            prevented_loops.add(node.pet_node_id)
            counts["skipped_dependency_found"] += 1
            continue

        # Determine which pattern this candidate would register. Both the reduction variables
        # and the resulting key follow from the dependency scan alone (see get_pattern_key), so
        # a redundant copy of a loop can be recognized here instead of after the classification.
        reduction_vars = collect_reduction_variables(reduction_info)
        reduction: Set[str] = set([str(v.name) for v in reduction_vars])
        pattern_key = get_pattern_key(node.pet_node_id, node.created_context, reduction_vars)
        if pattern_key is None or pattern_key in known_pattern_keys:
            # Nothing to register. The classification is still needed when static dependencies
            # are pending, because the second chance check below consumes its firstwritten /
            # init sets and can mark this loop as prevented - which retroactively invalidates
            # the pattern registered by another copy of it.
            if len(potential_breaking_dependencies) == 0:
                counts["skipped_before_classification"] += 1
                continue

        # get contexts contained in loopparent for later check
        loopparent_contained_ctxs = node.created_context.get_contained_contexts(inclusive=True)
        # node is a valid doall loop. Detect data sharing clauses
        logger.debug("CURRENT LOOP: " + str(node.created_context.get_code_scope(tg.pet)))
        counts["classified"] += 1
        firstprivate, private, lastprivate, shared, firstwritten, init = detect_doall_sharing_clauses(
            tg.pet,
            ast_helper,
            data_edges,
            node.pet_node_id,
            iteration_contexts,
            loopparent_contained_ctxs,
            set([v[0] for v in loop_variables]),
            clause_cache,
        )
        # check potential_breaking_dependencies for cases which actually prevent doall
        for src_ctx, dst_ctx, dep in potential_breaking_dependencies:
            if dep.var_name not in firstwritten.union(init).union(reduction):
                # node is not a valid doall loop
                prevented_loops.add(node.pet_node_id)
                # print("LOOP: ", node.created_context.get_code_scope(tg.pet))
                # print("SECOND CHANCEs missed!: ", dep.dtype, dep.var_name)
                continue
            else:
                # static dependency does not actually prevent doall parallelization, as privatization is possible
                pass
        # if len(potential_breaking_dependencies) > 0:
        #    print(
        #        "HERE DUE TO SECOND CHANCEs!: ", [(d[2].dtype, d[2].var_name) for d in potential_breaking_dependencies]
        #    )

        # Register a pattern
        if pattern_key is None or pattern_key in known_pattern_keys:
            # duplicate or unregistrable, as determined before the classification
            counts["discarded_after_classification"] += 1
            continue
        known_pattern_keys.add(pattern_key)
        pattern: DoAllInfo | ReductionInfo
        if len(reduction) == 0:
            # register DoAll pattern
            pattern = DoAllInfo(tg.pet, tg.pet.node_at(node.pet_node_id))
            pattern.first_private = [
                Variable(type="UNKNOWN", name=VarName(v), defLine="UNKNOWN") for v in sorted(firstprivate)
            ]
            pattern.private = [Variable(type="UNKNOWN", name=VarName(v), defLine="UNKNOWN") for v in sorted(private)]
            pattern.last_private = [
                Variable(type="UNKNOWN", name=VarName(v), defLine="UNKNOWN") for v in sorted(lastprivate)
            ]
            pattern.shared = [Variable(type="UNKNOWN", name=VarName(v), defLine="UNKNOWN") for v in sorted(shared)]
        else:
            # register reduction pattern. get_pattern_key rejected a missing parent loop already.
            assert node.created_context.parent_loop is not None
            pattern = ReductionInfo(tg.pet, tg.pet.node_at(node.created_context.parent_loop), reduction=reduction_vars)
            pattern.first_private = [
                Variable(type="UNKNOWN", name=VarName(v), defLine="UNKNOWN")
                for v in sorted(firstprivate)
                if v not in reduction
            ]
            pattern.private = [
                Variable(type="UNKNOWN", name=VarName(v), defLine="UNKNOWN")
                for v in sorted(private)
                if v not in reduction
            ]
            pattern.last_private = [
                Variable(type="UNKNOWN", name=VarName(v), defLine="UNKNOWN")
                for v in sorted(lastprivate)
                if v not in reduction
            ]
            pattern.shared = [
                Variable(type="UNKNOWN", name=VarName(v), defLine="UNKNOWN")
                for v in sorted(shared)
                if v not in reduction
            ]

        # two different nodes can still collide on a tag, so the exact check remains - it is just
        # no longer the one which every duplicate has to be built for.
        if pattern.pattern_tag in known_pattern_tags:
            continue
        known_pattern_tags.add(pattern.pattern_tag)
        patterns.append(pattern)

    logger.info("Doall/reduction candidates: " + ", ".join(k + "=" + str(v) for k, v in counts.items()))

    # clean patterns agains prevented loops
    patterns = [p for p in patterns if p.node_id not in prevented_loops]

    return patterns


SharingClauses = Tuple[Set[str], Set[str], Set[str], Set[str], Set[str], Set[str]]
# what the classification of a loop's variables actually depends on: the loop's CU, the CU
# sequence of each of its iterations, the CUs of the enclosing loop parent and the loop variables
ClauseCacheKey = Tuple[NodeID, Tuple[Tuple[NodeID, ...], ...], FrozenSet[NodeID], FrozenSet[str]]


def detect_doall_sharing_clauses(
    pet: PEGraphX,
    ast_helper: ASTPatternDetectionHelper,
    data_edges: DataEdgeIndex,
    loop_node_id: NodeID,
    iteration_contexts: List[IterationContext],
    loopparent_contained_ctxs: Set[Context],
    loop_variables: Set[str],
    clause_cache: Dict[ClauseCacheKey, SharingClauses],
) -> SharingClauses:
    """classifies variables used inside the iterations and returns the OpenMP data sharing clauses in the following structure:
    (firstprivate, private, lastprivate, shared, firstwritten, init)
    firstwritten and init are not data sharing clauses, but required to validate potential doall-breaking dependencies originating from static information.

    The result is memoized in clause_cache. The classification reaches the contexts it is given
    only to read the CU sequences out of them, so it is a function of those sequences - and the
    task graph holds one copy of a loop per dynamic execution of it, all of which project onto the
    same sequences. The returned sets are shared with the cache and must not be modified.
    """
    logger.debug("-------------------- LOOP START ---------------------")
    # Initialization
    # calculate CUs contained in the loop parent for later use dureing filtering
    contained_tg_nodes_in_loopparent: List[TGNode] = []
    for ctx in loopparent_contained_ctxs:
        contained_tg_nodes_in_loopparent += ctx.contained_nodes
    contained_cu_node_ids_in_loopparent = frozenset(
        [tg.pet_node_id for tg in contained_tg_nodes_in_loopparent if tg.pet_node_id is not None]
    )

    # the CU sequence of every iteration, in execution order - the firstread / firstwritten
    # classification depends on that order
    cu_sequences: List[List[NodeID]] = []
    for it_ctx in iteration_contexts:
        contained_tg_nodes_in_sequence: List[TGNode] = []
        for ctx in it_ctx.get_contained_contexts_in_sequence(pet):
            contained_tg_nodes_in_sequence += ctx.contained_nodes
        cu_sequences.append([tg.pet_node_id for tg in contained_tg_nodes_in_sequence if tg.pet_node_id is not None])

    cache_key: ClauseCacheKey = (
        loop_node_id,
        tuple(tuple(sequence) for sequence in cu_sequences),
        contained_cu_node_ids_in_loopparent,
        frozenset(loop_variables),
    )
    cached_clauses = clause_cache.get(cache_key)
    if cached_clauses is not None:
        return cached_clauses

    # get known variables for source location from AST
    file_id = pet.node_at(loop_node_id).file_id
    line_num = pet.node_at(loop_node_id).start_line

    known_vars_with_types = ast_helper.get_variables_at_location(file_id, line_num)
    known_vars = set([v[0] for v in known_vars_with_types])
    # names of the known variables of pointer or reference type. The types do not depend on the
    # dependency they are looked up for, so this is determined once per loop. Scanning the list of
    # typed variables per dependency instead dominated the entire analysis.
    known_ptr_type_vars = set(
        [
            name
            for name, type_str in known_vars_with_types
            if type_str is not None and ("*" in type_str or "&" in type_str)
        ]
    )
    # names of the variables whose own storage is written somewhere inside this loop, taken from
    # the AST rather than from the dependencies. The profiler names an access that went through a
    # pointer after the pointer, so "rA" labels both the write to rA in "rA = &rv[first_i]" and
    # the read of rv's elements in "rA[i].v" - which makes a pointer that is re-aimed every
    # iteration indistinguishable from a shared array by dependency data alone. Sharing such a
    # variable would race on the pointer itself, so it must never be classified as shared.
    reassigned_vars = ast_helper.get_variables_assigned_in_loop_at(file_id, line_num)

    # shared:
    # - no dependency between iterations
    # private:
    # - no dependency between iterations && first written in iteration && no RAW from outside to inside of loop
    # lastprivate:
    # - no dependency between iterations && read from outside to inside of loop
    # firstprivate:
    # - no dependency between iterations && first read in iterations && written in iteration
    # IMPORTANT: first- and lastprivate can be applied to one variable at the same time!
    # -> Check them independently
    # -> private and lastprivate / firstprivate can NOT be used at the same time.

    # # TODO update
    # reformatted condition to better suit the available data:
    # shared:
    # - outside dependency but not to or from the other iteration
    # private:
    # - outside dependency but not to or from the other iteration && RAW or WAW between first and second access in contained sequence && no RAW from outside to inside of loop
    # lastprivate:
    # - outside dependency but none to or from the other iteration && RAW or WAW between first and second access in contained sequence && read from outside to inside of loop
    # firstprivate:
    # - outside dependency but none to or from the other iteration && outgoing RAW from first access in contained sequence && RAW or WAR exists within

    private: Set[str] = set()
    shared: Set[str] = set()
    lastprivate: Set[str] = set()
    firstprivate: Set[str] = set()
    firstwritten: Set[str] = set()
    init: Set[str] = set()
    gep_result_access: Set[str] = set()
    ptr_type_access: Set[str] = set()

    for contained_cu_node_ids_in_sequence in cu_sequences:
        # the list is iterated in order below - the firstread / firstwritten classification
        # depends on it - so it stays a list. Membership is tested once per dependency, which is a
        # linear scan on a list, so keep a set alongside it for that.
        contained_cu_node_ids_in_sequence_set = set(contained_cu_node_ids_in_sequence)
        # CUs of the enclosing loop which are not part of this iteration's sequence. Both operands
        # are invariant for the whole iteration context, so this is computed once here. Written
        # inside the dependency filters below it would be re-evaluated for every single dependency
        # (a comprehension's condition is not loop-invariant-hoisted), which dominated the entire
        # do-all detection.
        cu_node_ids_outside_sequence = contained_cu_node_ids_in_loopparent - contained_cu_node_ids_in_sequence_set

        # -> get lists of firstwritten, firstread, written, read, read_in, read_out for all iterations.
        # -> use the gathered lists to determine sharing clauses after the loop over iteration contexts
        it_init: Set[str] = set()
        written: Set[str] = set()
        read: Set[str] = set()
        it_firstwritten: Set[str] = set()
        firstread: Set[str] = set()
        data_incoming: Set[str] = set()
        data_outgoing: Set[str] = set()

        for cu_node_id in contained_cu_node_ids_in_sequence:
            incoming_deps = data_edges.in_edges(cu_node_id)
            outgoing_deps = data_edges.out_edges(cu_node_id)

            # TODO:# filter incoming and outgoing deps to ignore nodes within the parent loop
            # TODO: ignore variables defined inside the loop
            # reasone: remove data sharing clauses correlating to loop headers etc.
            incoming_deps = [d for d in incoming_deps if d[0] not in cu_node_ids_outside_sequence]
            outgoing_deps = [d for d in outgoing_deps if d[1] not in cu_node_ids_outside_sequence]

            # outgoing
            #   RAW: cu reads
            #   WAR: cu overwrites
            #   WAW: cu overwrites
            # incoming:
            #   RAW: value is used after cu wrote the value
            #   WAR: value is overwritten after cu read the value
            #   WAW: value is overwritten after cu wrote the value

            for src, dst, dep in outgoing_deps:
                if dep.var_name is None:
                    continue

                # check if dep is access to array type value (or result of pointer arithmetic)
                if dep.is_gep_result_dependency:
                    gep_result_access.add(dep.var_name)
                # check if dep is access to pointer or reference type
                if dep.var_name in known_ptr_type_vars:
                    ptr_type_access.add(dep.var_name)

                if dep.dtype == DepType.RAW:
                    if dep.var_name not in written:
                        firstread.add(dep.var_name)
                    read.add(dep.var_name)
                    if dst not in contained_cu_node_ids_in_sequence_set:
                        data_incoming.add(dep.var_name)
                elif dep.dtype == DepType.WAR:
                    if dep.var_name not in read:
                        it_firstwritten.add(dep.var_name)
                    written.add(dep.var_name)
                elif dep.dtype == DepType.WAW:
                    if dep.var_name not in read:
                        it_firstwritten.add(dep.var_name)
                    written.add(dep.var_name)
                elif dep.dtype == DepType.INIT:
                    if dep.var_name not in read:
                        it_firstwritten.add(dep.var_name)
                    it_init.add(dep.var_name)
                    written.add(dep.var_name)
                else:
                    raise ValueError("Unsupported dependency type: " + str(dep.dtype))

            for src, dst, dep in incoming_deps:
                if dep.var_name is None:
                    continue
                if dep.dtype == DepType.RAW:
                    if dep.var_name not in read:
                        it_firstwritten.add(dep.var_name)
                    written.add(dep.var_name)
                    if src not in contained_cu_node_ids_in_sequence_set:
                        data_outgoing.add(dep.var_name)
                elif dep.dtype == DepType.WAR:
                    if dep.var_name not in written:
                        firstread.add(dep.var_name)
                    read.add(dep.var_name)
                elif dep.dtype == DepType.WAW:
                    if dep.var_name not in read:
                        it_firstwritten.add(dep.var_name)
                    written.add(dep.var_name)
                elif dep.dtype == DepType.INIT:
                    if dep.var_name not in read:
                        it_firstwritten.add(dep.var_name)
                    it_init.add(dep.var_name)
                    written.add(dep.var_name)
                else:
                    raise ValueError("Usupported dependency type: " + str(dep.dtype))

        #            print("cunode -> ", cu_node_id)
        # print("--> in deps:", [(d[2].dtype, d[0], d[2].var_name) for d in incoming_deps])
        # print("--> out_deps: ", [(d[2].dtype, d[1], d[2].var_name) for d in outgoing_deps])
        logger.debug("\t--> written: " + str(written))
        logger.debug("\t--> read: " + str(read))
        logger.debug("\t--> data_incoming: " + str(data_incoming))
        logger.debug("\t--> data_outgoing: " + str(data_outgoing))
        logger.debug("\t--> firstread: " + str(firstread))
        logger.debug("\t--> it_firstwritten: " + str(it_firstwritten))
        logger.debug("\t--> it_init: " + str(it_init))
        logger.debug("\t--> gep_result_access: " + str(gep_result_access))
        logger.debug("\t--> ptr_type_access: " + str(ptr_type_access))
        # dependency between iterations is trivially not possible, as this would invalidate the doall pattern.
        # Classification scheme:
        # shared:
        # - no dependency between iterations
        # private:
        # - no dependency between iterations && first written in iteration && no RAW from outside to inside of loop
        # lastprivate:
        # - no dependency between iterations && read from outside to inside of loop
        # firstprivate:
        # - no dependency between iterations && first read in iterations && written in iteration

        # iterate over all found variable names. use set union via '|'
        it_private: Set[str] = set()
        it_shared: Set[str] = set()
        it_lastprivate: Set[str] = set()
        it_firstprivate: Set[str] = set()

        for var_name in written | read | data_incoming | data_outgoing | firstread | it_firstwritten:
            # ignore loop variables
            if var_name in loop_variables:
                continue
            # -> classification of the variables clauses according to scheme above
            if var_name in written:
                if var_name in data_outgoing:
                    if var_name in ptr_type_access and var_name not in reassigned_vars:
                        it_shared.add(var_name)
                    else:
                        it_lastprivate.add(var_name)
                if var_name in firstread and var_name not in it_init:
                    it_firstprivate.add(var_name)
                if (
                    var_name not in data_outgoing
                    and var_name not in data_incoming
                    and var_name not in it_init
                    and var_name not in it_lastprivate
                    and var_name not in it_firstprivate
                ):
                    if var_name in ptr_type_access and var_name not in reassigned_vars:
                        it_shared.add(var_name)
                    else:
                        it_private.add(var_name)
                if (
                    var_name in data_incoming
                    and var_name in it_firstwritten
                    and var_name not in it_lastprivate
                    and var_name not in it_firstprivate
                    and var_name not in it_private
                ):
                    if var_name in reassigned_vars:
                        # The incoming value cannot be this variable's own: it is written before
                        # it is read inside the iteration. It belongs to the memory reached
                        # through the variable, which stays shared by way of the base pointer it
                        # was derived from, while the variable itself is re-aimed every iteration.
                        it_private.add(var_name)
                    else:
                        it_shared.add(var_name)

                if (
                    var_name not in it_private
                    and var_name not in it_shared
                    and var_name not in it_lastprivate
                    and var_name not in it_firstprivate
                    and var_name in it_init
                    and var_name in ptr_type_access
                    and var_name not in reassigned_vars
                ):
                    # array initializations without immediate successive uses
                    it_shared.add(var_name)

                if (
                    var_name not in it_private
                    and var_name not in it_shared
                    and var_name not in it_lastprivate
                    and var_name not in it_firstprivate
                    and var_name in it_init
                ):
                    it_private.add(var_name)

                assert (
                    var_name in it_lastprivate
                    or var_name in it_firstprivate
                    or var_name in it_private
                    or var_name in it_init
                    or var_name in it_shared
                )
            else:
                # read-only
                if var_name in ptr_type_access:
                    it_shared.add(var_name)
                else:
                    it_firstprivate.add(var_name)
            assert (
                var_name in it_lastprivate
                or var_name in it_firstprivate
                or var_name in it_private
                or var_name in it_shared
                or var_name in it_init
            )

        logger.debug("\tit_private: " + str(it_private))
        logger.debug("\tit_shared: " + str(it_shared))
        logger.debug("\tit_lastprivate: " + str(it_lastprivate))
        logger.debug("\tit_firstprivate: " + str(it_firstprivate))
        logger.debug("\tloop_vars: " + str(loop_variables))

        # save classifications
        private = private.union(it_private)
        shared = shared.union(it_shared)
        lastprivate = lastprivate.union(it_lastprivate)
        firstprivate = firstprivate.union(it_firstprivate)
        firstwritten = firstwritten.union(it_firstwritten)
        init = init.union(it_init)
        logger.debug("----------------------- IT END ------------------")

    # merge classifications
    logger.debug("")
    logger.debug("\tPRE MERGE: private: " + str(private))
    logger.debug("\tPRE MERGE: shared: " + str(shared))
    logger.debug("\tPRE MERGE: lastprivate: " + str(lastprivate))
    logger.debug("\tPRE MERGE: firstprivate: " + str(firstprivate))
    logger.debug("")
    firstprivate, private, lastprivate, shared = merge_classifications(firstprivate, private, lastprivate, shared)
    logger.debug("\tPOST MERGE: private: " + str(private))
    logger.debug("\tPOST MERGE: shared: " + str(shared))
    logger.debug("\tPOST MERGE: lastprivate: " + str(lastprivate))
    logger.debug("\tPOST MERGE: firstprivate: " + str(firstprivate))
    logger.debug("")
    firstprivate, private, lastprivate, shared = filter_classifications(
        known_vars, firstprivate, private, lastprivate, shared
    )
    logger.debug("\tPOST FILTER: private: " + str(private))
    logger.debug("\tPOST FILTER: shared: " + str(shared))
    logger.debug("\tPOST FILTER: lastprivate: " + str(lastprivate))
    logger.debug("\tPOST FILTER: firstprivate: " + str(firstprivate))
    logger.debug("---------------------------- LOOP END --------------------")
    logger.debug("")
    result: SharingClauses = (firstprivate, private, lastprivate, shared, firstwritten, init)
    clause_cache[cache_key] = result
    return result

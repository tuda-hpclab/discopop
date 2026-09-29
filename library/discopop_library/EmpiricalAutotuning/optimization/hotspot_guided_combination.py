# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Deterministic, hotspot-guided selection of parallelization suggestions.

The search walks the code regions that dominate the measured runtime first and
descends into nested regions only where the enclosing region did not pay off. Every
decision is derived from sorted data, so two runs on a machine with stable timings
produce the same sequence of measured configurations.

Ranking uses the hotspot analyzer's own classification as the primary key. That
classification already combines both quantities of interest: ``hotness`` is derived
from ``topAvr`` (average runtime above the mean of all executed regions) and
``topRatio`` (scaling indicator above the mean), with YES = both, MAYBE = exactly
one, NO = neither. Within a class, regions are ordered by ``maxVal`` -- the longest
single profiling run, i.e. the largest-input regime where parallel speedup matters --
rather than by ``avr``, which dilutes a large run against a small one.
"""

import time
from dataclasses import dataclass, field
from logging import Logger
from typing import Callable, Dict, List, Optional, Sequence, Set, Tuple, cast

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes

from discopop_library.EmpiricalAutotuning.ArgumentClasses import AutotunerArguments
from discopop_library.EmpiricalAutotuning.optimization.coordinate_descent_combination import (
    execute_coordinate_descent_combination,
)
from discopop_library.EmpiricalAutotuning.Classes.CodeConfiguration import CodeConfiguration
from discopop_library.EmpiricalAutotuning.Classes.ExecutionResult import ExecutionResult
from discopop_library.EmpiricalAutotuning.Types import SUGGESTION_ID
from discopop_library.EmpiricalAutotuning.output.intermediate import show_info_stats
from discopop_library.EmpiricalAutotuning.output.progress import DebugStatEntry
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType, parse_hotspot_types
from discopop_library.HostpotLoader.detailed_hotspot_loader import (
    HotspotRegionInfo,
    hotspots_are_degenerate,
    load_detailed_hotspots,
)
from discopop_library.HostpotLoader.hostpot_loader import AVERAGE_RUNTIME, FILEID, NAME, STARTLINE
from discopop_library.result_classes.DetectionResult import DetectionResult

# A configuration is a set of suggestions, so (1, 2) and (2, 1) describe the same code.
CONFIGURATION = Tuple[SUGGESTION_ID, ...]
# Identity of a candidate region: (file id, start line, end line).
REGION_KEY = Tuple[int, int, int]

# Order the hotspot classes by the strength of the evidence they represent.
HOTNESS_TIER: Dict[HotspotType, int] = {HotspotType.YES: 0, HotspotType.MAYBE: 1, HotspotType.NO: 2}


@dataclass
class CandidateRegion:
    """A hot loop together with the suggestions that parallelize it.

    Several suggestions may target the same loop (e.g. a do-all and the collapsed
    variants derived from it); they are *alternatives*, and at most one of them ends
    up in the final configuration.
    """

    file_id: int
    start_line: int
    end_line: int
    node_id: Optional[NodeID]
    hotness: HotspotType
    avr: float
    max_val: float
    ratio: float
    suggestion_ids: List[SUGGESTION_ID] = field(default_factory=list)

    @property
    def key(self) -> REGION_KEY:
        return (self.file_id, self.start_line, self.end_line)

    def label(self) -> str:
        return (
            str(self.file_id)
            + ":"
            + str(self.start_line)
            + "-"
            + str(self.end_line)
            + " ("
            + self.hotness.name
            + ", max="
            + str(round(self.max_val, 3))
            + "s, suggestions="
            + str(self.suggestion_ids)
            + ")"
        )


def canonical_configuration(suggestion_ids: Sequence[SUGGESTION_ID]) -> CONFIGURATION:
    """Normalize a selection of suggestions into a cache key."""
    return tuple(sorted(set(suggestion_ids)))


def rank_key(region: CandidateRegion) -> Tuple[int, float, int, int, int]:
    """Total order over candidate regions: hottest class first, then longest run.

    The trailing (file id, start line, first suggestion id) makes the order total, so
    it never depends on dictionary or set iteration. For the loops of one nest, which
    report identical inclusive runtimes, the start line decides -- putting the
    outermost loop first, which is the order the descent below wants anyway.
    """
    return (
        HOTNESS_TIER[region.hotness],
        -region.max_val,
        region.file_id,
        region.start_line,
        min(region.suggestion_ids) if region.suggestion_ids else 0,
    )


def improves(runtime: float, best_runtime: float, noise_threshold: float) -> bool:
    """True if ``runtime`` beats ``best_runtime`` by more than the noise threshold.

    Requiring a *relative* improvement keeps the search reproducible on a machine
    whose timings fluctuate by a little: a difference that small can no longer flip a
    decision in either direction.
    """
    return runtime < best_runtime * (1.0 - noise_threshold)


def build_candidate_regions(
    detection_result: DetectionResult,
    hotspot_regions: Sequence[HotspotRegionInfo],
    considered_types: Sequence[HotspotType],
    min_share: float,
) -> List[CandidateRegion]:
    """Map hot loops to the suggestions that parallelize them and rank the result.

    Regions contributing less than ``min_share`` of the hottest region's ``maxVal``
    are dropped: every remaining region costs a full compile-and-execute cycle, and
    parallelizing a loop that accounts for a fraction of a percent of the runtime
    cannot pay for that.
    """
    patterns_by_start = __patterns_by_start_position(detection_result)
    patterns_by_file = __patterns_by_file(detection_result)
    loop_nodes = __loop_nodes_by_start_position(detection_result)

    regions: List[CandidateRegion] = []
    for hotspot in sorted(hotspot_regions, key=lambda h: (h.file_id, h.start_line, h.csid)):
        if hotspot.node_type != HotspotNodeType.LOOP:
            continue
        if hotspot.hotness not in considered_types:
            continue

        # Prefer the exact start-line match; a suggestion sits on the loop it
        # parallelizes. Only if no suggestion starts there, fall back to the
        # containment rule used by get_patterns_by_hotspot_type().
        matches = patterns_by_start.get((hotspot.file_id, hotspot.start_line), [])
        if not matches:
            matches = [
                pattern
                for pattern in patterns_by_file.get(hotspot.file_id, [])
                if pattern[1] <= hotspot.start_line <= pattern[2]
            ]
        if not matches:
            continue

        for pattern_id, start_line, end_line in sorted(matches):
            # A suggestion records the loop's start position as both its start and its
            # end line, and points at the loop's entry CU rather than the loop itself.
            # The LoopNode supplies what the nesting analysis needs: the real line span
            # and the graph node whose subtree contains the nested loops.
            loop_node = loop_nodes.get(str(hotspot.file_id) + ":" + str(start_line))
            node_id: Optional[NodeID] = None
            if loop_node is not None:
                node_id = loop_node.id
                end_line = max(end_line, __line_of(str(loop_node.end_position())))
            regions.append(
                CandidateRegion(
                    file_id=hotspot.file_id,
                    start_line=start_line,
                    end_line=end_line,
                    node_id=node_id,
                    hotness=hotspot.hotness,
                    avr=hotspot.avr,
                    max_val=hotspot.max_val,
                    ratio=hotspot.ratio,
                    suggestion_ids=[pattern_id],
                )
            )

    merged = __merge_regions(regions)
    __attach_node_ids(detection_result, merged)
    filtered = __filter_by_share(merged, min_share)
    return sorted(filtered, key=rank_key)


def __patterns_by_start_position(
    detection_result: DetectionResult,
) -> Dict[Tuple[int, int], List[Tuple[SUGGESTION_ID, int, int]]]:
    result: Dict[Tuple[int, int], List[Tuple[SUGGESTION_ID, int, int]]] = dict()
    for pattern_id, file_id, start_line, end_line in __applicable_patterns(detection_result):
        result.setdefault((file_id, start_line), []).append((pattern_id, start_line, end_line))
    return result


def __patterns_by_file(detection_result: DetectionResult) -> Dict[int, List[Tuple[SUGGESTION_ID, int, int]]]:
    result: Dict[int, List[Tuple[SUGGESTION_ID, int, int]]] = dict()
    for pattern_id, file_id, start_line, end_line in __applicable_patterns(detection_result):
        result.setdefault(file_id, []).append((pattern_id, start_line, end_line))
    return result


def __applicable_patterns(detection_result: DetectionResult) -> List[Tuple[SUGGESTION_ID, int, int, int]]:
    """All patterns that may be applied on their own, as (id, file id, start, end)."""
    result: List[Tuple[SUGGESTION_ID, int, int, int]] = []
    for pattern_type in sorted(detection_result.patterns.__dict__):
        for pattern in detection_result.patterns.__dict__[pattern_type]:
            if not getattr(pattern, "applicable_pattern", False):
                continue
            # A pattern that is not standalone has been swallowed by an inflated
            # parallel region; applying it by itself would duplicate that region's
            # pragmas.
            if not getattr(pattern, "standalone_pattern", True):
                continue
            try:
                file_id = int(str(pattern.start_line).split(":")[0])
                start_line = int(str(pattern.start_line).split(":")[1])
                end_line = int(str(pattern.end_line).split(":")[1])
            except (IndexError, ValueError):
                continue
            result.append((pattern.pattern_id, file_id, start_line, end_line))
    return sorted(result)


def __merge_regions(regions: Sequence[CandidateRegion]) -> List[CandidateRegion]:
    """Collapse regions that describe the same source range into one with alternatives."""
    merged: Dict[REGION_KEY, CandidateRegion] = dict()
    for region in regions:
        existing = merged.get(region.key)
        if existing is None:
            merged[region.key] = region
            continue
        for suggestion_id in region.suggestion_ids:
            if suggestion_id not in existing.suggestion_ids:
                existing.suggestion_ids.append(suggestion_id)
        # Keep the strongest evidence and the largest measurement seen for the range.
        if HOTNESS_TIER[region.hotness] < HOTNESS_TIER[existing.hotness]:
            existing.hotness = region.hotness
        existing.max_val = max(existing.max_val, region.max_val)
        existing.avr = max(existing.avr, region.avr)
        existing.ratio = max(existing.ratio, region.ratio)
    for region in merged.values():
        region.suggestion_ids.sort()
    return [merged[key] for key in sorted(merged)]


def __line_of(line_id: str) -> int:
    """Line number of a "<file id>:<line>" line id."""
    return int(line_id.split(":")[1])


def __loop_nodes_by_start_position(detection_result: DetectionResult) -> Dict[str, LoopNode]:
    """Index the PET's loop nodes by their start position, as "<file id>:<line>".

    A suggestion's ``start_line`` is the start position of the loop it parallelizes, so
    this maps a candidate region onto the loop node it belongs to.
    """
    pet = getattr(detection_result, "pet", None)
    if pet is None:
        return dict()
    result: Dict[str, LoopNode] = dict()
    for node in all_nodes(pet, LoopNode):
        key = str(node.start_position())
        previous = result.get(key)
        # Two loops can start on the same line; keep the enclosing one.
        if previous is None or __node_span(node) > __node_span(previous):
            result[key] = node
    return result


def __node_span(node: LoopNode) -> int:
    return __line_of(str(node.end_position())) - __line_of(str(node.start_position()))


def __attach_node_ids(detection_result: DetectionResult, regions: Sequence[CandidateRegion]) -> None:
    """Fall back to the suggestion's own PET node where no loop node was resolved."""
    node_id_by_pattern: Dict[SUGGESTION_ID, NodeID] = dict()
    for pattern_type in sorted(detection_result.patterns.__dict__):
        for pattern in detection_result.patterns.__dict__[pattern_type]:
            node_id = getattr(pattern, "node_id", None)
            if node_id is not None:
                node_id_by_pattern[pattern.pattern_id] = node_id
    for region in regions:
        if region.node_id is not None:
            continue
        for suggestion_id in region.suggestion_ids:
            if suggestion_id in node_id_by_pattern:
                region.node_id = node_id_by_pattern[suggestion_id]
                break


def __filter_by_share(regions: Sequence[CandidateRegion], min_share: float) -> List[CandidateRegion]:
    if not regions or min_share <= 0.0:
        return list(regions)
    hottest = max(region.max_val for region in regions)
    if hottest <= 0.0:
        return list(regions)
    return [region for region in regions if region.max_val >= hottest * min_share]


def build_exclusion_map(detection_result: DetectionResult) -> Dict[SUGGESTION_ID, Set[SUGGESTION_ID]]:
    """Suggestions that must not be applied together with a given suggestion.

    Two sources, both already produced by the explorer but so far unused by the tuner:
    ``collapsed_pattern_ids`` names the do-all patterns folded into a collapsed one
    (a pragma between two collapsed loops does not compile), and
    ``contains_patterns`` names the patterns an inflated parallel region swallowed.
    """
    result: Dict[SUGGESTION_ID, Set[SUGGESTION_ID]] = dict()
    for pattern_type in sorted(detection_result.patterns.__dict__):
        for pattern in detection_result.patterns.__dict__[pattern_type]:
            excluded: Set[SUGGESTION_ID] = set()
            for attribute in ["collapsed_pattern_ids", "contains_patterns"]:
                excluded.update(getattr(pattern, attribute, []) or [])
            excluded.discard(pattern.pattern_id)
            if excluded:
                result[pattern.pattern_id] = excluded
    return result


def build_containment_forest(
    regions: Sequence[CandidateRegion],
    detection_result: DetectionResult,
) -> Tuple[List[CandidateRegion], Dict[REGION_KEY, List[CandidateRegion]]]:
    """Arrange the candidate regions into a nesting forest.

    Hotspot runtimes are inclusive, so a hot loop and every loop nested inside it
    report nearly the same time. Parallelizing the outer one usually makes the inner
    ones pointless (and nesting parallel regions costs more than it gains), so the
    search needs to know which region encloses which.

    Containment is decided on the PET graph, following CHILD *and* CALLSNODE edges so
    that a loop nested inside a called function counts as contained as well. Line
    ranges are the fallback when a region has no usable PET node.
    """
    reachable = __reachable_node_ids(detection_result, regions)

    children: Dict[REGION_KEY, List[CandidateRegion]] = dict()
    parent_of: Dict[REGION_KEY, CandidateRegion] = dict()

    ordered = sorted(regions, key=lambda r: r.key)
    for inner in ordered:
        best_parent: Optional[CandidateRegion] = None
        for outer in ordered:
            if outer.key == inner.key:
                continue
            if not __contains(outer, inner, reachable):
                continue
            # The direct parent is the tightest enclosing region.
            if best_parent is None or __span(outer) < __span(best_parent):
                best_parent = outer
        if best_parent is not None:
            parent_of[inner.key] = best_parent
            children.setdefault(best_parent.key, []).append(inner)

    for key in children:
        children[key].sort(key=rank_key)

    roots = sorted([region for region in ordered if region.key not in parent_of], key=rank_key)
    return roots, children


def __span(region: CandidateRegion) -> int:
    return region.end_line - region.start_line


def __contains(outer: CandidateRegion, inner: CandidateRegion, reachable: Dict[REGION_KEY, Set[NodeID]]) -> bool:
    outer_reachable = reachable.get(outer.key)
    if outer_reachable is not None and inner.node_id is not None:
        if inner.node_id in outer_reachable:
            return True
        # The PET answer is authoritative for regions that have nodes; asking the line
        # ranges as well would re-introduce the false positives it avoids.
        if outer.node_id is not None:
            return False
    if outer.file_id != inner.file_id:
        return False
    return outer.start_line <= inner.start_line and inner.end_line <= outer.end_line and __span(outer) > __span(inner)


def __reachable_node_ids(
    detection_result: DetectionResult, regions: Sequence[CandidateRegion]
) -> Dict[REGION_KEY, Set[NodeID]]:
    """Node ids reachable from each region over CHILD and CALLSNODE edges.

    Same semantics as ``subtree_of_type(pet, node, ignore_called_functions=False)``,
    but iterative: the recursive variant overflows the stack on large call graphs.
    """
    pet = getattr(detection_result, "pet", None)
    if pet is None:
        return dict()

    edge_types = [EdgeType.CHILD, EdgeType.CALLSNODE]
    result: Dict[REGION_KEY, Set[NodeID]] = dict()
    for region in regions:
        if region.node_id is None:
            continue
        try:
            pet.node_at(region.node_id)
        except Exception:
            continue
        visited: Set[NodeID] = {region.node_id}
        queue: List[NodeID] = [region.node_id]
        while queue:
            current = queue.pop()
            try:
                edges = out_edges(pet, current, edge_types)
            except Exception:
                continue
            for _, target, _ in edges:
                if target in visited:
                    continue
                visited.add(target)
                queue.append(target)
        visited.discard(region.node_id)
        result[region.key] = visited
    return result


@dataclass
class MeasurementCache:
    """Remembers every measured configuration for the duration of one search.

    Besides saving compile-and-execute cycles, this is what keeps the search
    reproducible: a configuration that is reached twice contributes the very same
    runtime to both decisions instead of two independent noisy samples.
    """

    runtime: Dict[CONFIGURATION, float] = field(default_factory=dict)
    valid: Dict[CONFIGURATION, bool] = field(default_factory=dict)
    measurements: int = 0

    def known(self, configuration: CONFIGURATION) -> bool:
        return configuration in self.runtime

    def store(self, configuration: CONFIGURATION, runtime: float, valid: bool, measured: bool = True) -> None:
        """Remember a result. ``measured`` is False for results that cost no execution,
        so that the measurement budget only ever counts real compile-and-execute cycles."""
        self.runtime[configuration] = runtime
        self.valid[configuration] = valid
        if measured:
            self.measurements += 1


class SearchBudgetExhausted(Exception):
    """Raised to unwind the search once the configured measurement budget is used up."""


def _evaluate(
    suggestion_ids: Sequence[SUGGESTION_ID],
    cache: MeasurementCache,
    reference_configuration: CodeConfiguration,
    arguments: AutotunerArguments,
    timeout_after: float,
    get_unique_configuration_id: Callable[[], int],
    debug_stats: List[DebugStatEntry],
    logger: Logger,
    deadline: Optional[float],
) -> Tuple[float, bool]:
    """Compile and run one configuration. Returns (runtime, is_valid)."""
    configuration = canonical_configuration(suggestion_ids)
    if cache.known(configuration):
        return cache.runtime[configuration], cache.valid[configuration]

    if not configuration:
        reference_result = cast(ExecutionResult, reference_configuration.execution_result)
        valid = (
            reference_result.return_code == 0 and reference_result.result_valid and reference_result.thread_sanitizer
        )
        cache.store(configuration, reference_result.runtime, valid, measured=False)
        return reference_result.runtime, valid

    if arguments.max_measurements > 0 and cache.measurements >= arguments.max_measurements:
        raise SearchBudgetExhausted()
    if deadline is not None and time.time() > deadline:
        raise SearchBudgetExhausted()

    tmp_config = reference_configuration.create_copy(arguments, "par_settings.json", get_unique_configuration_id)
    # A conflicting patch would otherwise be measured as if it had been applied, which
    # would make a rejected suggestion look merely useless instead of inapplicable.
    patch_result = tmp_config.apply_suggestions(arguments, list(configuration))
    if patch_result is not None and patch_result.failure:
        logger.info(
            "Could not apply suggestions "
            + str(list(configuration))
            + ". "
            + patch_result.summary()
            + " Treating the configuration as failed."
        )
        failed_suggestions = patch_result.unapplied_ids
        debug_stats.append((list(configuration), 0.0, 1, False, False, tmp_config.root_path, failed_suggestions))
        if not arguments.skip_cleanup:
            tmp_config.deleteFolder()
        cache.store(configuration, 0.0, False)
        return 0.0, False

    tmp_config.execute(arguments, timeout=timeout_after, thread_count=arguments.thread_count)
    if not arguments.skip_cleanup:
        tmp_config.deleteFolder()

    exec_res = cast(ExecutionResult, tmp_config.execution_result)
    debug_stats.append(
        (
            list(configuration),
            exec_res.runtime,
            exec_res.return_code,
            exec_res.result_valid,
            exec_res.thread_sanitizer,
            tmp_config.root_path,
            exec_res.failed_suggestions,
        )
    )
    is_valid = exec_res.return_code == 0 and exec_res.result_valid and exec_res.thread_sanitizer
    cache.store(configuration, exec_res.runtime, is_valid)
    return exec_res.runtime, is_valid


def execute_hotspot_guided_combination(
    detection_result: DetectionResult,
    hotspot_information: Dict[HotspotType, List[Tuple[FILEID, STARTLINE, HotspotNodeType, NAME, AVERAGE_RUNTIME]]],
    logger: Logger,
    time_limit_s: int,
    reference_configuration: CodeConfiguration,
    arguments: AutotunerArguments,
    timeout_after: float,
    debug_stats: List[DebugStatEntry],
    get_unique_configuration_id: Callable[[], int],
) -> None:
    logger.info("Executing hotspot-guided region descent.")

    # -- Phase 0: this algorithm is only meaningful with hotspot measurements ------
    # Without them the descent has no order to walk, but "produce nothing and
    # exit 0" is the worst possible answer: hotspot detection can fail silently
    # (an instrumented run that writes no hotspot_result_*.txt leaves the
    # analyzer with an empty Hotspots.json, and neither reports an error), so a
    # caller sees a completed auto-tuning whose result is the unmodified
    # program. Hand over to the hotspot-free coordinate descent instead, which
    # treats every suggestion as a candidate when no classification exists.
    hotspot_regions = load_detailed_hotspots(arguments.dot_dp_path)
    fallback_reason: Optional[str] = None
    if not hotspot_regions:
        fallback_reason = "no hotspot detection results were found"
    elif not [region for region in hotspot_regions if region.node_type == HotspotNodeType.LOOP]:
        fallback_reason = "the hotspot detection results contain no loops"
    if fallback_reason is not None:
        __fall_back_to_coordinate_descent(
            logger,
            fallback_reason,
            detection_result,
            hotspot_information,
            time_limit_s,
            reference_configuration,
            arguments,
            timeout_after,
            debug_stats,
            get_unique_configuration_id,
        )
        return
    if hotspots_are_degenerate(hotspot_regions):
        logger.warning(
            "All hotspot regions report the neutral scaling ratio 0.5, which means the project "
            "was profiled with a single input. Regions are still ranked by runtime, but the "
            "scaling behaviour cannot contribute to the ranking."
        )

    try:
        considered_types = parse_hotspot_types(arguments.hotspot_types)
    except ValueError as error:
        logger.error("Could not parse --hotspot-types '" + arguments.hotspot_types + "': " + str(error))
        return

    # -- Phase 1 + 2: candidate regions, ranked --------------------------------------
    regions = build_candidate_regions(detection_result, hotspot_regions, considered_types, arguments.hs_min_share)
    if not regions:
        # Hotspots exist, but none of them is something this detection result can
        # parallelize, so the descent has nothing to descend into either. Same
        # reasoning as in Phase 0: a search that can still run beats an empty
        # answer that looks like a completed one.
        __fall_back_to_coordinate_descent(
            logger,
            "no suggestion targets any of the considered hot loops",
            detection_result,
            hotspot_information,
            time_limit_s,
            reference_configuration,
            arguments,
            timeout_after,
            debug_stats,
            get_unique_configuration_id,
        )
        return
    __log_region_overview(logger, regions, arguments.hs_min_share)

    # -- Phase 3: nesting ------------------------------------------------------------
    roots, children = build_containment_forest(regions, detection_result)
    exclusions = build_exclusion_map(detection_result)
    logger.info("Nesting forest: " + str(len(roots)) + " root region(s) of " + str(len(regions)) + " total.")

    cache = MeasurementCache()
    reference_runtime = cast(ExecutionResult, reference_configuration.execution_result).runtime
    cache.store(tuple(), reference_runtime, True, measured=False)

    accepted: List[SUGGESTION_ID] = []
    best_runtime = reference_runtime
    excluded: Set[SUGGESTION_ID] = set()
    deadline = time.time() + time_limit_s if time_limit_s > 0 else None

    evaluate = lambda config: _evaluate(
        config,
        cache,
        reference_configuration,
        arguments,
        timeout_after,
        get_unique_configuration_id,
        debug_stats,
        logger,
        deadline,
    )

    logger.info(
        "Starting descent over "
        + str(len(regions))
        + " hot region(s). Baseline runtime: "
        + str(round(best_runtime, 3))
        + "s. Press CTRL+C to stop the search."
    )

    # -- Phase 4: forward descent, outermost region first ----------------------------
    stopped_early = False
    try:
        accepted, best_runtime = __forward_descent(
            roots, children, exclusions, accepted, best_runtime, excluded, evaluate, arguments, logger
        )
    except SearchBudgetExhausted:
        stopped_early = True
        logger.warning(
            "Search budget exhausted after "
            + str(cache.measurements)
            + " measurement(s). The result is not necessarily reproducible."
        )
    except KeyboardInterrupt:
        stopped_early = True
        logger.info("Manually stopped the descent.")

    # -- Phase 5: removal refinement -------------------------------------------------
    if accepted and not stopped_early and not arguments.skip_removal_pass:
        try:
            accepted, best_runtime = __removal_pass(accepted, best_runtime, evaluate, arguments, logger)
        except SearchBudgetExhausted:
            logger.warning("Search budget exhausted during the removal pass.")
        except KeyboardInterrupt:
            logger.info("Manually stopped the removal pass.")

    logger.info(
        "Hotspot-guided descent complete after "
        + str(cache.measurements)
        + " measurement(s). Final configuration: "
        + str(sorted(accepted))
        + " at "
        + str(round(best_runtime, 3))
        + "s (baseline "
        + str(round(reference_runtime, 3))
        + "s)."
    )
    show_info_stats(debug_stats, logger)


def __forward_descent(
    roots: Sequence[CandidateRegion],
    children: Dict[REGION_KEY, List[CandidateRegion]],
    exclusions: Dict[SUGGESTION_ID, Set[SUGGESTION_ID]],
    accepted: List[SUGGESTION_ID],
    best_runtime: float,
    excluded: Set[SUGGESTION_ID],
    evaluate: Callable[[Sequence[SUGGESTION_ID]], Tuple[float, bool]],
    arguments: AutotunerArguments,
    logger: Logger,
) -> Tuple[List[SUGGESTION_ID], float]:
    """Try the hottest available region; descend into its nested regions only on failure.

    Accepting a region prunes its whole subtree: the inner loops are already covered by
    the enclosing parallel region, so measuring them would cost a compile-and-execute
    cycle each for a change that can only add nesting overhead.
    """
    worklist: List[CandidateRegion] = sorted(roots, key=rank_key)
    visited: Set[REGION_KEY] = set()

    while worklist:
        region = worklist.pop(0)
        if region.key in visited:
            continue
        visited.add(region.key)

        alternatives = [suggestion_id for suggestion_id in region.suggestion_ids if suggestion_id not in excluded]
        if not alternatives:
            logger.info("Skipping " + region.label() + ": all alternatives are excluded.")
            continue

        logger.info("Region " + region.label())
        winner: Optional[SUGGESTION_ID] = None
        winner_runtime = best_runtime
        for suggestion_id in alternatives:
            runtime, is_valid = evaluate(accepted + [suggestion_id])
            if is_valid and improves(runtime, winner_runtime, arguments.noise_threshold):
                winner = suggestion_id
                winner_runtime = runtime

        if winner is None:
            logger.info("--- no alternative improved the runtime; descending into nested regions.")
            for child in children.get(region.key, []):
                if child.key not in visited:
                    worklist.append(child)
            worklist.sort(key=rank_key)
            continue

        accepted.append(winner)
        best_runtime = winner_runtime
        excluded.update(exclusions.get(winner, set()))
        # Everything nested inside an accepted region stays sequential.
        __mark_subtree_visited(region, children, visited)
        logger.info(
            "--- accepted suggestion "
            + str(winner)
            + " -> "
            + str(round(best_runtime, 3))
            + "s; skipping its nested regions."
        )

    return accepted, best_runtime


def __mark_subtree_visited(
    region: CandidateRegion, children: Dict[REGION_KEY, List[CandidateRegion]], visited: Set[REGION_KEY]
) -> None:
    queue = list(children.get(region.key, []))
    while queue:
        current = queue.pop()
        if current.key in visited:
            continue
        visited.add(current.key)
        queue.extend(children.get(current.key, []))


def __removal_pass(
    accepted: List[SUGGESTION_ID],
    best_runtime: float,
    evaluate: Callable[[Sequence[SUGGESTION_ID]], Tuple[float, bool]],
    arguments: AutotunerArguments,
    logger: Logger,
) -> Tuple[List[SUGGESTION_ID], float]:
    """Drop accepted suggestions that turned out to be harmful in the final combination.

    A suggestion accepted early was judged against a configuration that has grown
    since, so this pass revisits each one exactly once, coldest region first.
    """
    logger.info("Refinement: checking whether any accepted suggestion can be removed.")
    current = list(accepted)
    for suggestion_id in reversed(list(accepted)):
        candidate = [entry for entry in current if entry != suggestion_id]
        if not candidate:
            continue
        runtime, is_valid = evaluate(candidate)
        if is_valid and improves(runtime, best_runtime, arguments.noise_threshold):
            logger.info("--- removed suggestion " + str(suggestion_id) + " -> " + str(round(runtime, 3)) + "s")
            current = candidate
            best_runtime = runtime
    return current, best_runtime


def __fall_back_to_coordinate_descent(
    logger: Logger,
    reason: str,
    detection_result: DetectionResult,
    hotspot_information: Dict[HotspotType, List[Tuple[FILEID, STARTLINE, HotspotNodeType, NAME, AVERAGE_RUNTIME]]],
    time_limit_s: int,
    reference_configuration: CodeConfiguration,
    arguments: AutotunerArguments,
    timeout_after: float,
    debug_stats: List[DebugStatEntry],
    get_unique_configuration_id: Callable[[], int],
) -> None:
    """Run the hotspot-free search in place of the descent, and say so.

    Coordinate descent is the substitute because it is the closest thing to what
    -A 6 was chosen for: it searches combinations rather than measuring
    suggestions one at a time, and it is deterministic. With no classification
    loaded it considers every suggestion a candidate (see
    HostpotLoader.utilities.get_patterns_by_hotspot_type), which is exactly the
    interpretation "we have no hotspot information" calls for.

    Reported at ERROR, above the default log level, because the result that
    follows was not produced by the algorithm the caller asked for -- and
    because the usual cause, a hotspot detection run that silently produced
    nothing, is worth fixing rather than working around run after run.
    """
    logger.error(
        "The hotspot-guided region descent requires hotspot detection results, but "
        + reason
        + ".\nFalling back to coordinate descent (-A 5), which does not need them. The result "
        + "below was NOT produced by -A 6.\nTo use the descent, run hotspot detection "
        + "(discopop_hotspot_analyzer) for at least two input sizes; an empty Hotspots.json "
        + "usually means the instrumented run wrote no hotspot_result_*.txt files."
    )
    execute_coordinate_descent_combination(
        detection_result,
        hotspot_information,
        logger,
        time_limit_s,
        reference_configuration,
        arguments,
        timeout_after,
        debug_stats,
        get_unique_configuration_id,
    )


def __log_region_overview(logger: Logger, regions: Sequence[CandidateRegion], min_share: float) -> None:
    logger.info(
        "Considering "
        + str(len(regions))
        + " hot region(s) contributing at least "
        + str(round(min_share * 100, 2))
        + "% of the hottest region's runtime."
    )
    for hotspot_type in [HotspotType.YES, HotspotType.MAYBE, HotspotType.NO]:
        tier = [region for region in regions if region.hotness == hotspot_type]
        if not tier:
            continue
        # Log the boundaries so a hot but flat-scaling loop that landed in MAYBE, and is
        # therefore visited after every YES region, is visible rather than surprising.
        logger.info(
            "--- "
            + hotspot_type.name
            + ": "
            + str(len(tier))
            + " region(s), max runtime "
            + str(round(max(region.max_val for region in tier), 3))
            + "s .. "
            + str(round(min(region.max_val for region in tier), 3))
            + "s"
        )

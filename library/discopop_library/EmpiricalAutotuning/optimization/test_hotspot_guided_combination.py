# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Unit tests for the hotspot-guided region descent.

These cover the measurement-free parts of the algorithm: ranking, candidate
selection, the nesting forest, the mutual-exclusion map and the two search passes
(driven through an injected evaluator). Anything that actually compiles or executes
code is out of scope -- ``_evaluate`` is the only piece that does, and it is replaced
by a lookup table here.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, cast

import pytest

from discopop_explorer.aliases.NodeID import NodeID
from discopop_library.EmpiricalAutotuning.ArgumentClasses import AutotunerArguments
from discopop_library.EmpiricalAutotuning.Classes.ExecutionResult import ExecutionResult
from discopop_library.EmpiricalAutotuning.output.progress import DebugStatEntry
from discopop_library.PatchApplicator.PatchApplicationResult import PatchApplicationResult
from discopop_library.EmpiricalAutotuning.optimization import hotspot_guided_combination as hgc
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.HostpotLoader.detailed_hotspot_loader import HotspotRegionInfo
from discopop_library.result_classes.DetectionResult import DetectionResult

# module-private functions are reached via getattr to keep mypy and the linter happy
__forward_descent = getattr(hgc, "_" + "_forward_descent")
__removal_pass = getattr(hgc, "_" + "_removal_pass")

logger = logging.getLogger("test_hotspot_guided_combination")


# -- fixtures / builders -------------------------------------------------------------


class _FakePattern:
    """Enough of PatternBase for the candidate-selection and exclusion helpers."""

    def __init__(
        self,
        pattern_id: int,
        file_id: int,
        start_line: int,
        end_line: int,
        applicable: bool = True,
        standalone: bool = True,
        node_id: Optional[NodeID] = None,
        collapsed_pattern_ids: Optional[List[int]] = None,
        contains_patterns: Optional[List[int]] = None,
    ) -> None:
        self.pattern_id = pattern_id
        self.start_line = str(file_id) + ":" + str(start_line)
        self.end_line = str(file_id) + ":" + str(end_line)
        self.applicable_pattern = applicable
        self.standalone_pattern = standalone
        self.node_id = node_id if node_id is not None else NodeID(str(file_id) + ":" + str(pattern_id))
        if collapsed_pattern_ids is not None:
            self.collapsed_pattern_ids = collapsed_pattern_ids
        if contains_patterns is not None:
            self.contains_patterns = contains_patterns


class _FakeStorage:
    def __init__(self, patterns: Sequence[_FakePattern]) -> None:
        self.do_all: List[_FakePattern] = list(patterns)


class _FakeDetectionResult:
    """A DetectionResult without a PET graph, so containment falls back to line ranges."""

    def __init__(self, patterns: Sequence[_FakePattern]) -> None:
        self.patterns = _FakeStorage(patterns)
        self.pet = None


def _detection_result(patterns: Sequence[_FakePattern]) -> DetectionResult:
    """The helpers below only touch ``.patterns`` and ``.pet``, so a stand-in suffices."""
    return cast(DetectionResult, _FakeDetectionResult(patterns))


def _hotspot(
    file_id: int,
    start_line: int,
    hotness: HotspotType,
    max_val: float,
    ratio: float = 0.9,
    node_type: HotspotNodeType = HotspotNodeType.LOOP,
    csid: int = 0,
) -> HotspotRegionInfo:
    return HotspotRegionInfo(
        csid=csid,
        node_type=node_type,
        file_id=file_id,
        start_line=start_line,
        name="",
        hotness=hotness,
        runtimes=[max_val * (1.0 - ratio) / ratio, max_val],
        avr=max_val / 2.0,
        min_val=max_val * (1.0 - ratio) / ratio,
        max_val=max_val,
        ratio=ratio,
    )


def _region(
    file_id: int,
    start_line: int,
    end_line: int,
    hotness: HotspotType,
    max_val: float,
    suggestion_ids: Sequence[int],
    node_id: Optional[NodeID] = None,
) -> hgc.CandidateRegion:
    return hgc.CandidateRegion(
        file_id=file_id,
        start_line=start_line,
        end_line=end_line,
        node_id=node_id,
        hotness=hotness,
        avr=max_val / 2.0,
        max_val=max_val,
        ratio=0.9,
        suggestion_ids=list(suggestion_ids),
    )


def _arguments(**overrides: Any) -> AutotunerArguments:
    """AutotunerArguments without the on-disk validation of __post_init__."""
    arguments = AutotunerArguments.__new__(AutotunerArguments)
    defaults: Dict[str, Any] = {
        "log_level": "WARNING",
        "write_log": False,
        "dot_dp_path": "",
        "skip_cleanup": True,
        "sanitize": False,
        "configuration": "tiny",
        "suggestions": None,
        "allow_plots": False,
        "thread_count": 4,
        "project_path": "",
        "configuration_path": "",
        "hotspot_types": "yes,no,maybe",
        "algorithm": 6,
        "search_space": None,
        "noise_threshold": 0.02,
        "hs_min_share": 0.01,
        "max_measurements": 0,
        "skip_removal_pass": False,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        setattr(arguments, key, value)
    return arguments


class _Evaluator:
    """Replays a runtime table and records which configurations were asked for."""

    def __init__(self, runtimes: Dict[Tuple[int, ...], float], invalid: Optional[Set[Tuple[int, ...]]] = None) -> None:
        self.runtimes = runtimes
        self.invalid = invalid or set()
        self.calls: List[Tuple[int, ...]] = []

    def __call__(self, suggestion_ids: Sequence[int]) -> Tuple[float, bool]:
        key = hgc.canonical_configuration(suggestion_ids)
        self.calls.append(key)
        if key in self.invalid:
            return self.runtimes.get(key, 0.0), False
        # An unlisted configuration is a configuration that did not help.
        return self.runtimes.get(key, 1000.0), True


# -- ranking -------------------------------------------------------------------------


def test_hotness_class_outranks_runtime() -> None:
    """A huge MAYBE loop still waits for every YES loop, however small."""
    small_yes = _region(1, 10, 20, HotspotType.YES, 1.0, [1])
    huge_maybe = _region(1, 30, 40, HotspotType.MAYBE, 500.0, [2])

    assert sorted([huge_maybe, small_yes], key=hgc.rank_key) == [small_yes, huge_maybe]


def test_longest_run_wins_inside_a_class() -> None:
    cold = _region(1, 10, 20, HotspotType.YES, 5.0, [1])
    hot = _region(1, 30, 40, HotspotType.YES, 50.0, [2])

    assert sorted([cold, hot], key=hgc.rank_key) == [hot, cold]


def test_no_class_is_ranked_last() -> None:
    yes = _region(1, 10, 20, HotspotType.YES, 1.0, [1])
    maybe = _region(1, 30, 40, HotspotType.MAYBE, 1.0, [2])
    no = _region(1, 50, 60, HotspotType.NO, 1.0, [3])

    assert sorted([no, maybe, yes], key=hgc.rank_key) == [yes, maybe, no]


def test_a_loop_nest_is_ordered_outermost_first() -> None:
    """Nested loops report the same inclusive runtime, so the start line decides."""
    outer = _region(1, 100, 200, HotspotType.YES, 42.0, [1])
    inner = _region(1, 101, 199, HotspotType.YES, 42.0, [2])

    assert sorted([inner, outer], key=hgc.rank_key) == [outer, inner]


def test_ranking_is_independent_of_the_input_order() -> None:
    regions = [
        _region(2, 10, 20, HotspotType.MAYBE, 3.0, [4]),
        _region(1, 10, 20, HotspotType.YES, 3.0, [1]),
        _region(1, 30, 40, HotspotType.YES, 3.0, [2]),
        _region(3, 10, 20, HotspotType.NO, 99.0, [3]),
    ]
    expected = sorted(regions, key=hgc.rank_key)

    for rotation in range(len(regions)):
        rotated = regions[rotation:] + regions[:rotation]
        assert sorted(rotated, key=hgc.rank_key) == expected


def test_single_run_input_ranks_purely_by_runtime() -> None:
    """With one profiling run maxVal == avr, so the key collapses to descending runtime."""
    patterns = [_FakePattern(i, 1, 100 + 10 * i, 105 + 10 * i) for i in range(1, 4)]
    detection_result = _detection_result(patterns)
    # A single run means minVal == maxVal, hence ratio == 0.5 and topRatio holds for
    # every region: the analyzer then classifies on the average runtime alone.
    hotspots = [
        HotspotRegionInfo(
            csid=i,
            node_type=HotspotNodeType.LOOP,
            file_id=1,
            start_line=100 + 10 * i,
            name="",
            hotness=HotspotType.YES if runtime > 2.0 else HotspotType.MAYBE,
            runtimes=[runtime],
            avr=runtime,
            min_val=runtime,
            max_val=runtime,
            ratio=0.5,
        )
        for i, runtime in [(1, 1.0), (2, 5.0), (3, 3.0)]
    ]

    regions = hgc.build_candidate_regions(detection_result, hotspots, list(HotspotType), 0.0)

    assert [region.max_val for region in regions] == [5.0, 3.0, 1.0]


# -- candidate selection -------------------------------------------------------------


def test_exact_start_line_match_is_preferred_over_containment() -> None:
    enclosing = _FakePattern(1, 1, 100, 300)
    on_the_loop = _FakePattern(2, 1, 200, 250)
    detection_result = _detection_result([enclosing, on_the_loop])

    regions = hgc.build_candidate_regions(
        detection_result, [_hotspot(1, 200, HotspotType.YES, 10.0)], list(HotspotType), 0.0
    )

    assert [region.suggestion_ids for region in regions] == [[2]]


def test_containment_is_the_fallback_when_no_suggestion_starts_there() -> None:
    enclosing = _FakePattern(1, 1, 100, 300)
    detection_result = _detection_result([enclosing])

    regions = hgc.build_candidate_regions(
        detection_result, [_hotspot(1, 200, HotspotType.YES, 10.0)], list(HotspotType), 0.0
    )

    assert [region.suggestion_ids for region in regions] == [[1]]


def test_suggestions_on_the_same_loop_become_alternatives() -> None:
    do_all = _FakePattern(1, 1, 100, 200)
    collapsed = _FakePattern(2, 1, 100, 200)
    detection_result = _detection_result([collapsed, do_all])

    regions = hgc.build_candidate_regions(
        detection_result, [_hotspot(1, 100, HotspotType.YES, 10.0)], list(HotspotType), 0.0
    )

    assert len(regions) == 1
    assert regions[0].suggestion_ids == [1, 2]


def test_min_share_drops_the_cold_tail() -> None:
    patterns = [_FakePattern(1, 1, 100, 110), _FakePattern(2, 1, 200, 210)]
    detection_result = _detection_result(patterns)
    hotspots = [
        _hotspot(1, 100, HotspotType.YES, 100.0),
        _hotspot(1, 200, HotspotType.YES, 0.5),  # 0.5% of the hottest region
    ]

    kept = hgc.build_candidate_regions(detection_result, hotspots, list(HotspotType), 0.01)
    assert [region.suggestion_ids for region in kept] == [[1]]

    without_filter = hgc.build_candidate_regions(detection_result, hotspots, list(HotspotType), 0.0)
    assert [region.suggestion_ids for region in without_filter] == [[1], [2]]


def test_unconsidered_hotness_classes_are_excluded() -> None:
    patterns = [_FakePattern(1, 1, 100, 110), _FakePattern(2, 1, 200, 210)]
    detection_result = _detection_result(patterns)
    hotspots = [
        _hotspot(1, 100, HotspotType.YES, 10.0),
        _hotspot(1, 200, HotspotType.MAYBE, 10.0),
    ]

    regions = hgc.build_candidate_regions(detection_result, hotspots, [HotspotType.YES], 0.0)

    assert [region.suggestion_ids for region in regions] == [[1]]


def test_function_hotspots_are_ignored() -> None:
    """Only loops are parallelized; a hot function is covered through its loops."""
    detection_result = _detection_result([_FakePattern(1, 1, 100, 110)])

    regions = hgc.build_candidate_regions(
        detection_result,
        [_hotspot(1, 100, HotspotType.YES, 10.0, node_type=HotspotNodeType.FUNCTION)],
        list(HotspotType),
        0.0,
    )

    assert regions == []


@pytest.mark.parametrize("applicable,standalone", [(False, True), (True, False)])
def test_patterns_that_must_not_be_applied_alone_are_skipped(applicable: bool, standalone: bool) -> None:
    pattern = _FakePattern(1, 1, 100, 110, applicable=applicable, standalone=standalone)
    detection_result = _detection_result([pattern])

    regions = hgc.build_candidate_regions(
        detection_result, [_hotspot(1, 100, HotspotType.YES, 10.0)], list(HotspotType), 0.0
    )

    assert regions == []


def test_hot_loops_without_any_suggestion_are_dropped() -> None:
    detection_result = _detection_result([_FakePattern(1, 1, 100, 110)])

    regions = hgc.build_candidate_regions(
        detection_result, [_hotspot(1, 900, HotspotType.YES, 10.0)], list(HotspotType), 0.0
    )

    assert regions == []


# -- exclusions ----------------------------------------------------------------------


def test_collapsed_patterns_exclude_their_base_patterns() -> None:
    collapsed = _FakePattern(3, 1, 100, 200, collapsed_pattern_ids=[1, 2])
    detection_result = _detection_result([_FakePattern(1, 1, 100, 200), _FakePattern(2, 1, 101, 199), collapsed])

    exclusions = hgc.build_exclusion_map(detection_result)

    assert exclusions == {3: {1, 2}}


def test_parallel_regions_exclude_the_patterns_they_contain() -> None:
    region = _FakePattern(5, 1, 100, 300, contains_patterns=[1, 2])
    detection_result = _detection_result([region])

    assert hgc.build_exclusion_map(detection_result) == {5: {1, 2}}


def test_a_pattern_never_excludes_itself() -> None:
    detection_result = _detection_result([_FakePattern(1, 1, 100, 200, collapsed_pattern_ids=[1])])

    assert hgc.build_exclusion_map(detection_result) == {}


# -- nesting forest ------------------------------------------------------------------


def test_line_ranges_nest_regions_when_no_pet_is_available() -> None:
    outer = _region(1, 100, 300, HotspotType.YES, 42.0, [1])
    inner = _region(1, 150, 250, HotspotType.YES, 42.0, [2])
    innermost = _region(1, 160, 240, HotspotType.YES, 42.0, [3])
    detection_result = _detection_result([])

    roots, children = hgc.build_containment_forest([innermost, outer, inner], detection_result)

    assert roots == [outer]
    assert children[outer.key] == [inner]
    assert children[inner.key] == [innermost]


def test_regions_in_different_files_are_separate_roots() -> None:
    first = _region(1, 100, 300, HotspotType.YES, 42.0, [1])
    second = _region(2, 150, 250, HotspotType.YES, 10.0, [2])

    roots, children = hgc.build_containment_forest([second, first], _detection_result([]))

    assert roots == [first, second]
    assert children == {}


def test_the_direct_parent_is_the_tightest_enclosing_region() -> None:
    outer = _region(1, 100, 400, HotspotType.YES, 42.0, [1])
    middle = _region(1, 150, 350, HotspotType.YES, 42.0, [2])
    inner = _region(1, 200, 300, HotspotType.YES, 42.0, [3])

    _, children = hgc.build_containment_forest([outer, middle, inner], _detection_result([]))

    assert children[middle.key] == [inner]
    assert children[outer.key] == [middle]


# -- forward descent -----------------------------------------------------------------


def test_an_accepted_region_prunes_its_whole_subtree() -> None:
    """The inner loops of a parallelized region must not cost a measurement."""
    outer = _region(1, 100, 300, HotspotType.YES, 42.0, [1])
    inner = _region(1, 150, 250, HotspotType.YES, 42.0, [2])
    children = {outer.key: [inner]}
    evaluator = _Evaluator({(1,): 5.0})

    accepted, runtime = __forward_descent([outer], children, {}, [], 10.0, set(), evaluator, _arguments(), logger)

    assert accepted == [1]
    assert runtime == 5.0
    assert evaluator.calls == [(1,)]


def test_a_rejected_region_hands_over_to_its_nested_regions() -> None:
    outer = _region(1, 100, 300, HotspotType.YES, 42.0, [1])
    inner = _region(1, 150, 250, HotspotType.YES, 42.0, [2])
    children = {outer.key: [inner]}
    # The outer loop does not pay off, the inner one does.
    evaluator = _Evaluator({(1,): 10.0, (2,): 4.0})

    accepted, runtime = __forward_descent([outer], children, {}, [], 10.0, set(), evaluator, _arguments(), logger)

    assert accepted == [2]
    assert runtime == 4.0
    assert evaluator.calls == [(1,), (2,)]


def test_the_best_alternative_of_a_region_is_kept() -> None:
    region = _region(1, 100, 200, HotspotType.YES, 42.0, [1, 2, 3])
    evaluator = _Evaluator({(1,): 8.0, (2,): 3.0, (3,): 6.0})

    accepted, runtime = __forward_descent([region], {}, {}, [], 10.0, set(), evaluator, _arguments(), logger)

    assert accepted == [2]
    assert runtime == 3.0
    assert evaluator.calls == [(1,), (2,), (3,)]


def test_an_invalid_configuration_is_never_accepted() -> None:
    """A racy parallelization is often the fastest one; it must still lose."""
    region = _region(1, 100, 200, HotspotType.YES, 42.0, [1])
    evaluator = _Evaluator({(1,): 0.5}, invalid={(1,)})

    accepted, runtime = __forward_descent([region], {}, {}, [], 10.0, set(), evaluator, _arguments(), logger)

    assert accepted == []
    assert runtime == 10.0


def test_an_improvement_below_the_noise_threshold_is_rejected() -> None:
    region = _region(1, 100, 200, HotspotType.YES, 42.0, [1])
    evaluator = _Evaluator({(1,): 9.9})  # 1% faster, below the 2% threshold

    accepted, _ = __forward_descent([region], {}, {}, [], 10.0, set(), evaluator, _arguments(), logger)
    assert accepted == []

    permissive = _Evaluator({(1,): 9.9})
    accepted, _ = __forward_descent(
        [region], {}, {}, [], 10.0, set(), permissive, _arguments(noise_threshold=0.005), logger
    )
    assert accepted == [1]


def test_suggestions_accumulate_across_regions() -> None:
    first = _region(1, 100, 200, HotspotType.YES, 50.0, [1])
    second = _region(1, 300, 400, HotspotType.YES, 20.0, [2])
    evaluator = _Evaluator({(1,): 6.0, (1, 2): 4.0})

    accepted, runtime = __forward_descent([first, second], {}, {}, [], 10.0, set(), evaluator, _arguments(), logger)

    assert accepted == [1, 2]
    assert runtime == 4.0
    assert evaluator.calls == [(1,), (1, 2)]


def test_accepting_a_suggestion_skips_the_ones_it_excludes() -> None:
    """The exclusion map catches conflicts the nesting forest cannot see.

    Suggestions on one loop are merged into a single region's alternatives and the
    regions below an accepted one are pruned anyway, so this map matters exactly where
    the conflicting suggestions end up as siblings -- e.g. an inflated parallel region
    whose contained patterns sit in a called function.
    """
    region = _region(1, 100, 200, HotspotType.YES, 50.0, [3])
    sibling = _region(1, 400, 500, HotspotType.YES, 40.0, [1])
    evaluator = _Evaluator({(3,): 5.0})

    accepted, _ = __forward_descent([region, sibling], {}, {3: {1}}, [], 10.0, set(), evaluator, _arguments(), logger)

    assert accepted == [3]
    assert evaluator.calls == [(3,)]


def test_an_already_excluded_alternative_is_not_measured() -> None:
    region = _region(1, 100, 200, HotspotType.YES, 50.0, [1, 2])
    evaluator = _Evaluator({(2,): 5.0})

    accepted, _ = __forward_descent([region], {}, {}, [], 10.0, {1}, evaluator, _arguments(), logger)

    assert accepted == [2]
    assert evaluator.calls == [(2,)]


def test_the_hottest_available_region_is_always_measured_first() -> None:
    cold_root = _region(1, 500, 600, HotspotType.YES, 1.0, [9])
    hot_root = _region(1, 100, 300, HotspotType.YES, 90.0, [1])
    hot_child = _region(1, 150, 250, HotspotType.YES, 90.0, [2])
    children = {hot_root.key: [hot_child]}
    # Nothing helps, so the descent visits every region: the order is what matters.
    evaluator = _Evaluator({})

    __forward_descent([hot_root, cold_root], children, {}, [], 10.0, set(), evaluator, _arguments(), logger)

    # The hot root's nested region outranks the cold root and is therefore tried first.
    assert evaluator.calls == [(1,), (2,), (9,)]


def test_the_descent_is_reproducible() -> None:
    regions = [
        _region(1, 100, 300, HotspotType.YES, 90.0, [1, 2]),
        _region(2, 100, 200, HotspotType.MAYBE, 40.0, [3]),
        _region(1, 400, 500, HotspotType.YES, 10.0, [4]),
    ]
    runtimes = {(2,): 7.0, (2, 4): 6.0, (1,): 8.0}

    traces = []
    for _ in range(2):
        evaluator = _Evaluator(dict(runtimes))
        accepted, runtime = __forward_descent(
            sorted(regions, key=hgc.rank_key), {}, {}, [], 10.0, set(), evaluator, _arguments(), logger
        )
        traces.append((list(evaluator.calls), list(accepted), runtime))

    assert traces[0] == traces[1]


def test_the_measurement_budget_stops_the_descent() -> None:
    regions = [_region(1, 100 * i, 100 * i + 50, HotspotType.YES, 10.0, [i]) for i in range(1, 5)]

    class _Budgeted(_Evaluator):
        def __call__(self, suggestion_ids: Sequence[int]) -> Tuple[float, bool]:
            if len(self.calls) >= 2:
                raise hgc.SearchBudgetExhausted()
            return super().__call__(suggestion_ids)

    evaluator = _Budgeted({})
    with pytest.raises(hgc.SearchBudgetExhausted):
        __forward_descent(regions, {}, {}, [], 10.0, set(), evaluator, _arguments(), logger)

    assert len(evaluator.calls) == 2


# -- removal pass --------------------------------------------------------------------


def test_a_suggestion_that_hurts_in_combination_is_removed() -> None:
    evaluator = _Evaluator({(1,): 3.0, (2,): 9.0})

    accepted, runtime = __removal_pass([1, 2], 5.0, evaluator, _arguments(), logger)

    assert accepted == [1]
    assert runtime == 3.0


def test_a_helpful_suggestion_survives_the_removal_pass() -> None:
    evaluator = _Evaluator({(1,): 8.0, (2,): 8.0})

    accepted, runtime = __removal_pass([1, 2], 5.0, evaluator, _arguments(), logger)

    assert accepted == [1, 2]
    assert runtime == 5.0


def test_the_removal_pass_never_empties_the_configuration() -> None:
    """Dropping the last suggestion would just reproduce the untuned baseline."""
    evaluator = _Evaluator({})

    accepted, runtime = __removal_pass([1], 5.0, evaluator, _arguments(), logger)

    assert accepted == [1]
    assert runtime == 5.0
    assert evaluator.calls == []


def test_the_removal_pass_revisits_the_coldest_region_first() -> None:
    evaluator = _Evaluator({})

    __removal_pass([1, 2, 3], 5.0, evaluator, _arguments(), logger)

    assert evaluator.calls == [(1, 2), (1, 3), (2, 3)]


def test_an_invalid_removal_is_not_applied() -> None:
    evaluator = _Evaluator({(1,): 1.0}, invalid={(1,)})

    accepted, runtime = __removal_pass([1, 2], 5.0, evaluator, _arguments(), logger)

    assert accepted == [1, 2]
    assert runtime == 5.0


# -- cache key -----------------------------------------------------------------------


def test_a_configuration_is_a_set_of_suggestions() -> None:
    assert hgc.canonical_configuration([2, 1, 2]) == (1, 2)
    assert hgc.canonical_configuration([1, 2]) == hgc.canonical_configuration([2, 1])


def test_improves_requires_more_than_the_threshold() -> None:
    assert hgc.improves(9.0, 10.0, 0.02)
    assert not hgc.improves(9.9, 10.0, 0.02)
    assert not hgc.improves(10.0, 10.0, 0.02)
    assert not hgc.improves(11.0, 10.0, 0.02)


# -- driver --------------------------------------------------------------------------


class _StubConfiguration:
    """A CodeConfiguration that reports runtimes from a table instead of compiling."""

    def __init__(
        self,
        runtimes: Dict[Tuple[int, ...], float],
        baseline: float,
        unpatchable: Optional[Set[Tuple[int, ...]]] = None,
    ) -> None:
        self.runtimes = runtimes
        self.unpatchable = unpatchable or set()
        self.root_path = "/stub"
        self.execution_result: Optional[ExecutionResult] = ExecutionResult(baseline, 0, True, True)
        self.applied: Tuple[int, ...] = tuple()
        self.deleted = 0

    def create_copy(self, arguments: Any, settings_name: str, get_new_configuration_id: Any) -> "_StubConfiguration":
        copy = _StubConfiguration(self.runtimes, 0.0, self.unpatchable)
        copy.execution_result = None
        return copy

    def apply_suggestions(self, arguments: Any, suggestion_ids: List[int]) -> PatchApplicationResult:
        self.applied = hgc.canonical_configuration(suggestion_ids)
        requested = [str(id) for id in self.applied]
        if self.applied in self.unpatchable:
            return PatchApplicationResult(requested=requested, failed=requested)
        return PatchApplicationResult(requested=requested, applied=requested)

    def execute(self, arguments: Any, timeout: Optional[float], thread_count: int, is_initial: bool = False) -> None:
        runtime = self.runtimes.get(self.applied, 1000.0)
        self.execution_result = ExecutionResult(runtime, 0, True, True)

    def deleteFolder(self) -> None:
        self.deleted += 1


def _hotspots_on_disk(directory: Any, regions: Sequence[Dict[str, Any]]) -> None:
    hotspot_dir = directory / "hotspot_detection"
    hotspot_dir.mkdir(parents=True, exist_ok=True)
    (hotspot_dir / "Hotspots.json").write_text(json.dumps({"code_regions": list(regions)}))


def _json_region(csid: int, line: int, hotness: str, runtimes: List[float], typ: str = "LOOP") -> Dict[str, Any]:
    return {
        "csid": csid,
        "typ": typ,
        "fid": 1,
        "lineNum": line,
        "name": "",
        "runtimes": runtimes,
        "level": 0,
        "hot": True,
        "hotness": hotness,
        "delta": max(runtimes) - min(runtimes),
        "avr": sum(runtimes) / len(runtimes),
        "sum": sum(runtimes),
        "minVal": min(runtimes),
        "maxVal": max(runtimes),
        "ratio": 1.0 / ((min(runtimes) / max(runtimes)) + 1.0),
        "topAvr": True,
        "topRatio": True,
    }


def _run_driver(
    tmp_path: Any,
    patterns: Sequence[_FakePattern],
    runtimes: Dict[Tuple[int, ...], float],
    baseline: float = 10.0,
    **argument_overrides: Any,
) -> List[DebugStatEntry]:
    debug_stats: List[DebugStatEntry] = []
    hgc.execute_hotspot_guided_combination(
        _detection_result(patterns),
        {},
        logger,
        0,
        cast(Any, _StubConfiguration(runtimes, baseline)),
        _arguments(dot_dp_path=str(tmp_path), **argument_overrides),
        30.0,
        cast(Any, debug_stats),
        lambda: 1,
    )
    return debug_stats


def test_the_driver_aborts_without_hotspot_results(tmp_path: Any, caplog: Any) -> None:
    """The algorithm is defined by the hotspot data; guessing instead would be worse."""
    with caplog.at_level(logging.ERROR):
        debug_stats = _run_driver(tmp_path, [_FakePattern(1, 1, 100, 110)], {})

    assert debug_stats == []
    assert "requires hotspot detection results" in caplog.text


def test_the_driver_aborts_when_the_results_contain_no_loops(tmp_path: Any, caplog: Any) -> None:
    _hotspots_on_disk(tmp_path, [_json_region(1, 100, "YES", [1.0, 5.0], typ="FUNCTION")])

    with caplog.at_level(logging.ERROR):
        debug_stats = _run_driver(tmp_path, [_FakePattern(1, 1, 100, 110)], {})

    assert debug_stats == []
    assert "contain no loops" in caplog.text


def test_the_driver_aborts_when_no_suggestion_targets_a_hot_loop(tmp_path: Any, caplog: Any) -> None:
    _hotspots_on_disk(tmp_path, [_json_region(1, 900, "YES", [1.0, 5.0])])

    with caplog.at_level(logging.ERROR):
        debug_stats = _run_driver(tmp_path, [_FakePattern(1, 1, 100, 110)], {})

    assert debug_stats == []
    assert "no suggestion targets" in caplog.text


def test_the_driver_records_every_measurement(tmp_path: Any) -> None:
    _hotspots_on_disk(
        tmp_path,
        [_json_region(1, 100, "YES", [1.0, 50.0]), _json_region(2, 200, "MAYBE", [1.0, 20.0])],
    )
    patterns = [_FakePattern(1, 1, 100, 110), _FakePattern(2, 1, 200, 210)]

    debug_stats = _run_driver(tmp_path, patterns, {(1,): 5.0, (1, 2): 4.0})

    # Both regions are accepted; the removal pass then re-checks dropping each of them.
    # Dropping 2 reuses the cached [1], dropping 1 needs the new measurement [2].
    assert [entry[0] for entry in debug_stats] == [[1], [1, 2], [2]]
    assert [entry[1] for entry in debug_stats] == [5.0, 4.0, 1000.0]
    assert all(entry[2] == 0 and entry[3] and entry[4] for entry in debug_stats)


def test_the_driver_never_measures_a_configuration_twice(tmp_path: Any) -> None:
    """The removal pass revisits configurations the descent already measured."""
    _hotspots_on_disk(
        tmp_path,
        [_json_region(1, 100, "YES", [1.0, 50.0]), _json_region(2, 200, "YES", [1.0, 20.0])],
    )
    patterns = [_FakePattern(1, 1, 100, 110), _FakePattern(2, 1, 200, 210)]

    debug_stats = _run_driver(tmp_path, patterns, {(1,): 5.0, (1, 2): 4.0})

    measured = [tuple(entry[0]) for entry in debug_stats]
    assert len(measured) == len(set(measured))


def test_an_unpatchable_configuration_is_recorded_as_failed(tmp_path: Any) -> None:
    """A conflicting patch must not be measured as if it had been applied."""
    _hotspots_on_disk(tmp_path, [_json_region(1, 100, "YES", [1.0, 50.0])])
    debug_stats: List[DebugStatEntry] = []
    stub = _StubConfiguration({(1,): 1.0}, 10.0, unpatchable={(1,)})

    hgc.execute_hotspot_guided_combination(
        _detection_result([_FakePattern(1, 1, 100, 110)]),
        {},
        logger,
        0,
        cast(Any, stub),
        _arguments(dot_dp_path=str(tmp_path)),
        30.0,
        cast(Any, debug_stats),
        lambda: 1,
    )

    assert [(entry[0], entry[2], entry[3]) for entry in debug_stats] == [([1], 1, False)]
    # the entry must say *which* suggestions are missing, so it can be told apart from
    # a parallel run that merely achieved no speedup
    assert [entry[6] for entry in debug_stats] == [[1]]


def test_the_driver_is_reproducible(tmp_path: Any) -> None:
    _hotspots_on_disk(
        tmp_path,
        [
            _json_region(1, 100, "YES", [1.0, 50.0]),
            _json_region(2, 200, "MAYBE", [1.0, 20.0]),
            _json_region(3, 300, "YES", [1.0, 30.0]),
        ],
    )
    patterns = [_FakePattern(i, 1, 100 * i, 100 * i + 10) for i in range(1, 4)]
    runtimes = {(3,): 8.0, (1, 3): 6.0, (1,): 9.5}

    first = _run_driver(tmp_path, patterns, dict(runtimes))
    second = _run_driver(tmp_path, patterns, dict(runtimes))

    assert [entry[0] for entry in first] == [entry[0] for entry in second]
    assert [entry[1] for entry in first] == [entry[1] for entry in second]


def test_the_measurement_budget_is_respected(tmp_path: Any) -> None:
    _hotspots_on_disk(tmp_path, [_json_region(i, 100 * i, "YES", [1.0, 50.0 - i]) for i in range(1, 5)])
    patterns = [_FakePattern(i, 1, 100 * i, 100 * i + 10) for i in range(1, 5)]

    debug_stats = _run_driver(tmp_path, patterns, {}, max_measurements=2)

    # The empty baseline configuration is cached rather than measured, so the budget
    # applies to the four candidate regions only.
    assert len(debug_stats) == 2

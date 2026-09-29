# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Unit tests for the evolutionary autotuning search.

These cover the pure, measurement-free parts of the algorithm: fitness derivation
from the measurement caches, survivor selection and population statistics. Anything
that compiles or executes code is out of scope here (that is covered end-to-end).
"""

import itertools
import logging
import random
from typing import Any, Dict, Iterator, List, Tuple

import pytest

from discopop_library.EmpiricalAutotuning.optimization import evolutionary_combination as ec
from discopop_library.HostpotLoader.HotspotType import HotspotType

CHROMOSOME = Tuple[int, ...]

# module-private functions are reached via getattr to keep mypy and the linter happy
__select = getattr(ec, "_" + "_select")
__initialize = getattr(ec, "_" + "_initialize")
__fill_population = getattr(ec, "_" + "_fill_population")
__crossover = getattr(ec, "_" + "_crossover")
__mutate = getattr(ec, "_" + "_mutate")

logger = logging.getLogger("test_evolutionary_combination")


@pytest.fixture(autouse=True)
def clean_caches() -> Iterator[None]:
    """The algorithm keeps its measurement caches in module globals; isolate them."""
    ec.fitness_cache.clear()
    ec.runtime_cache.clear()
    ec.return_code_cache.clear()
    ec.validity_cache.clear()
    yield
    ec.fitness_cache.clear()
    ec.runtime_cache.clear()
    ec.return_code_cache.clear()
    ec.validity_cache.clear()


def _measure(chromosome: CHROMOSOME, runtime: float, valid: bool, return_code: int = 0) -> None:
    ec.runtime_cache[chromosome] = runtime
    ec.return_code_cache[chromosome] = return_code
    ec.validity_cache[chromosome] = valid


# -- fitness -----------------------------------------------------------------------


def test_fitness_is_speedup_over_reference() -> None:
    _measure((1, 2), runtime=4.0, valid=True)
    assert ec.get_fitness((1, 2), reference_runtime=10.0) == pytest.approx(2.5)


def test_invalid_result_scores_zero_despite_fast_runtime() -> None:
    """A racy configuration is often the fastest one -- it must never earn fitness."""
    _measure((3,), runtime=0.5, valid=False, return_code=0)
    assert ec.get_fitness((3,), reference_runtime=10.0) == 0.0


def test_nonzero_return_code_scores_zero() -> None:
    _measure((4,), runtime=0.1, valid=False, return_code=1)
    assert ec.get_fitness((4,), reference_runtime=10.0) == 0.0


def test_unmeasured_chromosome_scores_zero() -> None:
    assert ec.get_fitness((9, 9), reference_runtime=10.0) == 0.0


def test_zero_runtime_does_not_divide_by_zero() -> None:
    _measure((5,), runtime=0.0, valid=True)
    assert ec.get_fitness((5,), reference_runtime=10.0) == 0.0


# -- selection ---------------------------------------------------------------------


def test_select_keeps_the_fittest_members_of_the_population() -> None:
    population: List[CHROMOSOME] = [(1,), (2,), (3,)]
    ec.fitness_cache.update({(1,): 1.0, (2,): 3.0, (3,): 2.0})
    assert __select(logger, population, 2) == [(2,), (3,)]


def test_select_does_not_resurrect_individuals_from_the_archive() -> None:
    """Selection is a population operator: history stays in the archive.

    Regression test -- selection used to return the globally fittest chromosomes
    ever measured, which made every population statistic an archive statistic.
    """
    population: List[CHROMOSOME] = [(1,), (2,)]
    ec.fitness_cache.update({(1,): 1.0, (2,): 0.5, (99,): 100.0})
    selection = __select(logger, population, 2)
    assert (99,) not in selection
    assert selection == [(1,), (2,)]


def test_select_deduplicates_and_never_grows_the_population() -> None:
    population: List[CHROMOSOME] = [(1,), (1,), (2,)]
    ec.fitness_cache.update({(1,): 2.0, (2,): 1.0})
    assert __select(logger, population, 5) == [(1,), (2,)]


def test_select_preserves_the_best_individual() -> None:
    """(mu+lambda) elitism: the fittest member always survives."""
    population: List[CHROMOSOME] = [(1,), (2,), (3,), (4,)]
    ec.fitness_cache.update({(1,): 0.1, (2,): 0.2, (3,): 9.0, (4,): 0.4})
    assert (3,) in __select(logger, population, 1)


def test_select_ranks_unmeasured_chromosomes_last() -> None:
    population: List[CHROMOSOME] = [(7,), (1,)]
    ec.fitness_cache.update({(1,): 1.0})
    assert __select(logger, population, 1) == [(1,)]


# -- population statistics ---------------------------------------------------------


def test_average_fitness_covers_exactly_the_given_individuals() -> None:
    ec.fitness_cache.update({(1,): 1.0, (2,): 3.0, (3,): 100.0})
    assert ec.get_average_fitness([(1,), (2,)]) == pytest.approx(2.0)


def test_average_fitness_counts_invalid_individuals_as_zero() -> None:
    """Invalid individuals are scattered at y=0, so they must pull the average down."""
    ec.fitness_cache.update({(1,): 4.0, (2,): 0.0})
    assert ec.get_average_fitness([(1,), (2,)]) == pytest.approx(2.0)


def test_average_fitness_of_empty_population_is_zero() -> None:
    assert ec.get_average_fitness([]) == 0.0


def test_maximum_fitness_is_the_best_of_the_archive() -> None:
    ec.fitness_cache.update({(1,): 1.0, (2,): 3.5})
    assert ec.get_maximum_fitness() == pytest.approx(3.5)


# -- chromosome representation -----------------------------------------------------


def test_chromosomes_are_order_independent_and_deduplicated() -> None:
    """(1, 2) and (2, 1) are the same parallelization and must share a cache key."""
    assert ec.canonical_chromosome([2, 1]) == ec.canonical_chromosome([1, 2]) == (1, 2)
    assert ec.canonical_chromosome([3, 3, 1]) == (1, 3)
    assert ec.canonical_chromosome([]) == tuple()


# -- initialization ----------------------------------------------------------------


def _patterns(yes: List[int], maybe: List[int], no: List[int]) -> Dict[HotspotType, List[int]]:
    return {HotspotType.YES: yes, HotspotType.MAYBE: maybe, HotspotType.NO: no}


def test_initialize_consumes_maybes_in_order_without_skipping() -> None:
    """Regression: the loop used to mutate the list it iterated, skipping every second."""
    patterns = _patterns(yes=[], maybe=[10, 11, 12, 13, 14, 15], no=[])
    population, unused_maybes = __initialize(logger, 4, patterns)
    assert population == [(10,), (11,), (12,), (13,)]
    assert unused_maybes == [14, 15]


def test_initialize_does_not_consume_the_callers_pattern_list() -> None:
    maybes = [10, 11, 12]
    patterns = _patterns(yes=[], maybe=maybes, no=[])
    __initialize(logger, 2, patterns)
    assert maybes == [10, 11, 12]


def test_initialize_takes_all_yes_then_fills_with_maybe_then_no() -> None:
    patterns = _patterns(yes=[1, 2], maybe=[10, 11], no=[20, 21])
    population, unused_maybes = __initialize(logger, 5, patterns)
    assert population == [(1,), (2,), (10,), (11,), (20,)]
    assert unused_maybes == []


def test_initialize_keeps_every_yes_even_beyond_the_population_size() -> None:
    patterns = _patterns(yes=[1, 2, 3], maybe=[10], no=[])
    population, unused_maybes = __initialize(logger, 2, patterns)
    assert population == [(1,), (2,), (3,)]
    assert unused_maybes == [10]


def test_fill_population_uses_the_remaining_maybes_in_priority_order() -> None:
    population: List[CHROMOSOME] = [(1,)]
    filled, unused_maybes = __fill_population(logger, population, 3, [14, 15, 16])
    assert filled == [(1,), (14,), (15,)]
    assert unused_maybes == [16]


# -- crossover ---------------------------------------------------------------------


def test_crossover_children_keep_the_genes_outside_the_cut_window(
    monkeypatch: "pytest.MonkeyPatch",
) -> None:
    """Regression: children used to consist only of the genes inside the cut window.

    A two-point crossover redistributes the parents' genes, it does not discard them:
    whatever the cut points, the two positional children together hold exactly the
    genes of the two parents. Before the fix each child kept only the window, so both
    invariants below failed for every window smaller than the full gene axis.
    """
    parents: List[CHROMOSOME] = [(1, 2, 3), (4, 5, 6)]
    # pin parent selection so the assertions do not depend on which parents were drawn
    picks = itertools.cycle(parents)
    monkeypatch.setattr(random, "choice", lambda seq: next(picks))

    for seed in range(25):
        random.seed(seed)
        result = __crossover(logger, list(parents), 1)
        child_1, child_2 = result[2], result[3]
        assert set(child_1) | set(child_2) == {1, 2, 3, 4, 5, 6}
        assert len(child_1) + len(child_2) == 6


def test_crossover_of_identical_parents_reproduces_them() -> None:
    random.seed(2)
    result = __crossover(logger, [(1, 2, 3)], 1)
    for child in result[1:]:
        assert child == (1, 2, 3)


def test_crossover_yields_canonical_children() -> None:
    random.seed(3)
    population: List[CHROMOSOME] = [(3, 1), (2, 9)]
    result = __crossover(logger, list(population), 4)
    for child in result[len(population) :]:
        assert list(child) == sorted(set(child))


def test_crossover_without_genes_is_a_noop() -> None:
    population: List[CHROMOSOME] = [tuple()]
    assert __crossover(logger, population, 3) == [tuple()]


# -- mutation ----------------------------------------------------------------------


def test_mutation_flips_exactly_one_known_gene() -> None:
    random.seed(4)
    ec.fitness_cache.update({(1,): 1.0, (2,): 1.0, (3,): 1.0})
    result = __mutate(logger, [(1, 2)], 5)
    for child in result[1:]:
        assert len(set(child) ^ {1, 2}) == 1
        assert set(child) <= {1, 2, 3}


def test_mutation_yields_canonical_children() -> None:
    random.seed(5)
    ec.fitness_cache.update({(5,): 1.0, (1,): 1.0})
    for child in __mutate(logger, [(5,)], 6):
        assert list(child) == sorted(set(child))


def test_mutation_without_known_genes_is_a_noop() -> None:
    """Regression: an empty gene pool used to raise ValueError from randint(0, -1)."""
    population: List[CHROMOSOME] = [tuple()]
    assert __mutate(logger, population, 3) == [tuple()]

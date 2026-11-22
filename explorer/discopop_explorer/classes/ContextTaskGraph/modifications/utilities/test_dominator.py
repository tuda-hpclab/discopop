# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""is_dominator on small hand-made graphs and against the first implementation on random ones."""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Set, Tuple

import pytest

from discopop_explorer.classes.ContextTaskGraph.classes.edges import CTGEdgeType
from discopop_explorer.classes.ContextTaskGraph.modifications.utilities.dominator import is_dominator


@dataclass(frozen=True)
class _Info:
    type: CTGEdgeType


class _FakeCTG:
    """What is_dominator asks of a ContextTaskGraph: get_predecessors and get_edge_info."""

    def __init__(self, edges: List[Tuple[int, int, CTGEdgeType]]) -> None:
        self.preds: Dict[int, List[int]] = {}
        self.info: Dict[Tuple[int, int], List[_Info]] = {}
        for s, t, kind in edges:
            if s not in self.preds.setdefault(t, []):
                self.preds[t].append(s)
            self.info.setdefault((s, t), []).append(_Info(kind))

    def get_predecessors(self, node: int) -> List[int]:
        return list(self.preds.get(node, []))

    def get_edge_info(self, source: int, target: int) -> List[_Info]:
        return self.info.get((source, target), [])


def _reference_is_dominator(ctg: Any, ctx_1: int, ctx_2: int) -> bool:
    """The implementation before it used a set for the membership test."""
    if ctx_1 == ctx_2:
        return True
    control_edge_predecessors = [
        ctx
        for ctx in ctg.get_predecessors(ctx_2)
        if (len([info for info in ctg.get_edge_info(ctx, ctx_2) if info.type == CTGEdgeType.CONTROL]) > 0)
    ]
    queue = control_edge_predecessors
    encountered_ctx_1 = False
    visited: Set[int] = set()
    while len(queue):
        current = queue.pop()
        if current == ctx_1:
            encountered_ctx_1 = True
            continue
        visited.add(current)
        current_control_edge_predecessors = [
            ctx
            for ctx in ctg.get_predecessors(current)
            if (len([info for info in ctg.get_edge_info(ctx, current) if info.type == CTGEdgeType.CONTROL]) > 0)
        ]
        if len(current_control_edge_predecessors) == 0:
            return False
        else:
            for pred in current_control_edge_predecessors:
                if pred not in visited and pred not in queue:
                    queue.append(pred)
    return encountered_ctx_1


C, D = CTGEdgeType.CONTROL, CTGEdgeType.DATA


def test_a_node_dominates_itself() -> None:
    assert is_dominator(_FakeCTG([]), 1, 1)  # type: ignore[arg-type]


def test_the_head_of_a_diamond_dominates_the_join_but_a_branch_does_not() -> None:
    ctg = _FakeCTG([(0, 1, C), (0, 2, C), (1, 3, C), (2, 3, C)])
    assert is_dominator(ctg, 0, 3)  # type: ignore[arg-type]
    assert not is_dominator(ctg, 1, 3)  # type: ignore[arg-type]


def test_a_node_without_control_predecessors_is_dominated_by_nobody() -> None:
    ctg = _FakeCTG([(0, 1, D)])
    assert not is_dominator(ctg, 0, 1)  # type: ignore[arg-type]


@pytest.mark.parametrize("seed", range(40))  # type: ignore[misc]
def test_same_answers_as_the_first_implementation_on_random_graphs(seed: int) -> None:
    rng = random.Random(seed)
    n = rng.randint(2, 14)
    edges = [
        (rng.randrange(n), rng.randrange(n), rng.choice([C, C, D]))  # cycles and self loops included
        for _ in range(rng.randint(1, 3 * n))
    ]
    ctg = _FakeCTG(edges)
    for a in range(n):
        for b in range(n):
            assert is_dominator(ctg, a, b) == _reference_is_dominator(ctg, a, b)  # type: ignore[arg-type]


@pytest.mark.parametrize("seed", range(20))  # type: ignore[misc]
def test_a_control_predecessor_map_gives_the_same_answers(seed: int) -> None:
    from discopop_explorer.classes.ContextTaskGraph.modifications.utilities.dominator import control_predecessor_map

    rng = random.Random(100 + seed)
    n = rng.randint(2, 14)
    edges = [(rng.randrange(n), rng.randrange(n), rng.choice([C, C, D])) for _ in range(rng.randint(1, 3 * n))]
    ctg = _FakeCTG(edges)
    ctg.graph = type("G", (), {"edges": staticmethod(lambda: list(ctg.info))})()  # type: ignore[attr-defined]
    cmap = control_predecessor_map(ctg)  # type: ignore[arg-type]
    for a in range(n):
        for b in range(n):
            assert is_dominator(ctg, a, b, cmap) == _reference_is_dominator(ctg, a, b)  # type: ignore[arg-type]

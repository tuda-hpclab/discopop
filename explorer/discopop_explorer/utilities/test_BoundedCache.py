# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import threading

import pytest

from discopop_explorer.utilities.BoundedCache import BoundedCache


def test_computes_once_and_counts() -> None:
    cache: BoundedCache[int, int] = BoundedCache(4)
    calls: list[int] = []

    def compute(value: int) -> int:
        calls.append(value)
        return value

    assert cache.get_or_compute(1, lambda: compute(10)) == 10
    assert cache.get_or_compute(1, lambda: compute(11)) == 10
    assert len(calls) == 1 and (cache.hits, cache.misses) == (1, 1)


def test_evicts_least_recently_used() -> None:
    cache: BoundedCache[int, int] = BoundedCache(2)
    cache.get_or_compute(1, lambda: 1)
    cache.get_or_compute(2, lambda: 2)
    cache.get_or_compute(1, lambda: 99)  # 1 is now the most recent
    cache.get_or_compute(3, lambda: 3)  # evicts 2
    assert len(cache) == 2
    assert cache.get_or_compute(1, lambda: 99) == 1
    assert cache.get_or_compute(2, lambda: 22) == 22


def test_clear_and_invalid_capacity() -> None:
    cache: BoundedCache[str, str] = BoundedCache(1)
    cache.get_or_compute("a", lambda: "x")
    cache.clear()
    assert len(cache) == 0
    with pytest.raises(ValueError):
        BoundedCache(0)


def test_threads_get_consistent_values() -> None:
    cache: BoundedCache[int, int] = BoundedCache(8)
    errors: list[int] = []

    def work() -> None:
        for i in range(2000):
            key = i % 20
            if cache.get_or_compute(key, lambda key=key: key) != key:  # type: ignore[misc]
                errors.append(i)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors and len(cache) <= 8

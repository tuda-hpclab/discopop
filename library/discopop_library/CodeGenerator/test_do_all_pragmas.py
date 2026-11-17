# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The pragmas generated for do-all and reduction patterns."""

from typing import Any, Dict, List

import pytest

from discopop_library.CodeGenerator.classes.UnpackedSuggestion import UnpackedSuggestion


def _pattern(**extra: Any) -> Dict[str, Any]:
    return {
        "pattern_id": 1,
        "start_line": "1:10",
        "end_line": "1:14",
        "pragma": "#pragma omp parallel for",
        "first_private": ["k"],
        "private": ["tmp"],
        "last_private": [],
        "shared": ["n", "out"],
        "reduction": ["+:sum"],
        "collapse_level": 1,
        **extra,
    }


def _pragma_text(type_str: str, values: Dict[str, Any]) -> str:
    pragmas = UnpackedSuggestion(type_str, values).get_pragmas(None)
    assert len(pragmas) == 1
    return str(pragmas[0].pragma_str).strip()


@pytest.mark.parametrize("type_str", ["do_all", "reduction"])
def test_default_none_is_added_only_when_the_pattern_asks_for_it(type_str: str) -> None:
    plain = _pragma_text(type_str, _pattern())
    marked = _pragma_text(type_str, _pattern(default_none=True))

    assert "default(none)" not in plain
    assert marked == plain.replace("#pragma omp parallel for", "#pragma omp parallel for default(none)")


def test_default_none_is_not_added_to_a_gpu_pragma() -> None:
    values: List[Any] = [_pattern(default_none=True, dp_optimizer_device_id=1)]

    assert "default(none)" not in _pragma_text("gpu_do_all", values[0])


def test_the_default_output_is_unchanged_without_the_field() -> None:
    """patterns.json of older runs has no default_none entry."""
    text = _pragma_text("do_all", _pattern())

    assert text == "#pragma omp parallel for firstprivate(k) private(tmp) shared(n,out) reduction(+:sum)"

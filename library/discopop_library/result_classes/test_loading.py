# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import types
from pathlib import Path
from typing import Any, Dict, Tuple

import jsonpickle  # type: ignore
import pytest

from discopop_explorer.classes.variable import Variable
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_library.result_classes.loading import load_detection_result, read_without_callpath_tree


def _result(tree: Dict[str, Tuple[str, str]]) -> Any:
    """A dump shaped like a DetectionResult: objects before and after the tree, shared across it (py/id)."""
    first = Variable("int", VarName("first"), "1:1")
    second = Variable("int", VarName("second"), "1:2")
    third = Variable("int", VarName("third"), "1:3")
    pet = types.SimpleNamespace(
        g=[first, second, [first]],
        callpath_tree=tree,
        later=[third, second, {"again": third}],
    )
    patterns = types.SimpleNamespace(do_all=[types.SimpleNamespace(pattern_id=0, _node=second, other=third)])
    return types.SimpleNamespace(pet=pet, patterns=patterns, enabled_patterns=["doall"])


def _tree(states: int) -> Dict[str, Tuple[str, str]]:
    return {str(i): (str(i - 1), "call_" + str(i) if i % 2 else "_ZN3fooEv") for i in range(1, states + 1)}


def _write(tmp_path: Path, result: Any) -> str:
    path = tmp_path / "detection_result_dump.json"
    path.write_text(jsonpickle.encode(result, keys=True))
    return str(path)


def _check(loaded: Any) -> None:
    assert loaded.pet.callpath_tree == {}
    first, second, nested = loaded.pet.g
    third, second_again, mapping = loaded.pet.later
    assert [first.name, second.name, third.name] == ["first", "second", "third"]
    assert nested[0] is first
    assert second_again is second
    assert mapping["again"] is third
    pattern = loaded.patterns.do_all[0]
    assert pattern._node is second
    assert pattern.other is third
    assert loaded.enabled_patterns == ["doall"]


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 64, 1 << 20])
def test_tree_is_left_out_and_references_stay_valid(tmp_path: Path, chunk_size: int) -> None:
    path = _write(tmp_path, _result(_tree(200)))
    text, left_out = read_without_callpath_tree(path, chunk_size)
    assert left_out
    assert "_ZN3fooEv" not in text
    _check(jsonpickle.decode(text, keys=True))


def test_load_detection_result(tmp_path: Path) -> None:
    _check(load_detection_result(_write(tmp_path, _result(_tree(1000)))))


@pytest.mark.parametrize("chunk_size", [1, 5, 1 << 20])
def test_empty_or_missing_tree_is_read_unchanged(tmp_path: Path, chunk_size: int) -> None:
    path = _write(tmp_path, _result({}))
    text, left_out = read_without_callpath_tree(path, chunk_size)
    assert not left_out
    assert text == Path(path).read_text()
    _check(load_detection_result(path))

    without = types.SimpleNamespace(pet=types.SimpleNamespace(g=[1]), patterns=[], enabled_patterns=[])
    path = _write(tmp_path, without)
    text, left_out = read_without_callpath_tree(path, chunk_size)
    assert not left_out
    assert text == Path(path).read_text()


def test_unexpected_end_of_tree_decodes_the_whole_file(tmp_path: Path) -> None:
    path = tmp_path / "detection_result_dump.json"
    path.write_text('{"pet": {"callpath_tree": {"1": ["0", "main"]}, "x": 1}, "patterns": []}')
    text, left_out = read_without_callpath_tree(str(path))
    assert not left_out
    assert text == path.read_text()

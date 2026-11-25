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

import networkx as nx

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.classes.variable import Variable
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_explorer.utilities.callpath_states import read_callpath_tree
from discopop_library.result_classes.DetectionResult import DetectionResult
from discopop_library.result_classes.loading import (
    LeftOutCallpathTree,
    load_detection_result,
    read_without_callpath_tree,
)


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


def _check(loaded: Any, left_out: bool = True) -> None:
    if left_out:
        assert isinstance(loaded.pet.callpath_tree, LeftOutCallpathTree)
    else:
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
    decoded = jsonpickle.decode(text, keys=True)
    assert decoded.pet.callpath_tree == {}
    decoded.pet.callpath_tree = LeftOutCallpathTree()
    _check(decoded)


def test_load_detection_result(tmp_path: Path) -> None:
    _check(load_detection_result(_write(tmp_path, _result(_tree(1000)))))


@pytest.mark.parametrize("chunk_size", [1, 5, 1 << 20])
def test_empty_or_missing_tree_is_read_unchanged(tmp_path: Path, chunk_size: int) -> None:
    path = _write(tmp_path, _result({}))
    text, left_out = read_without_callpath_tree(path, chunk_size)
    assert not left_out
    assert text == Path(path).read_text()
    _check(load_detection_result(path), left_out=False)

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


def test_the_left_out_tree_fails_on_use(tmp_path: Path) -> None:
    tree = load_detection_result(_write(tmp_path, _result(_tree(10)))).pet.callpath_tree
    for use in (
        lambda: tree["1"],
        lambda: "1" in tree,
        lambda: tree.get("1"),
        lambda: len(tree),
        lambda: list(tree),
        lambda: list(tree.items()),
    ):
        with pytest.raises(RuntimeError, match="left out"):
            use()


@pytest.mark.parametrize("chunk_size", [1, 3, 7, 1 << 20])
@pytest.mark.parametrize(
    "value",
    [
        pytest.param({"py/id": 3}, id="reference"),
        pytest.param(["0", "main"], id="list"),
        pytest.param({"parent": "0", "label": "main"}, id="dict"),
    ],
)
def test_a_tree_of_other_values_is_decoded_whole(tmp_path: Path, chunk_size: int, value: Any) -> None:
    """Values other than tuples of strings: the first "]}}" (here in "later") need not be the end of the tree."""
    tree = {str(i): (str(i - 1), "call_" + str(i)) for i in range(1, 20)}
    text = jsonpickle.encode(tree, keys=True)
    path = tmp_path / "detection_result_dump.json"
    entry = '"20": ' + jsonpickle.json.encode(value)
    path.write_text(
        '{"pet": {"callpath_tree": '
        + text[:-1]
        + ", "
        + entry
        + '}, "later": {"k": {"py/tuple": ["a"]}}}, "patterns": []}'
    )
    read, left_out = read_without_callpath_tree(str(path), chunk_size)
    assert not left_out
    assert read == path.read_text()


def test_a_decoding_error_after_the_cut_is_raised_with_a_note(tmp_path: Path) -> None:
    path = tmp_path / "detection_result_dump.json"
    path.write_text('{"pet": {"callpath_tree": {"1": {"py/tuple": ["0", "main"]}}, "x": }, "patterns": []}')
    with pytest.raises(Exception) as raised:
        load_detection_result(str(path))
    assert any("left out" in note for note in getattr(raised.value, "__notes__", []))


def test_a_real_detection_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The format the explorer writes: a DetectionResult of a PEGraphX whose tree was read from the profiler's
    file, with a pattern referring to a node of the graph (py/id across the cut)."""
    monkeypatch.chdir(tmp_path)  # PatternInfo allocates its id from a file in the working directory
    (tmp_path / "next_free_pattern_id.txt").write_text("0")
    main = CUNode(NodeID("1:1"))
    main.name = "main"
    loop = LoopNode(NodeID("1:2"))
    loop.name = "loop"
    for node in (main, loop):
        node.start_line = node.end_line = node.node_id
    loop.loop_data = None
    g = nx.MultiDiGraph()
    for node in (main, loop):
        g.add_node(node.id, data=node)
    pet = PEGraphX(g, [], pos={})
    mapping = tmp_path / "stateID_to_callpath_mapping.txt"
    mapping.write_text("".join(f"{i} {i - 1} {'call_' + str(i) if i % 2 else '_ZN3fooEv'}\n" for i in range(1, 500)))
    pet.callpath_tree = read_callpath_tree(str(mapping))
    result = DetectionResult(pet)
    result.patterns.do_all = [PatternInfo(loop)]  # type: ignore[list-item]
    result.enabled_patterns = ["doall"]
    path = tmp_path / "detection_result_dump.json"
    path.write_text(result.dump_to_pickled_json())

    text, left_out = read_without_callpath_tree(str(path), 1 << 10)
    assert left_out
    assert "_ZN3fooEv" not in text
    loaded = load_detection_result(str(path))
    assert isinstance(loaded.pet.callpath_tree, LeftOutCallpathTree)
    assert loaded.pet.main is loaded.pet.g.nodes["1:1"]["data"]
    assert loaded.patterns.do_all[0]._node is loaded.pet.g.nodes["1:2"]["data"]
    assert loaded.enabled_patterns == ["doall"]

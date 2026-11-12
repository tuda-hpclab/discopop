# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests of ``profiler/scripts/filter_ast_dump.py`` (a script of the profiler, not an installed module)."""

import importlib.util
import io
import json
import os
from types import ModuleType
from typing import Any

import pytest

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "profiler", "scripts", "filter_ast_dump.py")


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("filter_ast_dump", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fad = _load()

ROOT = "/proj"


def _translation_unit(n_system: int = 3) -> dict[str, Any]:
    inner: list[dict[str, Any]] = [
        {"kind": "TypedefDecl", "loc": {"file": "/usr/include/stdio.h", "line": 1}, "inner": [{"kind": "A"}]},
        # file omitted: inherited from the (dropped) previous sibling, so dropped as well
        {"kind": "FunctionDecl", "loc": {"line": 5}, "inner": [{"kind": "B", "loc": {"line": 6}}]},
        {
            "kind": "FunctionDecl",
            "loc": {"file": ROOT + "/main.cpp", "line": 1},
            "inner": [{"kind": "CompoundStmt", "loc": {"line": 2}, "inner": [{"kind": "ReturnStmt", "loc": {}}]}],
        },
        # macro expansion: the use site counts
        {
            "kind": "VarDecl",
            "loc": {"spellingLoc": {"file": "/usr/include/x.h"}, "expansionLoc": {"file": ROOT + "/a.hpp"}},
        },
        # relative path: project file
        {"kind": "VarDecl", "loc": {"file": "util.hpp", "line": 3}},
        {"kind": "VarDecl", "loc": {"line": 4}},
    ]
    for i in range(n_system):
        inner.append({"kind": "VarDecl", "loc": {"file": f"/usr/include/s{i}.h", "line": i}})
    return {"id": "0x1", "kind": "TranslationUnitDecl", "loc": {}, "range": {"begin": {}, "end": {}}, "inner": inner}


def _kinds(text: str) -> list[list[str]]:
    decoder = json.JSONDecoder()
    pos, result = 0, []
    while pos < len(text):
        obj, pos = decoder.raw_decode(text, pos)
        result.append([n["kind"] + ":" + str(n.get("loc", {}).get("file")) for n in obj["inner"]])
        while pos < len(text) and text[pos].isspace():
            pos += 1
    return result


def test_prunes_system_declarations_and_bakes_inherited_files() -> None:
    out = fad.filter_ast_dump(json.dumps(_translation_unit()), ROOT)
    assert _kinds(out) == [
        [
            "FunctionDecl:" + ROOT + "/main.cpp",
            "VarDecl:None",  # macro: file lives in expansionLoc
            "VarDecl:util.hpp",
            "VarDecl:util.hpp",  # inherited, baked into the loc
        ]
    ]
    kept = json.loads(out)["inner"]
    assert kept[3]["loc"]["file"] == "util.hpp"
    assert kept[1]["loc"]["expansionLoc"]["file"] == ROOT + "/a.hpp"


def test_header_is_preserved() -> None:
    obj = json.loads(fad.filter_ast_dump(json.dumps(_translation_unit()), ROOT))
    assert obj["id"] == "0x1" and obj["kind"] == "TranslationUnitDecl" and obj["range"] == {"begin": {}, "end": {}}


def test_concatenated_objects() -> None:
    text = json.dumps(_translation_unit()) + "\n" + json.dumps(_translation_unit(1)) + "\n"
    kinds = _kinds(fad.filter_ast_dump(text, ROOT))
    assert len(kinds) == 2 and kinds[0] == kinds[1]


def test_members_after_inner_and_missing_inner() -> None:
    tu = _translation_unit()
    tu["trailer"] = {"x": 1}
    obj = json.loads(fad.filter_ast_dump(json.dumps(tu), ROOT))
    assert obj["trailer"] == {"x": 1} and len(obj["inner"]) == 4
    assert json.loads(fad.filter_ast_dump('{"kind": "X"}', ROOT)) == {"kind": "X"}


def test_empty_inner_and_empty_input() -> None:
    assert json.loads(fad.filter_ast_dump('{"kind": "X", "inner": []}', ROOT))["inner"] == []
    assert fad.filter_ast_dump("  \n", ROOT) == ""


def test_strings_containing_structural_characters() -> None:
    tu = _translation_unit()
    tu["inner"][2]["name"] = '"inner": [ ] } {, \\'
    obj = json.loads(fad.filter_ast_dump(json.dumps(tu), ROOT))
    assert obj["inner"][0]["name"] == '"inner": [ ] } {, \\'


def test_input_larger_than_read_buffer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Declarations spanning several reads (small chunk size) give the same result as a single read."""
    tu = _translation_unit(200)
    tu["inner"][2]["inner"][0]["inner"] = [{"kind": "Big", "loc": {}, "text": "x" * 5000} for _ in range(50)]
    text = json.dumps(tu)
    expected = fad.filter_ast_dump(text, ROOT)
    monkeypatch.setattr(fad._Reader, "_MIN_CHUNK", 64)
    assert fad.filter_ast_dump(text, ROOT) == expected


def test_truncated_input_raises() -> None:
    text = json.dumps(_translation_unit())
    with pytest.raises((ValueError, json.JSONDecodeError)):
        fad.filter_ast_dump(text[: len(text) // 2], ROOT)
    with pytest.raises(ValueError):
        fad.filter_ast_dump(text[: text.rindex("]")], ROOT)


def test_stream_interface() -> None:
    out = io.StringIO()
    fad.filter_ast_stream(io.StringIO(json.dumps(_translation_unit())), out, ROOT + "/")
    assert len(json.loads(out.getvalue())["inner"]) == 4


def _reference(text: str) -> Any:
    """The whole-object algorithm: parse everything, then prune."""
    obj = json.loads(text)
    obj["inner"] = fad._filter_children(obj["inner"], None, ROOT + "/")
    return obj


def _namespace_dump() -> dict[str, Any]:
    tu = _translation_unit(2)
    tu["inner"] += [
        # system namespace: dropped with everything in it, even a child claiming a project file
        {
            "id": "0x2",
            "kind": "NamespaceDecl",
            "loc": {"file": "/usr/include/c++/vector", "line": 1},
            "name": "std",
            "inner": [
                {"kind": "FunctionDecl", "loc": {"line": 2}, "inner": [{"kind": "Z", "loc": {}}]},
                {"kind": "FunctionDecl", "loc": {"file": ROOT + "/in_std.cpp"}},
                {"id": "0x9", "kind": "NamespaceDecl", "loc": {"line": 9}, "name": "inner_ns", "inner": []},
            ],
        },
        # project namespace: kept; children are pruned individually, the inherited file is the namespace's
        {
            "id": "0x3",
            "kind": "NamespaceDecl",
            "loc": {"file": ROOT + "/ns.hpp", "line": 1},
            "name": "app",
            "inner": [
                {"kind": "FunctionDecl", "loc": {"line": 2}},
                {"kind": "VarDecl", "loc": {"file": "/usr/include/y.h", "line": 3}},
                {"kind": "VarDecl", "loc": {"line": 4}},
                {
                    "id": "0x4",
                    "kind": "NamespaceDecl",
                    "loc": {"line": 5},
                    "name": "nested",
                    "inner": [{"kind": "FunctionDecl", "loc": {"line": 6}}],
                },
                {"id": "0x5", "kind": "LinkageSpecDecl", "loc": {"line": 7}, "language": "C", "inner": []},
            ],
        },
        # namespace without children (no ``inner`` key), directly followed by another container
        {"id": "0x6", "kind": "NamespaceDecl", "loc": {"file": ROOT + "/e.cpp", "line": 1}, "name": "empty"},
        {
            "id": "0x7",
            "kind": "LinkageSpecDecl",
            "loc": {"file": ROOT + "/e.cpp", "line": 2},
            "language": "C",
            "inner": [{"kind": "FunctionDecl", "loc": {"line": 3}}],
        },
    ]
    return tu


@pytest.mark.parametrize("indent", [None, 2])
@pytest.mark.parametrize("chunk", [1 << 20, 64, 7])
@pytest.mark.parametrize("max_decode", [64 << 20, 200, 1])
def test_equals_whole_object_algorithm(
    monkeypatch: pytest.MonkeyPatch, indent: Any, chunk: int, max_decode: int
) -> None:
    """Any declaration larger than ``max_decode`` is read member by member (namespaces always are)."""
    monkeypatch.setattr(fad._Reader, "_MIN_CHUNK", chunk)
    monkeypatch.setattr(fad, "_MAX_DECODE", max_decode)
    for dump in (_namespace_dump(), _translation_unit()):
        text = json.dumps(dump, indent=indent)
        assert json.loads(fad.filter_ast_dump(text, ROOT)) == _reference(text)


def test_large_non_namespace_declaration_is_streamed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A class template with a huge, deeply nested ``inner`` tree is never decoded as a whole."""
    deep: dict[str, Any] = {"kind": "Leaf", "loc": {"line": 1}}
    for i in range(300):
        deep = {"id": str(i), "kind": "ElaboratedType", "loc": {"line": i}, "inner": [deep, {"kind": "Sibling"}]}
    tu = _translation_unit(1)
    tu["inner"].append(
        {"id": "0xa", "kind": "ClassTemplateDecl", "loc": {"file": ROOT + "/t.hpp", "line": 1}, "inner": [deep]}
    )
    text = json.dumps(tu, indent=2)
    monkeypatch.setattr(fad._Reader, "_MIN_CHUNK", 4096)
    monkeypatch.setattr(fad, "_MAX_DECODE", 8192)
    decoded_sizes: list[int] = []
    original = json.JSONDecoder.raw_decode

    def spy(self: json.JSONDecoder, s: str, idx: int = 0) -> Any:
        result = original(self, s, idx)
        decoded_sizes.append(result[1] - idx)
        return result

    with monkeypatch.context() as spied:
        spied.setattr(json.JSONDecoder, "raw_decode", spy)
        out = fad.filter_ast_dump(text, ROOT)
    assert max(decoded_sizes) < len(text) // 20
    assert json.loads(out) == _reference(text)


def test_dropped_namespace_children_are_not_kept() -> None:
    names = [n.get("name") for n in json.loads(fad.filter_ast_dump(json.dumps(_namespace_dump()), ROOT))["inner"]]
    assert "std" not in names and "app" in names and "empty" in names

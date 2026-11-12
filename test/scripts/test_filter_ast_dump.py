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
    assert json.loads(fad.filter_ast_dump('{"kind": "X"}', ROOT)) == {"kind": "X", "inner": []}


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

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
    fad.filter_ast_stream(io.StringIO(json.dumps(_translation_unit())), out, fad._Policy(ROOT + "/"))
    assert len(json.loads(out.getvalue())["inner"]) == 4


def _reference(text: str, policy: Any = None) -> Any:
    """The whole-object algorithm: parse everything, then prune."""
    obj = json.loads(text)
    obj["inner"] = fad._filter_children(obj["inner"], None, policy or fad._Policy(ROOT))
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
        deep = {"id": str(i), "kind": "Wrapper", "loc": {"line": i}, "inner": [deep, {"kind": "Sibling"}]}
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


def _mapping(tmp_path: Any, *files: str) -> str:
    path = tmp_path / "FileMapping.txt"
    path.write_text("".join(f"{i}\t{f}\n" for i, f in enumerate(files, 1)))
    return str(path)


def test_keeps_only_mapped_files(tmp_path: Any) -> None:
    """Files below the project directory that the profiler did not map (dependencies, headers) are dropped."""
    mapping = _mapping(tmp_path, ROOT + "/main.cpp", ROOT + "/./sub/../a.hpp")
    tu = _translation_unit(0)
    tu["inner"].append({"kind": "FunctionDecl", "loc": {"file": ROOT + "/_deps/boost/x.hpp", "line": 1}})
    tu["inner"].append({"kind": "FunctionDecl", "loc": {"file": ROOT + "/a.hpp", "line": 1}})
    out = json.loads(fad.filter_ast_dump(json.dumps(tu), ROOT, mapping))
    files = [(n.get("loc") or {}).get("file") for n in out["inner"]]
    assert ROOT + "/_deps/boost/x.hpp" not in files
    # main.cpp (mapped) and a.hpp (mapped, after normalization of its entry) stay; util.hpp is relative to the working
    # directory and not mapped
    assert ROOT + "/main.cpp" in files and ROOT + "/a.hpp" in files and "util.hpp" not in files


def test_relative_paths_are_resolved_against_the_working_directory(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    mapping = _mapping(tmp_path, str(tmp_path / "util.hpp"))
    tu = _translation_unit(0)
    out = json.loads(fad.filter_ast_dump(json.dumps(tu), str(tmp_path), mapping))
    assert [(n["loc"].get("file")) for n in out["inner"] if n["kind"] == "VarDecl" and "file" in n["loc"]] == [
        "util.hpp",
        "util.hpp",  # the second declaration inherits the file, which is baked in
    ]


@pytest.mark.parametrize("content", [None, ""])
def test_without_file_mapping_the_project_directory_decides(tmp_path: Any, content: Any) -> None:
    mapping = str(tmp_path / "absent.txt")
    if content is not None:
        (tmp_path / "FileMapping.txt").write_text(content)
        mapping = str(tmp_path / "FileMapping.txt")
    plain = fad.filter_ast_dump(json.dumps(_translation_unit()), ROOT)
    assert fad.filter_ast_dump(json.dumps(_translation_unit()), ROOT, mapping) == plain


def test_type_nodes_are_pruned() -> None:
    func = {
        "id": "0xf",
        "kind": "FunctionDecl",
        "loc": {"file": ROOT + "/m.cpp", "line": 1},
        "type": {"qualType": "int (int)"},
        "inner": [
            {
                "kind": "ParmVarDecl",
                "loc": {"line": 1},
                "inner": [{"kind": "BuiltinType", "type": {"qualType": "int"}}],
            },
            {"kind": "ElaboratedType", "inner": [{"kind": "TemplateArgument", "inner": [{"kind": "RecordType"}]}]},
            {"kind": "CompoundStmt", "loc": {"line": 2}},
        ],
    }
    tu = {"id": "0x1", "kind": "TranslationUnitDecl", "loc": {}, "inner": [func]}
    out = json.loads(fad.filter_ast_dump(json.dumps(tu), ROOT))["inner"][0]
    assert out["type"] == {"qualType": "int (int)"}
    assert [c["kind"] for c in out["inner"]] == ["ParmVarDecl", "CompoundStmt"]
    assert "inner" not in out["inner"][0] or out["inner"][0]["inner"] == []
    kept = json.loads(fad.filter_ast_dump(json.dumps(tu), ROOT, prune_types=False))["inner"][0]
    assert [c["kind"] for c in kept["inner"]] == ["ParmVarDecl", "ElaboratedType", "CompoundStmt"]


@pytest.mark.parametrize("max_decode", [64 << 20, 1])
def test_type_pruning_in_streamed_declarations(monkeypatch: pytest.MonkeyPatch, max_decode: int) -> None:
    monkeypatch.setattr(fad, "_MAX_DECODE", max_decode)
    monkeypatch.setattr(fad._Reader, "_MIN_CHUNK", 16)
    alias = {
        "id": "0xa",
        "kind": "TypeAliasDecl",
        "loc": {"file": ROOT + "/t.hpp", "line": 1},
        "inner": [{"kind": "ElaboratedType", "inner": [{"kind": "TemplateSpecializationType", "inner": []}]}] * 5,
    }
    ns = {"id": "0xb", "kind": "NamespaceDecl", "loc": {"file": ROOT + "/t.hpp", "line": 1}, "inner": [alias]}
    tu = {"id": "0x1", "kind": "TranslationUnitDecl", "loc": {}, "inner": [ns]}
    out = json.loads(fad.filter_ast_dump(json.dumps(tu, indent=1), ROOT))
    assert out["inner"][0]["inner"][0]["inner"] == []


def _status_of(tu: dict[str, Any], policy: Any, monkeypatch: Any = None, interval: Any = None) -> list[str]:
    if monkeypatch is not None and interval is not None:
        monkeypatch.setattr(fad._Status, "PROGRESS_INTERVAL", interval)
    log = io.StringIO()
    fad.filter_ast_stream(io.StringIO(json.dumps(tu)), io.StringIO(), policy, log)
    assert all(line.startswith(fad._Status.PREFIX) for line in log.getvalue().splitlines())
    return log.getvalue().splitlines()


def test_status_without_file_mapping() -> None:
    lines = _status_of(_translation_unit(3), fad._Policy(ROOT))
    assert len(lines) == 2  # a short run: the policy and the summary
    assert f"no file mapping given, keeping the declarations below {ROOT}/" in lines[0]
    assert "type nodes are dropped" in lines[0]
    # the two leading declarations of the test dump (a system typedef, and a function inheriting its file) and the
    # three system variables are dropped; what is kept counts the nodes below the kept declarations as well
    assert "dropped 5 subtrees outside the project directory, 0 type nodes" in lines[1]
    assert "kept 7 nodes" in lines[1] and lines[1].split("done in ")[1][0].isdigit()


def test_status_with_file_mapping_and_types(tmp_path: Any) -> None:
    mapping = _mapping(tmp_path, ROOT + "/main.cpp", ROOT + "/a.hpp")
    tu = _translation_unit(0)
    tu["inner"][2]["inner"].append({"kind": "ElaboratedType"})
    lines = _status_of(tu, fad._Policy(ROOT, mapping))
    assert f"keeping the declarations of the 2 files of {mapping}" in lines[0]
    assert "1 type node," in lines[1].replace("outside the mapped files, ", "") or "1 type node" in lines[1]
    assert "outside the mapped files" in lines[1]


def test_status_names_a_missing_file_mapping(tmp_path: Any) -> None:
    lines = _status_of(_translation_unit(1), fad._Policy(ROOT, str(tmp_path / "absent.txt")))
    assert "is missing or empty (no files are mapped yet)" in lines[0]
    assert f"below {ROOT}/" in lines[0]


def test_status_counts_declarations_read_member_by_member(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fad, "_MAX_DECODE", 1)
    lines = _status_of(_namespace_dump(), fad._Policy(ROOT))
    assert "1 large declaration read member by member" not in lines[-1]  # several: the namespaces and what is large
    assert "large declarations read member by member" in lines[-1]


def test_status_progress_for_long_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    tu = _translation_unit(500)
    monkeypatch.setattr(fad._Reader, "_MIN_CHUNK", 256)
    lines = _status_of(tu, fad._Policy(ROOT), monkeypatch, interval=0.0)
    progress = [line for line in lines if " s: read " in line and "done in" not in line]
    assert len(progress) > 3 and all("/s)" in line for line in progress)
    assert lines[-1].startswith(fad._Status.PREFIX + "done in ")


def test_no_status_without_log() -> None:
    out = io.StringIO()
    fad.filter_ast_stream(io.StringIO(json.dumps(_translation_unit())), out, fad._Policy(ROOT))
    assert json.loads(out.getvalue())["kind"] == "TranslationUnitDecl"


@pytest.mark.parametrize("quiet", [False, True])
def test_command_line_status_goes_to_stderr_and_can_be_silenced(tmp_path: Any, quiet: bool) -> None:
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k != "DP_AST_QUIET"}
    if quiet:
        env["DP_AST_QUIET"] = "1"
    result = subprocess.run(
        [sys.executable, _SCRIPT, ROOT],
        input=json.dumps(_translation_unit()),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["kind"] == "TranslationUnitDecl"  # stdout is nothing but the pruned AST
    assert (result.stderr == "") == quiet
    if not quiet:
        assert "DiscoPoP AST filter: done in" in result.stderr


def test_size_and_plural_formatting() -> None:
    assert [fad._size(n) for n in (0, 999, 1500, 2_500_000, 3_400_000_000, 7e12)] == [
        "0 B",
        "999 B",
        "1.5 KB",
        "2.5 MB",
        "3.4 GB",
        "7000.0 GB",
    ]
    assert fad._plural(1, "file") == "1 file" and fad._plural(0, "file") == "0 files"
    assert fad._plural(1234, "node") == "1,234 nodes"


@pytest.mark.parametrize("root_through_link", [True, False])
def test_project_directory_behind_a_symbolic_link(tmp_path: Any, root_through_link: bool) -> None:
    """Without a file mapping, a file below the project directory is kept whichever side resolved the link."""
    real = tmp_path / "storage" / "project"
    real.mkdir(parents=True)
    (real / "main.cpp").write_text("")
    link = tmp_path / "home_project"
    link.symlink_to(real)
    root, file_dir = (link, real) if root_through_link else (real, link)
    tu = {
        "id": "0x1",
        "kind": "TranslationUnitDecl",
        "loc": {},
        "inner": [
            {"kind": "FunctionDecl", "loc": {"file": str(file_dir / "main.cpp"), "line": 1}},
            {"kind": "FunctionDecl", "loc": {"file": "/usr/include/stdio.h", "line": 1}},
        ],
    }
    out = json.loads(fad.filter_ast_dump(json.dumps(tu), str(root)))
    assert [n["loc"]["file"] for n in out["inner"]] == [str(file_dir / "main.cpp")]

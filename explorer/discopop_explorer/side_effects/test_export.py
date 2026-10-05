# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Tests for the side effect export: the record mapping of the TaskGraph, the instance tree,
the executed call edges, the AST facts and the file format."""

from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pytest

from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.TaskGraph.Contexts.Context import Context
from discopop_explorer.classes.TaskGraph.Contexts.FunctionContext import FunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.InlinedFunctionContext import InlinedFunctionContext
from discopop_explorer.classes.TaskGraph.Contexts.IterationContext import IterationContext
from discopop_explorer.classes.TaskGraph.Contexts.WorkContext import WorkContext
from discopop_explorer.classes.TaskGraph.Functions.TGStartFunctionNode import TGStartFunctionNode
from discopop_explorer.side_effects import export as export_module
from discopop_explorer.side_effects.export import (
    _AstFacts,
    _base_name,
    _collect_instances,
    _LineToFunction,
    _read_executed_calls,
    write_export,
)
from discopop_explorer.side_effects.schema import (
    FORMAT_VERSION,
    ExportFormatError,
    dependency_file_info,
    load_export,
    save_export,
)
from discopop_explorer.utilities.ASTUtils.ASTGraph import ClangASTGraph

# ---------------------------------------------------------------------------
# TaskGraph.map_dynamic_dependency_records
# ---------------------------------------------------------------------------


def _task_graph_with_mapping(
    build_task_graph: Any,
    build_pet_graph: Any,
    tmp_path: Path,
    dependency_lines: List[str],
    mapping: Dict[Tuple[str, str], Set[Context]],
) -> Any:
    """A TaskGraph whose context lookup is replaced by ``mapping`` {(instruction, state): contexts}."""
    dep_file = tmp_path / "dynamic_dependencies.txt"
    dep_file.write_text("\n".join(dependency_lines) + "\n")
    instructions = sorted({loc for loc, _ in mapping} | {"1", "2", "3", "4", "5", "6"})
    (tmp_path / "instructionID_to_lineID_mapping.txt").write_text(
        "\n".join(f"{i} 1:{10 + int(i)}:1" for i in instructions if i.isdigit()) + "\n"
    )
    tg = build_task_graph(build_pet_graph([]))
    tg.dynamic_dependency_file = str(dep_file)
    tg.static_dependency_file = None
    tg.ignore_dependency_states = False

    def lookup(_pet: Any, location: str, state_id: str, *_args: Any) -> Set[Context]:
        return set(mapping.get((location, state_id), set()))

    tg._TaskGraph__get_work_contexts_by_location_and_state_id = lookup
    tg._TaskGraph__get_state_mappings_from_file = lambda _f: {}
    return tg


def test_records_map_both_ends_and_keep_only_dynamic_ones(
    build_task_graph: Any, build_pet_graph: Any, tmp_path: Path
) -> None:
    a, b = WorkContext(), WorkContext()
    tg = _task_graph_with_mapping(
        build_task_graph,
        build_pet_graph,
        tmp_path,
        [
            "2@7 NOM  RAW 1@8|g(123)",
            "5 NOM  RAW 4|local(S-1)",  # static: never crosses a function, not exported
            "START 1:1",
        ],
        {("2", "7"): {a}, ("1", "8"): {b}},
    )

    records = tg.map_dynamic_dependency_records()

    assert len(records) == 1
    record = records[0]
    assert (record.dep_type, record.var_name) == ("RAW", "g")
    assert record.first == (2, 7, "1:12")
    assert record.other == (1, 8, "1:11")
    assert record.pairs == [(a, b)]
    assert (record.first_contexts, record.other_contexts) == ([a], [b])


def test_stack_local_records_with_states_are_not_exported(
    build_task_graph: Any, build_pet_graph: Any, tmp_path: Path
) -> None:
    # the hybrid analysis records the local copy of a pointer parameter p under the name p, with
    # callpath states; it must not pass for an access to the pointee of p
    a, b = WorkContext(), WorkContext()
    tg = _task_graph_with_mapping(
        build_task_graph,
        build_pet_graph,
        tmp_path,
        [
            "2@7 NOM  RAW 1@8|p(S12) RAW 1@8|g(123)",
            "4@7 NOM  INIT *|p(S-3)",
            "START 1:1",
        ],
        {("2", "7"): {a}, ("1", "8"): {b}, ("4", "7"): {a}},
    )

    records = tg.map_dynamic_dependency_records()

    assert [(r.dep_type, r.var_name) for r in records] == [("RAW", "g")]


def test_init_maps_only_its_first_end(build_task_graph: Any, build_pet_graph: Any, tmp_path: Path) -> None:
    a = WorkContext()
    tg = _task_graph_with_mapping(
        build_task_graph, build_pet_graph, tmp_path, ["3@9 NOM  INIT 0@0|g_sink(1)"], {("3", "9"): {a}}
    )

    (record,) = tg.map_dynamic_dependency_records()

    assert record.dep_type == "INIT"
    assert record.other is None
    assert record.pairs == []
    assert record.first_contexts == [a]


def test_ends_without_state_and_self_pairs_are_dropped(
    build_task_graph: Any, build_pet_graph: Any, tmp_path: Path
) -> None:
    a, b = WorkContext(), WorkContext()
    tg = _task_graph_with_mapping(
        build_task_graph,
        build_pet_graph,
        tmp_path,
        [
            "2@7 NOM  RAW 1|x(1)",  # other end without state: cannot be attributed to a call
            "2@7 NOM  WAW 1@7|y(1)",  # both ends map to {a, b}: only the cross pairs remain
        ],
        {("2", "7"): {a, b}, ("1", "7"): {a, b}},
    )

    records = tg.map_dynamic_dependency_records()

    assert [r.var_name for r in records] == ["y"]
    # same state, no iteration ancestors on either side: the same-state rule keeps both cross pairs
    assert sorted((p[0].creation_index, p[1].creation_index) for p in records[0].pairs) == sorted(
        [(a.creation_index, b.creation_index), (b.creation_index, a.creation_index)]
    )


def test_same_state_pairs_require_the_same_iteration(
    build_task_graph: Any, build_pet_graph: Any, tmp_path: Path
) -> None:
    """The rule of the dependency insertion: with equal states, both ends must share their
    ancestors from the closest iteration context on."""
    loop = WorkContext()
    first_iteration = IterationContext(loop, [0])
    second_iteration = IterationContext(loop, [1])
    a, b = WorkContext(), WorkContext()
    a.parent_context = first_iteration
    b.parent_context = second_iteration
    tg = _task_graph_with_mapping(
        build_task_graph,
        build_pet_graph,
        tmp_path,
        ["2@7 NOM  RAW 1@7|x(1)", "4@7 NOM  RAW 3@8|z(1)"],
        {("2", "7"): {a}, ("1", "7"): {b}, ("4", "7"): {a}, ("3", "8"): {b}},
    )

    records = {r.var_name: r for r in tg.map_dynamic_dependency_records()}

    assert records["x"].pairs == []  # same state, different iterations: filtered
    assert records["z"].pairs == [(a, b)]  # different states: not filtered


def test_mapping_does_not_touch_the_registered_dependencies(
    build_task_graph: Any, build_pet_graph: Any, tmp_path: Path
) -> None:
    a, b = WorkContext(), WorkContext()
    tg = _task_graph_with_mapping(
        build_task_graph, build_pet_graph, tmp_path, ["2@7 NOM  RAW 1@8|g(1)"], {("2", "7"): {a}, ("1", "8"): {b}}
    )

    tg.map_dynamic_dependency_records()

    assert a.outgoing_dependencies == set() and b.incoming_dependencies == set()


# ---------------------------------------------------------------------------
# instance tree
# ---------------------------------------------------------------------------


class _Function:
    """Stand-in for a FunctionNode: _collect_instances only reads id and name."""

    def __init__(self, node_id: str, name: str) -> None:
        self.id = node_id
        self.name = name


def _instance(function_id: str, parent: Optional[Context]) -> FunctionContext:
    context = FunctionContext(NodeID(function_id))
    context.contained_nodes.append(TGStartFunctionNode(NodeID(function_id), 0, 0))
    context.parent_context = parent
    return context


def _child(context_type: Any, parent: Context, *args: Any) -> Any:
    child = context_type(*args)
    child.parent_context = parent
    return child


def test_instances_below_main_with_call_instructions(build_task_graph: Any, build_pet_graph: Any) -> None:
    main = _instance("1:1", None)
    call = _child(InlinedFunctionContext, main, 77)
    callee = _instance("1:5", call)
    work_main = _child(WorkContext, main)
    work_callee = _child(WorkContext, callee)
    top_level_copy = _instance("1:5", None)  # not reachable from main: dropped
    work_top_level = _child(WorkContext, top_level_copy)
    tg = build_task_graph(build_pet_graph([]))
    tg.contexts = [main, call, callee, work_main, work_callee, top_level_copy, work_top_level]

    instances, work_contexts, context_ids = _collect_instances(
        tg, [_Function("1:1", "main"), _Function("1:5", "f")]  # type: ignore[list-item]
    )

    by_function = {i["function"]: i for i in instances}
    assert set(by_function) == {"1:1", "1:5"} and len(instances) == 2
    assert by_function["1:1"]["parent"] is None and by_function["1:1"]["call_instruction_id"] is None
    assert by_function["1:5"]["parent"] == by_function["1:1"]["id"]
    assert by_function["1:5"]["call_instruction_id"] == 77
    assert work_contexts == {
        str(context_ids[work_main]): by_function["1:1"]["id"],
        str(context_ids[work_callee]): by_function["1:5"]["id"],
    }
    assert work_top_level not in context_ids


def test_instance_tree_with_a_containment_cycle_terminates(build_task_graph: Any, build_pet_graph: Any) -> None:
    a = _instance("1:5", None)
    b = _instance("1:5", a)
    a.parent_context = b  # inconsistent relation, see INVARIANTS.md section 7
    tg = build_task_graph(build_pet_graph([]))
    tg.contexts = [a, b]

    instances, _work_contexts, _ids = _collect_instances(tg, [_Function("1:5", "f")])  # type: ignore[list-item]

    assert instances == []


# ---------------------------------------------------------------------------
# executed call edges
# ---------------------------------------------------------------------------


class _Span:
    def __init__(self, node_id: str, start: int, end: int, file_id: int = 1, name: str = "f") -> None:
        self.id, self.start_line, self.end_line, self.file_id, self.name = node_id, start, end, file_id, name


def test_executed_calls_from_bgn_func_and_start(tmp_path: Path) -> None:
    functions = [_Span("1:1", 50, 60, name="main"), _Span("1:5", 10, 12), _Span("1:9", 20, 22)]
    file_ids = {f: 1 for f in functions}
    dep_file = tmp_path / "dynamic_dependencies.txt"
    dep_file.write_text(
        "\n".join(
            [
                "START 1:50",
                "0:3 BGN func 1:50",  # into main after a global constructor: ignored, main comes from START
                "1:52 BGN loop 4 1 1 1",
                "0:7 BGN func 1:10",  # call instruction 7 in main calls 1:5
                "1:11 BGN func 1:20",  # no call instruction logged: callback, caller by line
                "0:7 BGN func 1:10",  # duplicate
                "1:12 END func",
            ]
        )
        + "\n"
    )
    (tmp_path / "instructionID_to_lineID_mapping.txt").write_text("7 1:55:3\n")

    calls = _read_executed_calls(str(dep_file), functions, _LineToFunction(functions, file_ids))  # type: ignore[arg-type]

    assert calls == [
        {"caller": None, "call_instruction_id": None, "callee": "1:1"},
        {"caller": "1:1", "call_instruction_id": 7, "callee": "1:5"},
        {"caller": "1:5", "call_instruction_id": None, "callee": "1:9"},
    ]


def test_line_to_function_picks_the_innermost_function() -> None:
    outer, inner = _Span("1:1", 1, 100), _Span("1:2", 40, 50)
    lookup = _LineToFunction([outer, inner], {outer: 1, inner: 1})  # type: ignore[list-item, dict-item]

    assert lookup.lookup("1:45") == "1:2"
    assert lookup.lookup("1:10") == "1:1"
    assert lookup.lookup("2:45") is None
    assert lookup.lookup(None) is None


# ---------------------------------------------------------------------------
# AST facts
# ---------------------------------------------------------------------------


def _decl_ref(node_id: str, name: str, referenced_id: str, kind: str = "VarDecl", type_name: str = "int") -> Any:
    return {
        "id": node_id,
        "kind": "DeclRefExpr",
        "type": {"qualType": type_name},
        "referencedDecl": {"id": referenced_id, "kind": kind, "name": name},
    }


def _ast() -> Dict[str, Any]:
    """int g; const int t[2]; void f(int *p, int n) { static int calls; int *q; g = n; s->second = t[0]; memset(p, 0, n); }"""
    loc = {"file": "/src/code.cpp", "line": 3}
    return {
        "kind": "TranslationUnitDecl",
        "id": "0x1",
        "inner": [
            {
                "id": "0x10",
                "kind": "VarDecl",
                "name": "g",
                "loc": {"file": "/src/code.cpp", "line": 1},
                "type": {"qualType": "int"},
            },
            {"id": "0x11", "kind": "VarDecl", "name": "t", "loc": {"line": 2}, "type": {"qualType": "const int[2]"}},
            {"id": "0x12", "kind": "VarDecl", "name": "gp", "type": {"qualType": "const int *"}},
            {"id": "0x13", "kind": "VarDecl", "name": "gq", "type": {"qualType": "int *const"}},
            {
                "id": "0x20",
                "kind": "FunctionDecl",
                "name": "f",
                "mangledName": "_Z1fPii",
                "loc": loc,
                "inner": [
                    {"id": "0x21", "kind": "ParmVarDecl", "name": "p", "type": {"qualType": "int *"}},
                    {"id": "0x22", "kind": "ParmVarDecl", "name": "n", "type": {"qualType": "int"}},
                    {
                        "id": "0x30",
                        "kind": "CompoundStmt",
                        "inner": [
                            {
                                "id": "0x31",
                                "kind": "DeclStmt",
                                "inner": [
                                    {
                                        "id": "0x32",
                                        "kind": "VarDecl",
                                        "name": "calls",
                                        "storageClass": "static",
                                        "mangledName": "_ZZ1fPiiE5calls",
                                        "type": {"qualType": "int"},
                                    },
                                    {"id": "0x33", "kind": "VarDecl", "name": "q", "type": {"qualType": "int *"}},
                                    {
                                        "id": "0x34",
                                        "kind": "VarDecl",
                                        "name": "ext",
                                        "storageClass": "extern",
                                        "type": {"qualType": "int"},
                                    },
                                ],
                            },
                            {
                                "id": "0x40",
                                "kind": "BinaryOperator",
                                "opcode": "=",
                                "loc": {"line": 4},
                                "inner": [
                                    _decl_ref("0x41", "g", "0x10"),
                                    {
                                        "id": "0x42",
                                        "kind": "ImplicitCastExpr",
                                        "inner": [_decl_ref("0x43", "n", "0x22", "ParmVarDecl")],
                                    },
                                ],
                            },
                            {
                                "id": "0x50",
                                "kind": "BinaryOperator",
                                "opcode": "=",
                                "loc": {"line": 5},
                                "inner": [
                                    {
                                        "id": "0x51",
                                        "kind": "MemberExpr",
                                        "name": "second",
                                        "inner": [
                                            {
                                                "id": "0x52",
                                                "kind": "ImplicitCastExpr",
                                                "inner": [_decl_ref("0x53", "s", "0x99", "ParmVarDecl")],
                                            }
                                        ],
                                    },
                                    {
                                        "id": "0x54",
                                        "kind": "ImplicitCastExpr",
                                        "inner": [
                                            {
                                                "id": "0x55",
                                                "kind": "ArraySubscriptExpr",
                                                "inner": [
                                                    {
                                                        "id": "0x56",
                                                        "kind": "ImplicitCastExpr",
                                                        "inner": [
                                                            _decl_ref("0x57", "t", "0x11", type_name="const int[2]")
                                                        ],
                                                    },
                                                    {"id": "0x58", "kind": "IntegerLiteral"},
                                                ],
                                            }
                                        ],
                                    },
                                ],
                            },
                            {
                                "id": "0x70",
                                "kind": "CXXOperatorCallExpr",
                                "inner": [
                                    {
                                        "id": "0x71",
                                        "kind": "ImplicitCastExpr",
                                        "inner": [_decl_ref("0x72", "operator=", "0x97", "CXXMethodDecl")],
                                    }
                                ],
                            },
                            {"id": "0x73", "kind": "CXXConstructExpr", "type": {"qualType": "std::basic_string<char>"}},
                            {
                                "id": "0x60",
                                "kind": "CallExpr",
                                "loc": {"line": 6},
                                "inner": [
                                    {
                                        "id": "0x61",
                                        "kind": "ImplicitCastExpr",
                                        "inner": [_decl_ref("0x62", "memset", "0x98", "FunctionDecl")],
                                    }
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    }


class _AstHelper:
    def __init__(self, ast: Dict[str, Any]) -> None:
        self.graph = ClangASTGraph().build_from_ast(ast)

    def get_ast_graph(self) -> Any:
        return self.graph


class _Named:
    def __init__(self, node_id: str, name: str, file_id: int, start_line: int) -> None:
        self.id, self.name, self.file_id, self.start_line = node_id, name, file_id, start_line


def test_ast_facts_of_a_function() -> None:
    function = _Named("1:5", "_Z1fPii", 1, 3)
    facts_by_function = _AstFacts(_AstHelper(_ast()), {1: "/src/code.cpp"}, [function])  # type: ignore[arg-type, list-item]

    facts = facts_by_function.function_facts(function)  # type: ignore[arg-type]

    assert facts.found
    assert facts.params == [{"name": "p", "reachable": True}, {"name": "n", "reachable": False}]
    assert {l["name"]: (l["pointer"], l["static"]) for l in facts.locals} == {
        "calls": (False, True),
        "q": (True, False),
        "ext": (False, True),  # block-scope extern: persistent state, like a static local
    }
    assert facts.member_accesses == {"5": {"second": "s"}}
    assert {(r["name"], r["access"]) for r in facts.global_refs} == {("g", "write"), ("t", "read")}
    # calls the profiler cannot see: library functions, operators and constructors without a definition
    assert facts.called_names - facts_by_function.defined_function_names == {"memset", "operator=", "basic_string"}
    # only top-level const counts: gp points to const data but can itself be changed
    assert facts_by_function.globals == [
        {"name": "g", "const": False},
        {"name": "gp", "const": False},
        {"name": "gq", "const": True},
        {"name": "t", "const": True},
    ]
    # the profiler records function-static locals under their linker name
    assert facts_by_function.linker_names == {"_ZZ1fPiiE5calls": "calls"}


def test_function_without_ast_facts_falls_back_to_location_then_to_empty() -> None:
    by_location = _Named("1:5", "f_unmangled_other_name", 1, 3)
    unknown = _Named("1:9", "_Z7unknownv", 1, 40)
    facts = _AstFacts(_AstHelper(_ast()), {1: "/src/code.cpp"}, [by_location, unknown])  # type: ignore[arg-type, list-item]
    facts.file_ids_of_functions = {by_location: 1, unknown: 1}  # type: ignore[dict-item]

    assert facts.function_facts(by_location).found  # type: ignore[arg-type]
    assert not facts.function_facts(unknown).found  # type: ignore[arg-type]
    assert not _AstFacts(None, {}, []).function_facts(unknown).found  # type: ignore[arg-type]


@pytest.mark.parametrize(  # type: ignore[misc]
    "name, expected",
    [
        ("ns::Cls::method(int) const", "method"),
        ("std::vector<int, std::allocator<int> >::operator[](unsigned long)", "operator[]"),
        ("write_global(int)", "write_global"),
        ("main", "main"),
    ],
)
def test_base_name(name: str, expected: str) -> None:
    assert _base_name(name) == expected


# ---------------------------------------------------------------------------
# file format and failure isolation
# ---------------------------------------------------------------------------


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "explorer" / "side_effects.json.gz"
    data: Any = {"format_version": FORMAT_VERSION, "functions": [], "records": []}

    save_export(data, path)

    assert load_export(path) == data
    assert not (tmp_path / "explorer" / "side_effects.json.gz.tmp").exists()


def test_load_rejects_missing_unreadable_and_other_versions(tmp_path: Path) -> None:
    with pytest.raises(ExportFormatError):
        load_export(tmp_path / "missing.json.gz")
    broken = tmp_path / "broken.json.gz"
    broken.write_bytes(b"not gzip")
    with pytest.raises(ExportFormatError):
        load_export(broken)
    old = tmp_path / "old.json.gz"
    with gzip.open(old, "wt") as f:
        json.dump({"format_version": FORMAT_VERSION + 1}, f)
    with pytest.raises(ExportFormatError, match="format version"):
        load_export(old)


def test_dependency_file_info(tmp_path: Path) -> None:
    dep_file = tmp_path / "dynamic_dependencies.txt"
    dep_file.write_text("abc")

    info = dependency_file_info(dep_file)

    assert info is not None and info["size"] == 3
    assert dependency_file_info(tmp_path / "missing.txt") is None


def test_export_failure_does_not_fail_the_run(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(export_module, "build_export", broken)

    with caplog.at_level(logging.WARNING, logger="Explorer"):
        assert write_export(str(tmp_path), None, None, None) is None  # type: ignore[arg-type]

    assert "Could not write the side effect export" in caplog.text
    assert not (tmp_path / "explorer" / "side_effects.json.gz").exists()


# ---------------------------------------------------------------------------
# review fixes: types, repeated locals, access of globals, unprofiled calls, skipping
# ---------------------------------------------------------------------------


def _type(qual: str, desugared: Optional[str] = None) -> Dict[str, str]:
    return {"qualType": qual, "desugaredQualType": desugared} if desugared else {"qualType": qual}


def _function_ast(name: str, mangled: str, params: List[Any], body: List[Any], extra: List[Any]) -> Dict[str, Any]:
    """A translation unit with the declarations ``extra`` and one function definition."""
    return {
        "kind": "TranslationUnitDecl",
        "id": "0x1",
        "inner": extra
        + [
            {
                "id": "0xf0",
                "kind": "FunctionDecl",
                "name": name,
                "mangledName": mangled,
                "loc": {"file": "/src/code.cpp", "line": 3},
                "inner": params + [{"id": "0xf1", "kind": "CompoundStmt", "inner": body}],
            }
        ],
    }


def _facts_of(ast: Dict[str, Any], mangled: str, pet_names: Tuple[str, ...] = ()) -> Tuple[Any, Any]:
    function = _Named("1:5", mangled, 1, 3)
    others = [_Named(f"1:{9 + i}", n, 1, 100 + i) for i, n in enumerate(pet_names)]
    facts = _AstFacts(_AstHelper(ast), {1: "/src/code.cpp"}, [function, *others])  # type: ignore[arg-type, list-item]
    return facts, facts.function_facts(function)  # type: ignore[arg-type]


def test_typedef_pointers_and_class_parameters_are_reachable() -> None:
    params = [
        {"id": f"0x{20 + i}", "kind": "ParmVarDecl", "name": n, "type": t}
        for i, (n, t) in enumerate(
            [
                ("a", _type("Real_p", "double *")),  # typedef double* Real_p
                ("r", _type("IntRef", "int &")),
                ("p", _type("P")),  # struct P passed by value: may hold pointers into the caller's memory
                ("p2", _type("struct P", "P")),
                ("s", _type("std::shared_ptr<int>")),
                ("it", _type("std::vector<int>::iterator", "__gnu_cxx::__normal_iterator<int *, std::vector<int>>")),
                ("c", _type("Color")),  # an enum
                ("m", _type("myint", "int")),  # typedef int myint
                ("z", _type("size_t", "unsigned long")),
                ("n", _type("const int")),
            ]
        )
    ]
    extra = [{"id": "0x2", "kind": "EnumDecl", "name": "Color"}]
    _facts, facts = _facts_of(_function_ast("F", "_Z1F", params, [], extra), "_Z1F")

    assert {p["name"]: p["reachable"] for p in facts.params} == {
        "a": True,
        "r": True,
        "p": True,
        "p2": True,
        "s": True,
        "it": True,
        "c": False,
        "m": False,
        "z": False,
        "n": False,
    }


def test_typedef_pointers_and_pointer_wrappers_are_pointer_locals() -> None:
    locals_ = [
        ("q", _type("Real_p", "double *")),
        ("sp", _type("std::shared_ptr<int>")),
        ("it", _type("std::vector<int>::iterator", "__gnu_cxx::__normal_iterator<int *, std::vector<int>>")),
        ("sv", _type("std::string_view", "std::basic_string_view<char>")),
        ("pt", _type("P")),  # a struct by value is local storage
        ("arr", _type("int[4]")),
        ("m", _type("myint", "int")),
    ]
    body = [
        {
            "id": "0x30",
            "kind": "DeclStmt",
            "inner": [
                {"id": f"0x{40 + i}", "kind": "VarDecl", "name": n, "type": t} for i, (n, t) in enumerate(locals_)
            ],
        }
    ]
    _facts, facts = _facts_of(_function_ast("F", "_Z1F", [], body, []), "_Z1F")

    assert {l["name"]: l["pointer"] for l in facts.locals} == {
        "q": True,
        "sp": True,
        "it": True,
        "sv": True,
        "pt": False,
        "arr": False,
        "m": False,
    }


def test_every_declaration_of_a_local_name_is_exported() -> None:
    """{ int i; } { static int i; i++; }: the profiler's names carry no scope, the reader merges."""
    body = [
        {
            "id": "0x30",
            "kind": "CompoundStmt",
            "inner": [{"id": "0x31", "kind": "VarDecl", "name": "i", "type": _type("int")}],
        },
        {
            "id": "0x32",
            "kind": "CompoundStmt",
            "inner": [
                {"id": "0x33", "kind": "VarDecl", "name": "i", "storageClass": "static", "type": _type("int")},
                {"id": "0x34", "kind": "VarDecl", "name": "i", "storageClass": "static", "type": _type("int")},
            ],
        },
    ]
    _facts, facts = _facts_of(_function_ast("F", "_Z1F", [], body, []), "_Z1F")

    entries = sorted((l["name"], l["pointer"], l["static"]) for l in facts.locals)
    assert entries == [("i", False, False), ("i", False, True)]  # one entry per distinct declaration


def _call(node_id: str, callee: str, callee_id: str, args: List[Any], line: int) -> Dict[str, Any]:
    return {
        "id": node_id,
        "kind": "CallExpr",
        "loc": {"line": line},
        "inner": [
            {
                "id": node_id + "c",
                "kind": "ImplicitCastExpr",
                "inner": [_decl_ref(node_id + "d", callee, callee_id, "FunctionDecl")],
            }
        ]
        + args,
    }


def test_global_passed_by_reference_or_as_object_of_a_member_call_has_unknown_access() -> None:
    globals_ = [
        {"id": "0x10", "kind": "VarDecl", "name": "g", "type": _type("int")},
        {"id": "0x11", "kind": "VarDecl", "name": "g_vec", "type": _type("std::vector<int>")},
        {"id": "0x12", "kind": "VarDecl", "name": "g_val", "type": _type("int")},
        {"id": "0x13", "kind": "VarDecl", "name": "g_arr", "type": _type("int[4]")},
    ]
    body = [
        _call("0x50", "inc", "0x90", [_decl_ref("0x51", "g", "0x10")], 4),  # inc(int&)
        {
            "id": "0x60",
            "kind": "CXXMemberCallExpr",
            "loc": {"line": 5},
            "inner": [
                {
                    "id": "0x61",
                    "kind": "MemberExpr",
                    "name": "push_back",
                    "inner": [_decl_ref("0x62", "g_vec", "0x11", type_name="std::vector<int>")],
                }
            ],
        },
        # by value: the lvalue-to-rvalue cast makes it a read
        _call(
            "0x70",
            "use",
            "0x91",
            [{"id": "0x71", "kind": "ImplicitCastExpr", "inner": [_decl_ref("0x72", "g_val", "0x12")]}],
            6,
        ),
        # an array passed as a pointer
        _call(
            "0x80",
            "fill",
            "0x92",
            [
                {
                    "id": "0x81",
                    "kind": "ImplicitCastExpr",
                    "inner": [_decl_ref("0x82", "g_arr", "0x13", type_name="int[4]")],
                }
            ],
            7,
        ),
    ]
    _facts, facts = _facts_of(_function_ast("F", "_Z1F", [], body, globals_), "_Z1F")

    assert {(r["name"], r["access"]) for r in facts.global_refs} == {
        ("g", "unknown"),
        ("g_vec", "unknown"),
        ("g_val", "read"),
        ("g_arr", "unknown"),
    }


def test_compound_assignment_and_increment_of_a_global_are_a_read_and_a_write() -> None:
    """next_value: ++g_seq; the profiler records only the write, the read must come from the source."""
    globals_ = [
        {"id": "0x10", "kind": "VarDecl", "name": "g_seq", "type": _type("int")},
        {"id": "0x11", "kind": "VarDecl", "name": "g_sum", "type": _type("int")},
    ]
    body = [
        {
            "id": "0x50",
            "kind": "UnaryOperator",
            "opcode": "++",
            "loc": {"line": 4},
            "inner": [_decl_ref("0x51", "g_seq", "0x10")],
        },
        {
            "id": "0x60",
            "kind": "CompoundAssignOperator",
            "opcode": "+=",
            "loc": {"line": 5},
            "inner": [_decl_ref("0x61", "g_sum", "0x11"), {"id": "0x62", "kind": "IntegerLiteral"}],
        },
    ]
    _facts, facts = _facts_of(_function_ast("F", "_Z1F", [], body, globals_), "_Z1F")

    assert sorted((r["name"], r["access"]) for r in facts.global_refs) == [
        ("g_seq", "read"),
        ("g_seq", "write"),
        ("g_sum", "read"),
        ("g_sum", "write"),
    ]


def test_a_project_method_does_not_hide_a_library_function_of_the_same_name() -> None:
    """Project Logger::write must not make POSIX write look profiled."""
    extra = [
        {"id": "0x2", "kind": "FunctionDecl", "name": "write", "mangledName": "write"},  # unistd.h
        {
            "id": "0x3",
            "kind": "CXXRecordDecl",
            "name": "Logger",
            "inner": [{"id": "0x4", "kind": "CXXMethodDecl", "name": "write", "mangledName": "_ZN6Logger5writeEi"}],
        },
        {
            "id": "0x5",
            "kind": "CXXMethodDecl",
            "name": "write",
            "mangledName": "_ZN6Logger5writeEi",
            "loc": {"file": "/src/code.cpp", "line": 50},
            "inner": [{"id": "0x6", "kind": "CompoundStmt"}],
        },
    ]
    body = [
        {
            "id": "0x60",
            "kind": "CXXMemberCallExpr",
            "inner": [
                {
                    "id": "0x61",
                    "kind": "MemberExpr",
                    "name": "write",
                    "referencedMemberDecl": "0x4",
                    "inner": [_decl_ref("0x62", "l", "0x21", "ParmVarDecl", "Logger")],
                }
            ],
        },
        _call("0x70", "write", "0x2", [], 5),
        _call("0x80", "helper", "0x99", [], 6),  # declaration unknown: matched by base name
    ]
    facts_by_function, facts = _facts_of(
        _function_ast("h", "_Z1hR6Logger", [], body, extra), "_Z1hR6Logger", ("_ZN6Logger5writeEi", "_Z6helperv")
    )

    assert facts_by_function.unprofiled_calls(facts) == ["write"]


class _StatelessTaskGraph:
    ignore_dependency_states = True


def test_no_export_without_dependency_states_and_a_stale_one_is_removed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    stale = tmp_path / "explorer" / "side_effects.json.gz"
    save_export({"format_version": FORMAT_VERSION}, stale)  # type: ignore[typeddict-item]

    with caplog.at_level(logging.INFO, logger="Explorer"):
        assert write_export(str(tmp_path), _StatelessTaskGraph(), None, None) is None  # type: ignore[arg-type]

    assert not stale.exists()
    assert "--ignore-dependency-states" in caplog.text
    assert "Could not write" not in caplog.text


def test_a_failed_save_leaves_no_temporary_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(json, "dump", broken)
    path = tmp_path / "explorer" / "side_effects.json.gz"

    with pytest.raises(RuntimeError):
        save_export({"format_version": FORMAT_VERSION}, path)  # type: ignore[typeddict-item]

    assert list((tmp_path / "explorer").iterdir()) == []


def test_build_export_reads_the_explorers_file_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    read: List[str] = []

    class _Stop(Exception):
        pass

    def record(path: str) -> Dict[int, str]:
        read.append(path)
        raise _Stop()

    monkeypatch.setattr(export_module, "_read_file_mapping", record)
    fmap = str(tmp_path / "elsewhere" / "FileMapping.txt")

    with pytest.raises(_Stop):
        export_module.build_export(str(tmp_path), None, None, None, fmap)  # type: ignore[arg-type]
    with pytest.raises(_Stop):
        export_module.build_export(str(tmp_path), None, None, None)  # type: ignore[arg-type]

    assert read == [fmap, str(tmp_path / "FileMapping.txt")]

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for the outer references of a loop (find_outer_references) and the scope lookup of member functions.

The trees follow the shape of clang's JSON AST: a const method is called on an ImplicitCastExpr of type "const T", a
non-const one on the bare DeclRefExpr, and a value passed to a function is wrapped in a cast while a reference
argument is the bare lvalue.
"""

from __future__ import annotations

import itertools
from typing import Any, Optional

import networkx as nx
import pytest

from discopop_explorer.utilities.ASTUtils.ASTGraph import ClangASTGraph
from discopop_explorer.utilities.ASTUtils.ASTQueries import ASTVariableAndTypeQueries
from discopop_explorer.utilities.ASTUtils.OuterReferences import (
    OuterReference,
    find_names_declared_in_loop,
    find_outer_references,
    is_const_variable_type,
)

FILE = "t.cpp"
_ids = itertools.count(1)


def node(kind: str, *inner: dict[str, Any], line: int = 1, end: Optional[int] = None, **attrs: Any) -> dict[str, Any]:
    """A node on `line`. The first node of a tree carries the file, the others inherit it like in clang's output."""
    result: dict[str, Any] = {
        "id": f"0x{next(_ids)}",
        "kind": kind,
        "loc": {"line": line, "col": 1},
        "range": {"begin": {"line": line, "col": 1}, "end": {"line": end or line, "col": 2}},
        "inner": list(inner),
    }
    result.update(attrs)
    return result


def decl(kind: str, name: str, type_str: str, *inner: dict[str, Any], line: int = 1, **attrs: Any) -> dict[str, Any]:
    return node(kind, *inner, line=line, name=name, type={"qualType": type_str}, **attrs)


def ref(target: dict[str, Any], type_str: Optional[str] = None, line: int = 1) -> dict[str, Any]:
    """A DeclRefExpr to a declaration node."""
    return node(
        "DeclRefExpr",
        line=line,
        type={"qualType": type_str or target["type"]["qualType"]},
        referencedDecl={"id": target["id"], "kind": target["kind"], "name": target["name"]},
    )


def cast(inner: dict[str, Any], type_str: str, line: int = 1) -> dict[str, Any]:
    return node("ImplicitCastExpr", inner, line=line, type={"qualType": type_str})


def method_call(obj: dict[str, Any], method: str, *args: dict[str, Any], line: int = 1) -> dict[str, Any]:
    member = node("MemberExpr", obj, line=line, name=method, type={"qualType": "<bound member function type>"})
    return node("CXXMemberCallExpr", member, *args, line=line, type={"qualType": "void"})


def operator_call(op: str, obj: dict[str, Any], *args: dict[str, Any], line: int = 1) -> dict[str, Any]:
    callee_decl = {"id": "0xop", "kind": "CXXMethodDecl", "name": op}
    callee = cast(node("DeclRefExpr", line=line, type={"qualType": "x"}, referencedDecl=callee_decl), "fn *", line=line)
    return node("CXXOperatorCallExpr", callee, obj, *args, line=line, type={"qualType": "double &"})


def assign(lhs: dict[str, Any], rhs: dict[str, Any], line: int = 1) -> dict[str, Any]:
    return node("BinaryOperator", lhs, rhs, line=line, opcode="=", type={"qualType": "double"})


def call(callee_name: str, *args: dict[str, Any], line: int = 1) -> dict[str, Any]:
    callee_decl = {"id": "0xfn", "kind": "FunctionDecl", "name": callee_name}
    callee = cast(node("DeclRefExpr", line=line, type={"qualType": "x"}, referencedDecl=callee_decl), "fn *", line=line)
    return node("CallExpr", callee, *args, line=line, type={"qualType": "void"})


def address_of(inner: dict[str, Any], line: int = 1) -> dict[str, Any]:
    return node("UnaryOperator", inner, line=line, opcode="&", type={"qualType": "double *"})


def build(function: dict[str, Any]) -> nx.DiGraph[str]:
    function["loc"]["file"] = FILE
    tu = {"id": "0x0", "kind": "TranslationUnitDecl", "inner": [function]}
    return ClangASTGraph().build_from_ast(tu)


def loop_function(
    params: list[dict[str, Any]],
    pre: list[dict[str, Any]],
    body: list[dict[str, Any]],
    kind: str = "FunctionDecl",
    post: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """`kind` name(params) { pre; for (size_t i = 0; i < n; ++i) { body } post }, the loop on line 10 and `n` the
    parameter named "n"."""
    n = next(p for p in params if p["name"] == "n")
    i = decl("VarDecl", "i", "std::size_t", line=10)
    for_stmt = node(
        "ForStmt",
        node("DeclStmt", i, line=10),
        {},
        node("BinaryOperator", cast(ref(i), "std::size_t", 10), cast(ref(n), "std::size_t", 10), line=10, opcode="<"),
        node("UnaryOperator", ref(i), line=10, opcode="++"),
        node("CompoundStmt", *body, line=11, end=19),
        line=10,
        end=20,
    )
    return node(
        kind,
        *params,
        node("CompoundStmt", *pre, for_stmt, *(post or []), line=5, end=30),
        line=4,
        end=31,
        name="f",
        type={"qualType": "void ()"},
    )


def by_name(refs: list[OuterReference]) -> dict[str, OuterReference]:
    return {r.name: r for r in refs}


# ------------------------------------------------------------------------------------------------------------------


def test_header_only_reference_is_found_and_not_in_body() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    graph = build(loop_function([n], [], []))

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert set(refs) == {"n"}
    assert refs["n"].decl_kind == "ParmVarDecl"
    assert refs["n"].in_body is False
    assert refs["n"].maybe_written is False


def test_the_loop_own_variable_and_body_locals_are_not_outer() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    local = decl("VarDecl", "inp", "double", line=12)
    graph = build(
        loop_function([n], [], [node("DeclStmt", local, line=12), assign(ref(local, line=13), ref(n, line=13), 13)])
    )

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert set(refs) == {"n"}
    assert refs["n"].in_body is True
    assert "inp" in find_names_declared_in_loop(graph, FILE, 10)
    assert "i" in find_names_declared_in_loop(graph, FILE, 10)


def test_const_scalar_and_const_reference_are_const_but_pointer_to_const_is_not() -> None:
    assert is_const_variable_type("const double")
    assert is_const_variable_type("double *const")
    assert is_const_variable_type("const std::shared_ptr<G> &")
    assert not is_const_variable_type("const double *")
    assert not is_const_variable_type("double")
    assert not is_const_variable_type("std::vector<double> &")
    assert not is_const_variable_type(None)


def test_write_through_a_pointer_is_not_a_write_to_the_pointer() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    out = decl("ParmVarDecl", "out", "double *")
    i_ref = node(
        "DeclRefExpr",
        line=12,
        type={"qualType": "std::size_t"},
        referencedDecl={"id": "0xi", "kind": "VarDecl", "name": "i"},
    )
    store = assign(
        node("ArraySubscriptExpr", cast(ref(out, line=12), "double *", 12), i_ref, line=12),
        node("FloatingLiteral", line=12),
        12,
    )
    graph = build(loop_function([n, out], [], [store]))

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert refs["out"].maybe_written is False
    assert refs["out"].modified_via_call is False


def test_assigning_a_scalar_is_a_write() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    total = decl("VarDecl", "total", "double", line=6)
    graph = build(
        loop_function(
            [n], [node("DeclStmt", total, line=6)], [assign(ref(total, line=12), node("FloatingLiteral", line=12), 12)]
        )
    )

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert refs["total"].maybe_written is True
    assert refs["total"].modified_via_call is False


def test_non_const_method_call_is_a_write_through_a_call_and_a_const_one_is_not() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    tmp = decl("VarDecl", "tmp", "Acc", node("CXXConstructExpr", line=6, type={"qualType": "Acc"}), line=6)
    body = [
        method_call(ref(tmp, line=12), "reset", line=12),
        method_call(cast(ref(tmp, line=13), "const Acc", 13), "sum", line=13),
    ]
    graph = build(loop_function([n], [node("DeclStmt", tmp, line=6)], body))

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert refs["tmp"].modified_via_call is True
    assert refs["tmp"].modified_as_object is True
    assert refs["tmp"].call_lines == [12]
    assert refs["tmp"].default_constructed is True


def test_only_const_method_calls_leave_the_object_unwritten() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    tmp = decl("VarDecl", "tmp", "Acc", line=6)
    graph = build(
        loop_function(
            [n],
            [node("DeclStmt", tmp, line=6)],
            [method_call(cast(ref(tmp, line=12), "const Acc", 12), "sum", line=12)],
        )
    )

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert refs["tmp"].maybe_written is False


def test_element_access_of_a_container_does_not_write_the_container() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    vec = decl("ParmVarDecl", "vec", "std::vector<double> &")
    i_ref = node(
        "DeclRefExpr",
        line=12,
        type={"qualType": "std::size_t"},
        referencedDecl={"id": "0xi", "kind": "VarDecl", "name": "i"},
    )
    store = assign(
        operator_call("operator[]", ref(vec, "std::vector<double>", 12), i_ref, line=12),
        node("FloatingLiteral", line=12),
        12,
    )
    graph = build(loop_function([n, vec], [], [store]))

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert refs["vec"].maybe_written is False
    assert refs["vec"].modified_via_call is False


def test_bare_lvalue_argument_is_bound_to_a_reference_and_a_copy_is_not() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    buf = decl("VarDecl", "buf", "Buffer", line=6)
    copied = decl("VarDecl", "copied", "double", line=6)
    body = [call("fill", ref(buf, line=12), cast(ref(copied, line=12), "double", 12), line=12)]
    graph = build(loop_function([n], [node("DeclStmt", buf, copied, line=6)], body))

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert refs["buf"].modified_via_call is True
    assert refs["buf"].modified_as_object is False
    assert refs["copied"].modified_via_call is False


def test_address_passed_to_a_call_is_a_write_through_a_call() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    t = decl("VarDecl", "t", "double", line=6)
    graph = build(
        loop_function([n], [node("DeclStmt", t, line=6)], [call("set_val", address_of(ref(t, line=12), 12), line=12)])
    )

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert refs["t"].modified_via_call is True
    assert refs["t"].call_lines == [12]


def test_use_after_the_loop_and_escaping_alias_are_recorded() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    tmp = decl("VarDecl", "tmp", "Acc", line=6)
    escape = node("DeclStmt", decl("VarDecl", "alias", "Acc &", ref(tmp, line=7), line=7), line=7)
    after = method_call(cast(ref(tmp, line=25), "const Acc", 25), "sum", line=25)
    graph = build(
        loop_function(
            [n],
            [node("DeclStmt", tmp, line=6), escape],
            [method_call(cast(ref(tmp, line=12), "const Acc", 12), "sum", line=12)],
            post=[after],
        )
    )

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert refs["tmp"].used_after_loop is True
    assert refs["tmp"].address_escapes is True


def test_member_function_parameters_are_in_scope_of_the_loop() -> None:
    """The scope lookup stopped at the body of a method, so its parameters (siblings of the body) were unknown."""
    n = decl("ParmVarDecl", "n", "std::size_t")
    fired = decl("ParmVarDecl", "fired", "const int *")
    graph = build(loop_function([n, fired], [], [], kind="CXXMethodDecl"))

    names = {name for name, _ in ASTVariableAndTypeQueries.find_all_variables_in_scope(graph, FILE, 10)}

    assert {"n", "fired"} <= names


@pytest.mark.parametrize("kind", ["FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl", "CXXDestructorDecl"])
def test_outer_references_of_a_loop_in_any_function_like_declaration(kind: str) -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    graph = build(loop_function([n], [], [], kind=kind))

    assert [r.name for r in find_outer_references(graph, FILE, 10)] == ["n"]


def test_declarations_outside_the_project_are_not_variables_of_the_loop() -> None:
    """std::cout, std::numbers::pi and the like are declared in headers which are not part of the graph. Listing them
    unqualified in a clause does not compile."""
    n = decl("ParmVarDecl", "n", "std::size_t")
    cout = {"id": "0xcout", "kind": "VarDecl", "name": "cout", "type": {"qualType": "std::ostream"}}
    cout_ref = node("DeclRefExpr", line=12, type={"qualType": "std::ostream"}, referencedDecl=cout)
    graph = build(loop_function([n], [], [call("print", cout_ref, line=12)]))

    assert [r.name for r in find_outer_references(graph, FILE, 10)] == ["n"]


def test_a_global_of_the_translation_unit_is_an_outer_reference_and_a_namespace_variable_is_not() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    g_scale = decl("VarDecl", "g_scale", "double", line=2)
    in_namespace = node("NamespaceDecl", decl("VarDecl", "hidden", "double", line=3), line=3, name="ns")
    body = [
        assign(
            node(
                "DeclRefExpr",
                line=12,
                type={"qualType": "double"},
                referencedDecl={"id": "0xl", "kind": "VarDecl", "name": "l"},
            ),
            ref(g_scale, line=12),
            12,
        ),
        call("use", ref(in_namespace["inner"][0], line=13), line=13),
    ]
    function = loop_function([n], [], body)
    function["loc"]["file"] = FILE
    tu = {"id": "0x0", "kind": "TranslationUnitDecl", "inner": [g_scale, in_namespace, function]}
    g_scale["loc"]["file"] = FILE
    graph = ClangASTGraph().build_from_ast(tu)

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert refs["g_scale"].is_global is True
    assert "hidden" not in refs


def test_the_out_of_line_definition_of_a_static_member_is_not_a_global_variable() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    declaration = decl("VarDecl", "factor", "double", line=2, storageClass="static")
    record = node("CXXRecordDecl", declaration, line=2, name="Cfg")
    definition = decl("VarDecl", "factor", "double", line=3, previousDecl=declaration["id"])
    body = [call("use", ref(definition, line=12), line=12)]
    function = loop_function([n], [], body)
    function["loc"]["file"] = FILE
    record["loc"]["file"] = FILE
    tu = {"id": "0x0", "kind": "TranslationUnitDecl", "inner": [record, definition, function]}
    graph = ClangASTGraph().build_from_ast(tu)

    assert "factor" not in by_name(find_outer_references(graph, FILE, 10))


def test_typedef_is_resolved_for_the_type_of_a_reference() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    t = decl("VarDecl", "t", "real", line=6, desugaredType=None)
    t["type"]["desugaredQualType"] = "double"
    graph = build(
        loop_function([n], [node("DeclStmt", t, line=6)], [call("set_val", address_of(ref(t, line=12), 12), line=12)])
    )

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert refs["t"].type == "real" and refs["t"].desugared_type == "double"
    assert refs["t"].logical_type == "double"


def test_use_in_the_enclosing_loop_counts_as_use_after_the_loop() -> None:
    """The rest of an enclosing loop runs again after the inner loop, in its next iteration."""
    n = decl("ParmVarDecl", "n", "std::size_t")
    tmp = decl("VarDecl", "tmp", "Acc", line=6)
    inner_for = node(
        "ForStmt",
        node("DeclStmt", decl("VarDecl", "j", "std::size_t", line=10), line=10),
        {},
        node(
            "BinaryOperator",
            cast(
                node(
                    "DeclRefExpr",
                    line=10,
                    type={"qualType": "std::size_t"},
                    referencedDecl={"id": "0xj", "kind": "VarDecl", "name": "j"},
                ),
                "std::size_t",
                10,
            ),
            cast(ref(n), "std::size_t", 10),
            line=10,
            opcode="<",
        ),
        node(
            "UnaryOperator",
            node(
                "DeclRefExpr",
                line=10,
                type={"qualType": "std::size_t"},
                referencedDecl={"id": "0xj", "kind": "VarDecl", "name": "j"},
            ),
            line=10,
            opcode="++",
        ),
        node("CompoundStmt", method_call(ref(tmp, line=11), "reset", line=11), line=11, end=12),
        line=10,
        end=12,
    )
    outer_for = node(
        "ForStmt",
        {},
        {},
        {},
        {},
        node(
            "CompoundStmt",
            inner_for,
            method_call(cast(ref(tmp, line=14), "const Acc", 14), "sum", line=14),
            line=9,
            end=15,
        ),
        line=9,
        end=15,
    )
    function = node(
        "FunctionDecl",
        n,
        node("CompoundStmt", node("DeclStmt", tmp, line=6), outer_for, line=5, end=30),
        line=4,
        end=31,
        name="f",
        type={"qualType": "void ()"},
    )
    graph = build(function)

    refs = by_name(find_outer_references(graph, FILE, 10))

    assert refs["tmp"].used_after_loop is True


def test_no_loop_no_references() -> None:
    n = decl("ParmVarDecl", "n", "std::size_t")
    graph = build(loop_function([n], [], []))

    assert find_outer_references(graph, FILE, 25) == []
    assert find_names_declared_in_loop(graph, FILE, 25) == frozenset()

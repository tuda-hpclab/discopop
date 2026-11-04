# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The update statements of a source line (``x op= e``, ``x++``, ...), located by the column of their
operator. See design/doall_commutative_updates.md.

The profiler reports the load and the store of such a read-modify-write at the column of the operator,
while every other access of the statement has a column of its own. Clang's JSON gives expressions no
location of their own, only a source range, so the operator column is derived from the ranges:

- prefix ``++x`` / ``--x``: the beginning of the expression,
- postfix ``x++`` / ``x--``: the end of the expression, whose last token is the operator,
- ``x op= e``: the column strictly between the end of ``x`` and the beginning of ``e``; the operator
  is the only token there. Its exact column is not known, so a site matches every column of that gap.

A site that could not be made ``#pragma omp atomic`` as it stands carries a ``problem``; it is still
reported, so a caller can tell "an update, but not usable" from "no update at all".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx

from discopop_explorer.utilities.ASTUtils.ASTQueries import ASTQueries

# the operators of OpenMP's "atomic update" forms, by the class of operators which commute with each
# other: the updates of one location have to stay in one class
OPERATOR_CLASSES: Dict[str, str] = {
    "+=": "+",
    "-=": "+",
    "++": "+",
    "--": "+",
    "*=": "*",
    "&=": "&",
    "|=": "|",
    "^=": "^",
}

# the problems a site can have, see UpdateSite.problem
DEPENDENT_TYPE = "dependent_type"  # only in an uninstantiated template: no instantiation was found
INSTANTIATIONS_DIFFER = "instantiations_differ"
NOT_A_STATEMENT = "not_a_statement"  # not a statement of its own: y = h[k]++, a for increment, an else branch
NOT_ALONE_ON_LINE = "not_alone_on_line"  # the pragma has to precede exactly this statement
MULTI_LINE = "multi_line"
MACRO = "macro"  # the expression comes from a macro: its parts share one column
RHS_REFERENCES_LHS = "rhs_references_lhs"  # e.g. a[i+1] += a[i]

# wrappers which leave the value of an expression unchanged
_TRANSPARENT_KINDS = {"ImplicitCastExpr", "CStyleCastExpr", "ParenExpr", "ConstantExpr", "ExprWithCleanups"}
_DEPENDENT = "<dependent type>"


@dataclass(frozen=True)
class UpdateSite:
    """An update statement of one source line."""

    line: int
    # the columns the profiler may report the read-modify-write at: one column for ++ / --, the gap
    # between the operands for op=
    first_column: int
    last_column: int
    # the operator as written ("+=", "++", ...) and its class (see OPERATOR_CLASSES)
    operator: str
    operator_class: str
    # the variable the updated memory is reached through (row_coefs for row_coefs[k] += v, domain for
    # domain.fx(n) += v), None if the AST does not tell
    variable: Optional[str]
    # the column range of the whole statement, for placing a pragma
    begin_column: int
    end_column: int
    # why the site cannot be made atomic as it stands, None if it can
    problem: Optional[str] = None

    def covers(self, column: int) -> bool:
        """whether the profiler reports the read-modify-write of this site at the column"""
        return self.first_column <= column <= self.last_column


def update_sites_on_line(graph: nx.DiGraph[str], filename: str, line: int) -> List[UpdateSite]:
    """The update statements beginning on a line, one per source range (a template's instantiations
    and its uninstantiated pattern are one site), ordered by column."""
    nodes = ASTQueries.find_nodes_at_location(graph, filename, line)
    by_range: Dict[Tuple[Any, ...], List[str]] = {}
    # the statements of a template's instantiations for a class type, with an overloaded operator: the
    # same source range as the builtin operator of another instantiation, which the pragma would not fit
    overloaded: Set[Tuple[Any, ...]] = set()
    for node_id in nodes:
        attrs = graph.nodes[node_id]
        if attrs.get("kind") == "CXXOperatorCallExpr" and attrs.get("range", {}).get("begin_line") == line:
            overloaded.add(_range_key(attrs.get("range", {})))
            continue
        if attrs.get("kind") not in ("CompoundAssignOperator", "UnaryOperator"):
            continue
        if attrs.get("opcode") not in OPERATOR_CLASSES:
            continue
        range_info = attrs.get("range", {})
        if range_info.get("begin_line") != line:
            continue
        by_range.setdefault(_range_key(range_info), []).append(node_id)
    sites = []
    for key in sorted(by_range):
        site = _site(graph, nodes, by_range[key], line)
        if site is not None and key in overloaded and site.problem is None:
            site = UpdateSite(
                line=site.line,
                first_column=site.first_column,
                last_column=site.last_column,
                operator=site.operator,
                operator_class=site.operator_class,
                variable=site.variable,
                begin_column=site.begin_column,
                end_column=site.end_column,
                problem=INSTANTIATIONS_DIFFER,
            )
        if site is not None:
            sites.append(site)
    return sites


def _range_key(range_info: Dict[str, Any]) -> Tuple[Any, ...]:
    return (
        range_info.get("begin_column") or 0,
        range_info.get("end_line") or 0,
        range_info.get("end_column") or 0,
    )


def _site(graph: nx.DiGraph[str], line_nodes: List[str], node_ids: List[str], line: int) -> Optional[UpdateSite]:
    """one site from the nodes of one source range, all of them update operators"""
    # every instantiation of a template has its own copy of the statement, with concrete types; the
    # uninstantiated pattern has dependent ones and is only a fallback
    concrete = [n for n in node_ids if graph.nodes[n].get("type") != _DEPENDENT]
    candidates = concrete or node_ids
    described = [_describe(graph, n, line) for n in candidates]
    first = described[0]
    if first is None:
        return None
    problem = first.problem
    if not concrete:
        problem = problem or DEPENDENT_TYPE
    elif any(
        d is None
        or (d.operator, d.first_column, d.last_column) != (first.operator, first.first_column, first.last_column)
        for d in described
    ):
        problem = problem or INSTANTIATIONS_DIFFER
    else:
        problem = problem or next((d.problem for d in described if d is not None and d.problem is not None), None)
    if problem is None and not _alone_on_line(graph, line_nodes, candidates[0], line):
        problem = NOT_ALONE_ON_LINE
    if problem == first.problem:
        return first
    return UpdateSite(
        line=first.line,
        first_column=first.first_column,
        last_column=first.last_column,
        operator=first.operator,
        operator_class=first.operator_class,
        variable=first.variable,
        begin_column=first.begin_column,
        end_column=first.end_column,
        problem=problem,
    )


def _describe(graph: nx.DiGraph[str], node_id: str, line: int) -> Optional[UpdateSite]:
    """the site of one operator node, without the checks that need the rest of the line"""
    attrs = graph.nodes[node_id]
    opcode = str(attrs["opcode"])
    range_info = attrs.get("range", {})
    begin_column = range_info.get("begin_column")
    end_column = range_info.get("end_column")
    children = list(graph.successors(node_id))
    if begin_column is None or end_column is None or not children:
        return None
    lhs = children[0]
    lhs_range = graph.nodes[lhs].get("range", {})
    problem: Optional[str] = None
    if range_info.get("end_line") != line:
        problem = MULTI_LINE
    if attrs["kind"] == "UnaryOperator":
        if _is_postfix(graph, node_id, begin_column, lhs_range):
            first_column = last_column = end_column
            # the operand ends before the operator, unless the whole expression collapsed onto one
            # column - which is what an expression from a macro looks like
            operand_end = lhs_range.get("end_column")
            if operand_end is None or operand_end >= end_column:
                problem = problem or MACRO
        else:
            first_column = last_column = begin_column
            operand_begin = lhs_range.get("begin_column")
            if operand_begin is None or operand_begin <= begin_column:
                problem = problem or MACRO
    else:
        if len(children) < 2:
            return None
        lhs_end = lhs_range.get("end_column")
        rhs_begin = graph.nodes[children[1]].get("range", {}).get("begin_column")
        if lhs_end is None or rhs_begin is None or rhs_begin - lhs_end < 2:
            problem = problem or MACRO
            first_column = last_column = begin_column
        else:
            first_column, last_column = lhs_end + 1, rhs_begin - 1
    base = _base_declaration(graph, lhs)
    if problem is None and attrs["kind"] == "CompoundAssignOperator" and base is not None:
        if base[1] is not None and base[1] in _referenced_ids(graph, children[1]):
            problem = RHS_REFERENCES_LHS
    if problem is None and not _value_unused(graph, node_id):
        problem = NOT_A_STATEMENT
    return UpdateSite(
        line=line,
        first_column=first_column,
        last_column=last_column,
        operator=opcode,
        operator_class=OPERATOR_CLASSES[opcode],
        variable=base[0] if base is not None else None,
        begin_column=begin_column,
        end_column=end_column,
        problem=problem,
    )


def _is_postfix(graph: nx.DiGraph[str], node_id: str, begin_column: int, operand_range: Dict[str, Any]) -> bool:
    flag = graph.nodes[node_id].get("is_postfix")
    if flag is not None:
        return bool(flag)
    # graphs built before is_postfix was recorded: a postfix operator begins with its operand
    return bool(operand_range.get("begin_column") == begin_column)


def _value_unused(graph: nx.DiGraph[str], node_id: str) -> bool:
    """whether the operator is a statement of a compound statement of its own, i.e. its value is not
    used - an update the pragma can precede"""
    current = node_id
    while True:
        parents = list(graph.predecessors(current))
        if len(parents) != 1:
            return False
        parent_kind = graph.nodes[parents[0]].get("kind")
        if _statement_position(graph, parents[0], current):
            return True
        if parent_kind != "ExprWithCleanups":
            return False
        current = parents[0]


# kinds whose body is their last child (clang's JSON keeps a {} placeholder for a missing for-init, ...)
_BODY_LAST = ("ForStmt", "WhileStmt", "CXXForRangeStmt")


def _statement_position(graph: nx.DiGraph[str], parent: str, child: str) -> bool:
    """whether ``child`` is a statement of its own in ``parent``: a statement of a block, or the
    brace-less body of a loop or the then branch of an if. Not an else branch: whether ``else`` is on
    the line of the statement is not in the AST, and the pragma has to begin a line."""
    kind = graph.nodes[parent].get("kind")
    if kind == "CompoundStmt":
        return True
    inner = graph.nodes[parent].get("inner") or []
    ids = [entry.get("id") if isinstance(entry, dict) else None for entry in inner]
    if not ids:
        return False
    if kind in _BODY_LAST:
        return ids[-1] == child
    if kind == "DoStmt":
        return ids[0] == child
    if kind == "IfStmt":
        then_index = len(ids) - 2 if graph.nodes[parent].get("has_else") else len(ids) - 1
        return then_index >= 0 and ids[then_index] == child
    return False


def _alone_on_line(graph: nx.DiGraph[str], line_nodes: List[str], node_id: str, line: int) -> bool:
    """whether the statement is the only one on its line, and begins it: nothing outside of it touches
    the line except the statement around it (a block, a loop), which has to begin on an earlier line"""
    statement = node_id
    while True:
        parent = next(iter(graph.predecessors(statement)))
        if _statement_position(graph, parent, statement):
            break
        statement = parent
    if graph.nodes[parent].get("range", {}).get("begin_line") == line:
        return False
    own_range = _range_key(graph.nodes[statement].get("range", {}))
    for sibling in graph.successors(parent):
        if sibling == statement:
            continue
        sibling_range = graph.nodes[sibling].get("range", {})
        begin_line = sibling_range.get("begin_line")
        end_line = sibling_range.get("end_line")
        if begin_line is None or end_line is None or not begin_line <= line <= end_line:
            continue
        # another instantiation's copy of this very statement is not another statement
        if begin_line == line and _range_key(sibling_range) == own_range:
            continue
        return False
    return True


def _base_declaration(graph: nx.DiGraph[str], node_id: str) -> Optional[Tuple[Optional[str], Optional[str]]]:
    """(name, id) of the variable an lvalue reaches its memory through: row_coefs for row_coefs[k],
    vec_coefs for vec_coefs[k] (std::vector), domain for domain.fx(n), p for *p; None if not found"""
    current = node_id
    seen: Set[str] = set()
    while current not in seen:
        seen.add(current)
        attrs = graph.nodes[current]
        kind = attrs.get("kind")
        children = list(graph.successors(current))
        if kind == "DeclRefExpr":
            return attrs.get("referenced_name"), attrs.get("referenced_id")
        if kind == "CXXThisExpr":
            return "this", None
        if not children:
            return None
        if kind == "CXXOperatorCallExpr":
            # the callee (operator[], operator()) comes first, then the object
            if len(children) < 2:
                return None
            current = children[1]
        elif kind in _TRANSPARENT_KINDS or kind in (
            "ArraySubscriptExpr",
            "MemberExpr",
            "CXXMemberCallExpr",
            "UnaryOperator",
            "MaterializeTemporaryExpr",
        ):
            current = children[0]
        else:
            return None
    return None


def _referenced_ids(graph: nx.DiGraph[str], node_id: str) -> Set[str]:
    """the ids of the declarations referenced in a subtree"""
    ids: Set[str] = set()
    stack = [node_id]
    while stack:
        current = stack.pop()
        referenced = graph.nodes[current].get("referenced_id")
        if graph.nodes[current].get("kind") == "DeclRefExpr" and referenced is not None:
            ids.add(str(referenced))
        stack.extend(graph.successors(current))
    return ids


# the callee expressions of a CallExpr which name the function called, i.e. a direct call
_DIRECT_CALLEE_KINDS = {"FunctionDecl", "CXXMethodDecl", "CXXConstructorDecl", "CXXDestructorDecl", "CXXConversionDecl"}


def is_indirect_call(graph: nx.DiGraph[str], node_id: str) -> bool:
    """whether a call expression calls a function the profiler cannot attribute statically: through a
    function pointer (or a member holding one), or a virtual method. The PET has no edge to the function
    called then, so its accesses are invisible to an analysis of the loop's callees."""
    attrs = graph.nodes[node_id]
    kind = attrs.get("kind")
    children = list(graph.successors(node_id))
    if not children:
        return False
    if kind == "CXXMemberCallExpr":
        member = children[0]
        while graph.nodes[member].get("kind") in _TRANSPARENT_KINDS:
            following = list(graph.successors(member))
            if not following:
                return False
            member = following[0]
        if graph.nodes[member].get("kind") != "MemberExpr":
            return True  # e.g. (obj.*method)(), a call through a member pointer
        declaration = graph.nodes[member].get("referenced_member_id")
        if declaration is None or declaration not in graph:
            return False  # e.g. a method of a library class whose declaration is not in the dump
        return bool(graph.nodes[declaration].get("virtual"))
    if kind != "CallExpr":
        return False
    callee = children[0]
    while graph.nodes[callee].get("kind") in _TRANSPARENT_KINDS:
        following = list(graph.successors(callee))
        if not following:
            return True
        callee = following[0]
    callee_attrs = graph.nodes[callee]
    if callee_attrs.get("kind") == "DeclRefExpr":
        return callee_attrs.get("referenced_kind") not in _DIRECT_CALLEE_KINDS
    # UnresolvedLookupExpr etc. only occur in uninstantiated templates, whose instantiations are checked
    if callee_attrs.get("kind") in ("UnresolvedLookupExpr", "UnresolvedMemberExpr", "CXXDependentScopeMemberExpr"):
        return False
    return True


@dataclass
class FileFacts:
    """What the static checks of commutative_updates need to know of a file: the references to variables
    by name ((line, column) each), and the positions of the indirect calls, both sorted by position."""

    references: Dict[str, List[Tuple[int, int]]]
    indirect_calls: List[Tuple[int, int]]


def file_facts(graph: nx.DiGraph[str]) -> Dict[str, FileFacts]:
    """FileFacts of every file of the AST, keyed by the file path stored in the nodes"""
    facts: Dict[str, FileFacts] = {}
    for node_id, attrs in graph.nodes(data=True):
        kind = attrs.get("kind")
        if kind not in ("DeclRefExpr", "CallExpr", "CXXMemberCallExpr"):
            continue
        file_name = (attrs.get("loc") or {}).get("file")
        range_info = attrs.get("range") or {}
        line = range_info.get("begin_line")
        column = range_info.get("begin_column")
        if file_name is None or line is None or column is None:
            continue
        entry = facts.setdefault(str(file_name), FileFacts(references={}, indirect_calls=[]))
        if kind == "DeclRefExpr":
            name = attrs.get("referenced_name")
            if name:
                entry.references.setdefault(str(name), []).append((line, column))
        elif is_indirect_call(graph, node_id):
            entry.indirect_calls.append((line, column))
    for entry in facts.values():
        for positions in entry.references.values():
            positions.sort()
        entry.indirect_calls.sort()
    return facts

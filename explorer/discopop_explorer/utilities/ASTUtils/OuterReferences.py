# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The variables a loop refers to which are declared outside of it, and how the loop uses them.

The profiler names an access after the IR value it goes through, so a variable which is only reached through
calls (``tmp.reset()``, ``span[i]``, ``p->get()``) or which is only read by the loop header (``i < n``) leaves no
dependence under its own name. The syntax tree has no such blind spot, so this query is the reference for "which
variables does the loop use", and for "can the loop write them".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import networkx as nx

from discopop_explorer.utilities.ASTUtils.ASTQueries import ASTQueries

_VARIABLE_KINDS = {"VarDecl", "ParmVarDecl"}
# kinds that declare a function-like scope, i.e. a variable declared below one of them is a local variable
_FUNCTION_KINDS = {
    "FunctionDecl",
    "CXXMethodDecl",
    "CXXConstructorDecl",
    "CXXDestructorDecl",
    "CXXConversionDecl",
    "LambdaExpr",
}
_CALL_KINDS = {"CallExpr", "CXXMemberCallExpr", "CXXOperatorCallExpr"}
# wrappers which do not change which storage an expression denotes
_TRANSPARENT = {"ParenExpr", "ConstantExpr", "ImplicitCastExpr", "CStyleCastExpr", "CXXFunctionalCastExpr"}
_ASSIGNING_KINDS = {"BinaryOperator", "CompoundAssignOperator", "UnaryOperator"}
_ASSIGNING_OPCODES = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", "++", "--"}
_LOOP_KINDS = {"ForStmt", "WhileStmt", "DoStmt", "CXXForRangeStmt"}


@dataclass
class OuterReference:
    """A variable declared outside of a loop and referred to inside of it."""

    name: str
    decl_id: str
    decl_kind: str
    # the type as written, which may be a typedef or alias (``real``); logical_type is the one to reason about
    type: Optional[str]
    desugared_type: Optional[str] = None
    # the variable is const-qualified itself (the pointee of a "const T *" is not the variable)
    is_const: bool = False
    # a local variable of static storage duration: shared by definition, never to be listed as private
    is_static: bool = False
    # the loop body (not only its header) refers to the variable
    in_body: bool = False
    # the variable's own storage may be written by the loop: assigned, address taken, bound to a non-const
    # reference, or the object of a call which is not known to be const
    maybe_written: bool = False
    # ... through a call: the object of a non-const method call, or an argument bound to a mutable reference
    modified_via_call: bool = False
    # ... as the object a non-const method is called on (``tmp.reset()``), as opposed to an argument (``f(tmp)``)
    modified_as_object: bool = False
    # lines of the calls above, for messages
    call_lines: list[int] = field(default_factory=list)
    # the variable is read again after the loop, in the function which contains it
    used_after_loop: bool = False
    # outside of the loop, the variable's address is taken or it is bound to a non-const reference, so code
    # which is not part of the loop may write to it, too
    address_escapes: bool = False
    # declared without constructor arguments (``Acc tmp;``), so a private copy can be default-constructed
    default_constructed: bool = False
    # declared at the top level of the translation unit: a global which default(none) requires to be listed
    is_global: bool = False

    @property
    def logical_type(self) -> Optional[str]:
        """The type with typedefs and aliases resolved."""
        return self.desugared_type or self.type


def is_const_variable_type(type_str: Optional[str]) -> bool:
    """Whether a variable of the type cannot be modified itself.

    ``const double`` and ``double *const`` are const variables, ``const double *`` is not (only what it points to is)
    and a reference cannot be rebound, so ``const T &`` is read-only as a whole."""
    if not type_str:
        return False
    text = type_str.strip()
    # a top-level const after the last pointer: "double *const" (clang writes no space) or "T * const"
    if text.endswith(" const") or text.endswith("*const"):
        return True
    if "&" in text:
        return text.startswith("const ") and "*" not in text
    return text.startswith("const ") and "*" not in text


def _is_pointer_type(type_str: Optional[str]) -> bool:
    """A pointer variable (not a reference to one): writes *through* it do not write the variable."""
    return bool(type_str) and "*" in str(type_str) and "&" not in str(type_str)


# calls which hand out a reference to an element or the pointee: the write happens through the returned reference and
# changes the elements, not the state of the object the call is made on, which stays shared between the iterations
_ELEMENT_OPERATORS = {"operator[]", "operator*", "operator->"}
_ELEMENT_ACCESSORS = {"at", "front", "back", "data", "begin", "end", "rbegin", "rend"}


@dataclass
class _Use:
    written: bool = False
    via_call: bool = False
    call_line: Optional[int] = None
    # via a call, as the object the (non-const) method is called on, as opposed to an argument
    as_object: bool = False


class _Walker:
    def __init__(self, graph: nx.DiGraph[str]) -> None:
        self.graph = graph

    def parent(self, node_id: str) -> Optional[str]:
        return ASTQueries.get_parent(self.graph, node_id)

    def kind(self, node_id: str) -> Optional[str]:
        kind = self.graph.nodes[node_id].get("kind")
        return str(kind) if kind is not None else None

    def children(self, node_id: str) -> list[str]:
        return list(self.graph.successors(node_id))

    def subtree(self, node_id: str) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        stack = [node_id]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            result.append(current)
            stack.extend(self.graph.successors(current))
        return result

    def line_of(self, node_id: str) -> Optional[int]:
        attrs = self.graph.nodes[node_id]
        line = (attrs.get("range") or {}).get("begin_line")
        if line is None:
            line = (attrs.get("loc") or {}).get("line")
        return int(line) if line is not None else None

    def type_of(self, node_id: str) -> str:
        return str(self.graph.nodes[node_id].get("type") or "")

    def callee_name(self, call_id: str) -> Optional[str]:
        """The name of the function a call expression calls, if it is named in the tree."""
        children = self.children(call_id)
        if not children:
            return None
        for node_id in self.subtree(children[0]):
            attrs = self.graph.nodes[node_id]
            # a function or a method (CXXMethodDecl, e.g. a member operator[]), as opposed to a variable
            if attrs.get("kind") == "DeclRefExpr" and attrs.get("referenced_kind") not in _VARIABLE_KINDS:
                return str(attrs.get("referenced_name") or "")
            if attrs.get("kind") == "MemberExpr" and attrs.get("name"):
                return str(attrs["name"])
        return None

    # ------------------------------------------------------------------------------------------------------------

    def classify_use(self, ref_id: str, var_type: Optional[str], is_const_var: bool) -> _Use:
        """How the expression a reference belongs to uses the variable's own storage.

        Climbs from the reference through casts and element / member selections. A write through a pointer variable
        (``p[i] = x``, ``p->f = x``, ``*p = x``) writes the memory it points to and leaves the pointer alone, whereas
        for an object, an array or a reference the same expression writes the variable itself."""
        if is_const_var:
            return _Use()
        pointer = _is_pointer_type(var_type)
        is_array = bool(var_type) and "[" in str(var_type)
        indirect = False
        casts: list[str] = []
        current = ref_id
        while True:
            parent = self.parent(current)
            if parent is None:
                return _Use()
            parent_kind = self.kind(parent)
            first = self.children(parent)[:1] == [current]
            if parent_kind in _TRANSPARENT:
                if parent_kind == "ImplicitCastExpr":
                    casts.append(self.type_of(parent))
                current = parent
                continue
            if parent_kind in {"MemberExpr", "ArraySubscriptExpr"} and first:
                indirect = indirect or pointer
                current = parent
                continue
            if parent_kind == "UnaryOperator" and self.graph.nodes[parent].get("opcode") == "*":
                indirect = indirect or pointer
                current = parent
                continue
            break

        attrs = self.graph.nodes[parent]
        parent_kind = attrs.get("kind")
        first = self.children(parent)[:1] == [current]

        if parent_kind in _ASSIGNING_KINDS and attrs.get("opcode") in _ASSIGNING_OPCODES and first:
            return _Use(written=not indirect)
        if parent_kind == "UnaryOperator" and attrs.get("opcode") == "&":
            if indirect:
                return _Use()
            return self._address_use(parent)
        if indirect:
            return _Use()
        if parent_kind == "CXXMemberCallExpr" and first:
            return self._member_call_use(parent, current)
        if parent_kind == "CXXOperatorCallExpr":
            children = self.children(parent)
            if len(children) > 1 and children[1] == current:
                if self.callee_name(parent) in _ELEMENT_OPERATORS:
                    return _Use()
                return self._object_use(current, self.line_of(parent))
            return self._argument_use(current, casts, is_array, self.line_of(parent))
        if parent_kind in {"CallExpr", "CXXMemberCallExpr", "CXXConstructExpr"}:
            return self._argument_use(current, casts, is_array, self.line_of(parent))
        return _Use()

    def leaves_alias(self, ref_id: str) -> bool:
        """Whether the reference takes the address of the variable or binds a reference variable to it."""
        current = ref_id
        while True:
            parent = self.parent(current)
            if parent is None:
                return False
            kind = self.kind(parent)
            if kind in _TRANSPARENT or kind in {"MemberExpr", "ArraySubscriptExpr"}:
                current = parent
                continue
            if kind == "UnaryOperator" and self.graph.nodes[parent].get("opcode") == "&":
                return True
            if kind == "VarDecl" and "&" in self.type_of(parent):
                return True
            return False

    def _member_call_use(self, call_id: str, member_expr_id: str) -> _Use:
        """The object of ``obj.method(...)``: the node below the MemberExpr is the object expression."""
        if self.callee_name(call_id) in _ELEMENT_ACCESSORS:
            return _Use()
        children = self.children(member_expr_id)
        object_expr = children[0] if children else member_expr_id
        return self._object_use(object_expr, self.line_of(call_id))

    def _object_use(self, object_expr_id: str, call_line: Optional[int]) -> _Use:
        # the object expression of a call of a const method is a const-qualified cast of the variable; a bare
        # lvalue means the method may modify the object
        if self.type_of(object_expr_id).startswith("const "):
            return _Use()
        return _Use(written=True, via_call=True, call_line=call_line, as_object=True)

    def _address_use(self, address_of_id: str) -> _Use:
        """``&x``: whoever receives the address may write. Passed to a call it is a write through a call."""
        current = address_of_id
        while True:
            parent = self.parent(current)
            if parent is None:
                return _Use(written=True)
            if self.kind(parent) in _TRANSPARENT:
                current = parent
                continue
            if self.kind(parent) in _CALL_KINDS | {"CXXConstructExpr"}:
                if self.type_of(current).startswith("const "):
                    return _Use()
                return _Use(written=True, via_call=True, call_line=self.line_of(parent))
            return _Use(written=True)

    def _argument_use(self, operand_id: str, casts: list[str], is_array: bool, call_line: Optional[int]) -> _Use:
        # a copied value is read through an implicit cast; a bare lvalue is bound to a reference. A cast which adds
        # const binds to a const reference. An array decays to a pointer, and the callee may write its elements.
        if is_array and any("*" in c and "const" not in c for c in casts):
            return _Use(written=True, via_call=True, call_line=call_line)
        if casts:
            return _Use()
        if self.type_of(operand_id).startswith("const "):
            return _Use()
        return _Use(written=True, via_call=True, call_line=call_line)


def _enclosing_function(walker: _Walker, node_id: str) -> Optional[str]:
    current: Optional[str] = node_id
    seen: set[str] = set()
    while current is not None and current not in seen:
        seen.add(current)
        if walker.kind(current) in _FUNCTION_KINDS:
            return current
        current = walker.parent(current)
    return None


def _is_default_constructed(walker: _Walker, decl_id: str, decl_kind: str) -> bool:
    """Whether a local variable is declared by value without constructor arguments (``Acc tmp;``), which proves that
    its type has a default constructor, so that a private copy of it can be made."""
    if decl_kind != "VarDecl" or decl_id not in walker.graph:
        return False
    for child in walker.children(decl_id):
        if walker.kind(child) == "CXXConstructExpr":
            return len(walker.children(child)) == 0
    return False


def _declaration_scope(walker: _Walker, decl_id: str, decl_kind: str) -> str:
    """Where a variable is declared: "local" (a parameter or a variable of a function), "global" (at the top level of
    the translation unit) or "other" (in a namespace or class, or not in the graph at all: a declaration of a header
    which is not part of the project, such as ``std::cout`` or ``std::numbers::pi``). Only the first two are
    variables a clause can name."""
    if decl_kind == "ParmVarDecl":
        return "local"
    if decl_id not in walker.graph:
        return "other"
    if _enclosing_function(walker, decl_id) is not None:
        return "local"
    parent = walker.parent(decl_id)
    if parent is not None and walker.kind(parent) == "TranslationUnitDecl":
        # the out-of-line definition of a static data member (``double Cfg::factor = 3.0;``) is at the top level, too,
        # but the member is not a variable a clause names, and default(none) does not ask for it
        previous = walker.graph.nodes[decl_id].get("previous_decl_id")
        if previous in walker.graph:
            previous_parent = walker.parent(str(previous))
            if previous_parent is not None and walker.kind(previous_parent) in {"CXXRecordDecl", "ClassTemplateDecl"}:
                return "other"
        return "global"
    return "other"


def find_outer_references(graph: nx.DiGraph[str], filename: str, line: int) -> list[OuterReference]:
    """The variables the loop starting on *line* refers to which are declared outside of it.

    Only parameters and local variables are returned: globals and static members are shared by definition and
    cannot appear in a private clause. Members reached through ``this`` are not variables. The result is sorted by
    name, one entry per declaration."""
    loop_id = ASTQueries.find_loop_at_location(graph, filename, line)
    if loop_id is None:
        return []
    walker = _Walker(graph)
    nodes = walker.subtree(loop_id)
    node_set = set(nodes)

    # unwrap: an OpenMP directive or captured statement which contains the loop is not the loop; the subtree of the
    # loop statement itself is what is analysed
    declared_inside = {n for n in nodes if walker.kind(n) in _VARIABLE_KINDS}

    loop_children = walker.children(loop_id)
    body_id = loop_children[-1] if loop_children else None
    body_nodes = set(walker.subtree(body_id)) if body_id is not None else set()

    found: dict[str, OuterReference] = {}
    for node_id in nodes:
        attrs = graph.nodes[node_id]
        if attrs.get("kind") != "DeclRefExpr":
            continue
        decl_kind = attrs.get("referenced_kind")
        decl_id = attrs.get("referenced_id")
        name = attrs.get("referenced_name")
        if decl_kind not in _VARIABLE_KINDS or not decl_id or not name or decl_id in declared_inside:
            continue
        scope = _declaration_scope(walker, str(decl_id), str(decl_kind))
        if scope == "other":
            continue
        decl_attrs = graph.nodes[decl_id] if decl_id in graph else {}
        written_type = decl_attrs.get("type") or attrs.get("type")
        # typedefs and aliases (``using real = double``) hide what a variable is: reason about the resolved type
        var_type = decl_attrs.get("desugared_type") or written_type
        ref = found.get(str(decl_id))
        if ref is None:
            ref = OuterReference(
                name=str(name),
                decl_id=str(decl_id),
                decl_kind=str(decl_kind),
                type=written_type,
                desugared_type=decl_attrs.get("desugared_type"),
                is_global=scope == "global",
                is_const=is_const_variable_type(var_type),
                is_static=decl_attrs.get("storage_class") == "static",
                default_constructed=_is_default_constructed(walker, str(decl_id), str(decl_kind)),
            )
            found[str(decl_id)] = ref
        if node_id in body_nodes:
            ref.in_body = True
        use = walker.classify_use(node_id, var_type, ref.is_const)
        if use.written:
            ref.maybe_written = True
        if use.via_call:
            ref.modified_via_call = True
            ref.modified_as_object = ref.modified_as_object or use.as_object
            if use.call_line is not None and use.call_line not in ref.call_lines:
                ref.call_lines.append(use.call_line)

    if not found:
        return []

    # the rest of the enclosing function: later uses, and writes which are not part of the loop
    function_id = _enclosing_function(walker, loop_id)
    loop_end = (graph.nodes[loop_id].get("range") or {}).get("end_line")
    # inside another loop, the code of that loop which is not this loop runs again after it, in the next iteration
    enclosing_loop = walker.parent(loop_id)
    while enclosing_loop is not None and walker.kind(enclosing_loop) not in _LOOP_KINDS | _FUNCTION_KINDS:
        enclosing_loop = walker.parent(enclosing_loop)
    if enclosing_loop is not None and walker.kind(enclosing_loop) in _LOOP_KINDS:
        for node_id in walker.subtree(enclosing_loop):
            if node_id in node_set:
                continue
            if graph.nodes[node_id].get("kind") == "DeclRefExpr":
                again = found.get(str(graph.nodes[node_id].get("referenced_id")))
                if again is not None:
                    again.used_after_loop = True
    if function_id is not None:
        for node_id in walker.subtree(function_id):
            if node_id in node_set:
                continue
            attrs = graph.nodes[node_id]
            if attrs.get("kind") != "DeclRefExpr":
                continue
            ref = found.get(str(attrs.get("referenced_id")))
            if ref is None:
                continue
            node_line = walker.line_of(node_id)
            if loop_end is not None and node_line is not None and node_line > int(loop_end):
                ref.used_after_loop = True
            # a call before or after the loop does not race with it; only an alias which outlives the statement does:
            # the address taken (&x) or the variable bound to a reference variable (T &r = x)
            if not ref.is_const and walker.leaves_alias(node_id):
                ref.address_escapes = True
    return sorted(found.values(), key=lambda r: (r.name, r.decl_id))


def find_names_declared_in_loop(graph: nx.DiGraph[str], filename: str, line: int) -> frozenset[str]:
    """The names of the variables the loop declares itself: its own index, the variables of its body and the names
    bound by its header (``for (auto &[key, value] : map)``). They cannot appear in a clause of the loop."""
    loop_id = ASTQueries.find_loop_at_location(graph, filename, line)
    if loop_id is None:
        return frozenset()
    walker = _Walker(graph)
    names: set[str] = set()
    for node_id in walker.subtree(loop_id):
        attrs = graph.nodes[node_id]
        if attrs.get("kind") in _VARIABLE_KINDS | {"BindingDecl"} and attrs.get("name"):
            names.add(str(attrs["name"]))
    return frozenset(names)

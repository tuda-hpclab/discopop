# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Per-function side effects computed on request from a loaded export.

Semantics: DESIGN_get_side_effects.md, section 1. Build one ``SideEffectIndex`` per
loaded export (cheap, linear in its size); ``compute`` caches its results.

Decisions where the design leaves room (kept here so that the code and its reasons stay together):

- Several names for the other end (``instruction_names`` lists more than one): every name is
  classified and the most significant class wins (global > parameter > other > local, ties by
  name), so that an access is never dropped as local while another name says it is not.
- An other end without an entry in ``instruction_names`` is not classified: it yields no effect
  when it is the inside end and contributes no ``outside_names`` when it is the outside end.
- ``via`` is the chain of instance functions from the queried instance (exclusive) down to the
  accessing one; it is empty whenever the accessing function is the queried function itself,
  also for a nested (recursive) instance of it.
- Several local declarations with the same name (different scopes): pointer beats static beats
  plain, i.e. the classification that does not drop the access wins.
- Observed effects are only reported for the coverage states ``executed`` and ``partial``; for
  ``untracked`` and ``not_executed`` the mapping of records to the function's contexts is not
  backed by an executed call (state ids are inherited), so only static facts are reported.
- ``partial`` (second rule of section 1.3) is decided per instance by the executed edges whose
  caller is the instance's function: an edge whose call instruction has no child instance there,
  or names no call instruction, makes the result partial. Without per-context execution data
  this over-approximates (an edge executed only in another calling context also counts).
- ``ast_facts`` covers the queried function, its static call closure, and every function whose
  accesses were classified for one of its instances.
- ``pure_on_observed_inputs``: besides the conditions of section 1.3, a static ``write`` entry
  and a read through a callee's parameter (it may be a global the queried function passes on)
  make the result unknown; only reads through the queried function's own parameters and reads
  of const globals keep it pure.
- An end recorded under a linker name (``linker_names``: function-static locals, static data
  members) is always a global, also when a local of the same name is declared in another scope.
- An end of a callee parameter or of other memory inside the instance whose other end is unknown
  (a first write ``INIT``, or an other end without an exported context) cannot be checked for
  crossing the call. It yields no effect, but counts towards ``unmapped_records``, like the
  record ends the export could not attribute to any context in the function or a function it
  reaches. ``unmapped_records > 0`` turns ``executed`` into ``partial``.
- The static fallback adds a referenced global per (name, access): an observed read does not hide
  a static write. A static ``unknown`` access is only hidden by an observed read and write.
- Allowlist matching of ``unprofiled_calls``: the argument list and trailing template arguments
  are removed, a leading ``::`` and the standard library namespaces (``std::``, ``std::__1::``,
  ``std::__cxx11::``, ``__gnu_cxx::``) are stripped, and the result or ``std::<result>`` must be
  in ``PURE_LIBRARY_FUNCTIONS``. Names in other namespaces are never considered pure.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, NamedTuple, Optional, Set, Tuple

from discopop_explorer.side_effects.result import (
    Access,
    Coverage,
    Effect,
    EffectSite,
    FunctionInfo,
    Kind,
    SideEffects,
    Source,
)
from discopop_explorer.side_effects.schema import Function, Record, SideEffectExport

# Called functions without a definition in the project that do not touch memory reachable
# by the caller (beyond their return value), so they do not make a result unknown.
PURE_LIBRARY_FUNCTIONS = frozenset(
    {
        "sqrt", "sqrtf", "cbrt", "pow", "powf", "exp", "expf", "log", "logf", "log2", "log10",
        "sin", "sinf", "cos", "cosf", "tan", "atan", "atan2", "fabs", "fabsf", "abs", "labs",
        "floor", "ceil", "round", "fmin", "fmax", "fmod", "std::sqrt", "std::pow", "std::exp",
        "std::log", "std::abs", "std::fabs", "std::min", "std::max", "std::floor", "std::ceil",
    }
)  # fmt: skip

_GEP_PREFIX = "GEPRESULT_"
_STD_PREFIXES = ("std::__1::", "std::__cxx11::", "std::", "__gnu_cxx::")

# name classes of section 1.1; "param" is reported as kind "parameter", "local" is dropped
_GLOBAL = "global"
_PARAM = "param"
_OTHER = "other"
_LOCAL = "local"
_CLASS_PRIORITY = {_GLOBAL: 0, _PARAM: 1, _OTHER: 2, _LOCAL: 3}


class _Classified(NamedTuple):
    cls: str
    # name without the GEPRESULT_ prefix; the member name for a member access
    name: str
    through_pointer: bool
    member_of: Optional[str]


class _FunctionFacts:
    __slots__ = ("ast_facts", "params", "locals", "member_accesses")

    def __init__(self, function: Function) -> None:
        self.ast_facts = bool(function.get("ast_facts", False))
        self.params: Dict[str, bool] = {}
        for param in function.get("params", []):
            self.params[param["name"]] = self.params.get(param["name"], False) or bool(param["reachable"])
        # name -> (pointer, static), merged over declarations of the same name: pointer > static > plain
        self.locals: Dict[str, Tuple[bool, bool]] = {}
        for local in function.get("locals", []):
            pointer, static = self.locals.get(local["name"], (False, False))
            self.locals[local["name"]] = (pointer or bool(local["pointer"]), static or bool(local["static"]))
        self.member_accesses: Dict[int, Dict[str, str]] = {}
        for line, members in function.get("member_accesses", {}).items():
            try:
                self.member_accesses[int(line)] = dict(members)
            except ValueError:
                continue


@dataclass
class _EffectAcc:
    through_pointer: bool = False
    sites: Set[EffectSite] = field(default_factory=set)
    outside_names: Set[str] = field(default_factory=set)


# (name, kind, access, source, member_of)
_EffectKey = Tuple[str, Kind, Access, Source, Optional[str]]


def _parse_line_id(line_id: str) -> Optional[Tuple[int, int]]:
    file_id, sep, line = str(line_id).partition(":")
    if not sep:
        return None
    try:
        return int(file_id), int(line)
    except ValueError:
        return None


def _split_top_level(text: str, separator: str) -> List[str]:
    """Split at ``separator`` outside of (), <> and []."""
    parts: List[str] = []
    depth = 0
    start = 0
    i = 0
    while i < len(text):
        c = text[i]
        if c in "(<[":
            depth += 1
        elif c in ")>]":
            depth = max(0, depth - 1)
        elif depth == 0 and text.startswith(separator, i):
            parts.append(text[start:i])
            i += len(separator)
            start = i
            continue
        i += 1
    parts.append(text[start:])
    return parts


def _split_signature(name: str) -> Tuple[str, Optional[str]]:
    """``"ns::f(int, char*) const"`` -> ``("ns::f", "int,char*")``; ``("ns::f", None)`` without a parameter list."""
    name = name.strip()
    close = name.rfind(")")
    if close < 0:
        return name, None
    depth = 0
    for i in range(close, -1, -1):
        if name[i] == ")":
            depth += 1
        elif name[i] == "(":
            depth -= 1
            if depth == 0:
                base = name[:i].strip()
                if not base:
                    return name, None
                return base, "".join(name[i + 1 : close].split())
    return name, None


def _strip_template_args(component: str) -> str:
    if component.endswith(">") and "<" in component and not component.startswith("operator"):
        return component[: component.find("<")]
    return component


def _library_base_name(name: str) -> str:
    base, _ = _split_signature(name)
    base = _strip_template_args(base.strip())
    if base.startswith("::"):
        base = base[2:]
    for prefix in _STD_PREFIXES:
        if base.startswith(prefix):
            return base[len(prefix) :]
    return base


def _is_pure_library_function(name: str) -> bool:
    if name in PURE_LIBRARY_FUNCTIONS:
        return True
    base, _ = _split_signature(name)
    base = _strip_template_args(base.strip()).lstrip(":")
    if not any(base.startswith(prefix) for prefix in _STD_PREFIXES) and "::" in base:
        return False
    short = _library_base_name(name)
    return short in PURE_LIBRARY_FUNCTIONS or ("std::" + short) in PURE_LIBRARY_FUNCTIONS


def _real_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(path))


class SideEffectIndex:
    def __init__(self, export: SideEffectExport) -> None:
        self.export = export
        self._cache: Dict[str, SideEffects] = {}
        self._class_cache: Dict[Tuple[str, int, str], _Classified] = {}
        self._via_cache: Dict[Tuple[int, int], Tuple[str, ...]] = {}

        self._files: Dict[int, str] = {}
        for file_id, path in export.get("files", {}).items():
            try:
                self._files[int(file_id)] = path
            except ValueError:
                continue

        self._functions: Dict[str, Function] = {f["id"]: f for f in export.get("functions", [])}
        self._facts: Dict[str, _FunctionFacts] = {fid: _FunctionFacts(f) for fid, f in self._functions.items()}
        self._linker_names: Dict[str, str] = dict(export.get("linker_names", {}))
        self._globals: Dict[str, bool] = {}
        for g in export.get("globals", []):
            # a name declared const and non-const (different scopes) counts as mutable
            self._globals[g["name"]] = self._globals.get(g["name"], True) and bool(g["const"])

        self._instance_function: Dict[int, str] = {}
        self._instance_parent: Dict[int, Optional[int]] = {}
        self._instance_call: Dict[int, Optional[int]] = {}
        for inst in export.get("instances", []):
            self._instance_function[inst["id"]] = inst["function"]
            self._instance_parent[inst["id"]] = inst["parent"]
            self._instance_call[inst["id"]] = inst["call_instruction_id"]
        self._build_instance_tree()

        self._ctx_instance: Dict[int, int] = {}
        for ctx_key, inst_id in export.get("work_contexts", {}).items():
            try:
                ctx_id = int(ctx_key)
            except ValueError:
                continue
            if inst_id in self._instance_function:
                self._ctx_instance[ctx_id] = inst_id

        self._records: List[Record] = list(export.get("records", []))
        self._records_by_instance: Dict[int, List[int]] = {}
        for index, record in enumerate(self._records):
            instances: Set[int] = set()
            for ctx in self._first_contexts(record) | self._other_contexts(record):
                owner = self._ctx_instance.get(ctx)
                if owner is not None:
                    instances.add(owner)
            for owner in instances:
                self._records_by_instance.setdefault(owner, []).append(index)

        self._instruction_names: Dict[int, List[str]] = {}
        for instr, names in export.get("instruction_names", {}).items():
            try:
                self._instruction_names[int(instr)] = sorted(set(names))
            except ValueError:
                continue

        self._edges_into: Dict[str, List[Optional[int]]] = {}
        self._edges_from: Dict[str, List[Optional[int]]] = {}
        for call in export.get("executed_calls", []):
            self._edges_into.setdefault(call["callee"], []).append(call["call_instruction_id"])
            if call["caller"] is not None:
                self._edges_from.setdefault(call["caller"], []).append(call["call_instruction_id"])

    # ------------------------------------------------------------------ instance tree

    def _build_instance_tree(self) -> None:
        """Pre-order numbers and subtree ends over the instance tree (iterative, cycle-safe), and the
        outermost instances per function."""
        self._children: Dict[int, List[int]] = {}
        roots: List[int] = []
        for inst_id in sorted(self._instance_function):
            parent = self._instance_parent[inst_id]
            if parent is None or parent not in self._instance_function or parent == inst_id:
                roots.append(inst_id)
            else:
                self._children.setdefault(parent, []).append(inst_id)
        self._pre: Dict[int, int] = {}
        self._last: Dict[int, int] = {}
        self._order: List[int] = []
        self._outermost: Dict[str, List[int]] = {}
        self._instances_of: Dict[str, List[int]] = {}
        for inst_id in sorted(self._instance_function):
            self._instances_of.setdefault(self._instance_function[inst_id], []).append(inst_id)

        active: Dict[str, int] = {}
        visited: Set[int] = set()

        def enter(node: int) -> None:
            visited.add(node)
            self._pre[node] = len(self._order)
            self._order.append(node)
            function = self._instance_function[node]
            if active.get(function, 0) == 0:
                self._outermost.setdefault(function, []).append(node)
            active[function] = active.get(function, 0) + 1

        # parent cycles have no root; they are entered at their smallest id after the rooted trees
        for start in roots + sorted(self._instance_function):
            if start in visited:
                continue
            enter(start)
            stack: List[Tuple[int, int]] = [(start, 0)]
            while stack:
                node, child_index = stack[-1]
                children = self._children.get(node, [])
                while child_index < len(children) and children[child_index] in visited:
                    child_index += 1
                if child_index < len(children):
                    stack[-1] = (node, child_index + 1)
                    child = children[child_index]
                    enter(child)
                    stack.append((child, 0))
                else:
                    stack.pop()
                    self._last[node] = len(self._order) - 1
                    function = self._instance_function[node]
                    active[function] -= 1

    def _in_subtree(self, inst_id: int, root: int) -> bool:
        return self._pre[root] <= self._pre[inst_id] <= self._last[root]

    def _subtree(self, root: int) -> List[int]:
        return self._order[self._pre[root] : self._last[root] + 1]

    def _tree_parent(self, inst_id: int) -> Optional[int]:
        parent = self._instance_parent.get(inst_id)
        if parent is None or parent not in self._pre:
            return None
        return parent

    def _via(self, root: int, inst_id: int, function_id: str) -> Tuple[str, ...]:
        if self._instance_function[inst_id] == function_id:
            return ()
        key = (root, inst_id)
        cached = self._via_cache.get(key)
        if cached is not None:
            return cached
        chain: List[str] = []
        current: Optional[int] = inst_id
        steps = 0
        while current is not None and current != root and steps <= len(self._order):
            chain.append(self._display_name(self._instance_function[current]))
            current = self._tree_parent(current)
            steps += 1
        via = tuple(reversed(chain))
        self._via_cache[key] = via
        return via

    # ------------------------------------------------------------------ helpers

    def _display_name(self, function_id: str) -> str:
        function = self._functions.get(function_id)
        if function is None:
            return function_id
        return function.get("display_name") or function.get("name") or function_id

    def _info(self, function: Function) -> FunctionInfo:
        return FunctionInfo(
            id=function["id"],
            name=function["name"],
            display_name=function.get("display_name") or function["name"],
            file=self._files.get(function["file_id"]),
            file_id=function["file_id"],
            start_line=function["start_line"],
            end_line=function["end_line"],
        )

    @staticmethod
    def _first_contexts(record: Record) -> Set[int]:
        """Work contexts of the first end, on its own: the per-access rules must not depend on the
        other end being mapped (it may lie beyond the inlining depth)."""
        contexts = {pair[0] for pair in record.get("pairs", [])}
        contexts.update(record.get("first_contexts", []) or [])
        return contexts

    @staticmethod
    def _other_contexts(record: Record) -> Set[int]:
        if record.get("other") is None:
            return set()
        contexts = {pair[1] for pair in record.get("pairs", [])}
        contexts.update(record.get("other_contexts", []) or [])
        return contexts

    def _classify(self, function_id: str, line: int, raw_name: str) -> _Classified:
        key = (function_id, line, raw_name)
        cached = self._class_cache.get(key)
        if cached is None:
            cached = self._classify_uncached(function_id, line, raw_name)
            self._class_cache[key] = cached
        return cached

    def _classify_uncached(self, function_id: str, line: int, raw_name: str) -> _Classified:
        through = raw_name.startswith(_GEP_PREFIX)
        base = raw_name[len(_GEP_PREFIX) :] if through else raw_name
        # function-static locals and static data members are recorded under their linker name: they
        # are persistent state, whatever a local of the same name in another scope says
        resolved = self._linker_names.get(base)
        if resolved is not None:
            return _Classified(_GLOBAL, resolved, through, None)
        facts = self._facts.get(function_id)
        if facts is None or not facts.ast_facts:
            return _Classified(_OTHER, base, through, None)
        # rule 0: a member access on this line
        members = facts.member_accesses.get(line)
        if members is not None and base in members:
            owner = members[base]
            if not owner:
                return _Classified(_OTHER, base, True, None)
            owner_cls, _ = self._classify_plain(facts, owner, False)
            return _Classified(owner_cls, base, True, owner)
        cls, through = self._classify_plain(facts, base, through)
        return _Classified(cls, base, through, None)

    def _classify_plain(self, facts: _FunctionFacts, base: str, through: bool) -> Tuple[str, bool]:
        """Rules 2-5 of section 1.1 -> (class, through_pointer)."""
        if base == "this":
            return _PARAM, True
        if base in facts.params:
            # *x of a scalar pointer parameter is recorded under the plain name x
            return (_PARAM, True) if facts.params[base] else (_LOCAL, through)
        if base in facts.locals:
            pointer, static = facts.locals[base]
            if pointer:
                return _OTHER, True
            if static:
                return _GLOBAL, through
            return _LOCAL, through
        if base in self._globals:
            return _GLOBAL, through
        return _OTHER, through

    def _classify_other_end(self, function_id: str, line: int, instr: int) -> Optional[_Classified]:
        names = self._instruction_names.get(instr)
        if not names:
            return None
        candidates = [self._classify(function_id, line, name) for name in names]
        return min(candidates, key=lambda c: (_CLASS_PRIORITY[c.cls], c.name))

    def _static_closure(self, function_id: str) -> List[Tuple[str, Tuple[str, ...]]]:
        """Functions statically reachable from ``function_id`` (itself first) with the shortest call
        chain (display names, exclusive of the start); breadth-first, cycle-safe, deterministic."""
        result: List[Tuple[str, Tuple[str, ...]]] = [(function_id, ())]
        seen = {function_id}
        position = 0
        while position < len(result):
            current, chain = result[position]
            position += 1
            function = self._functions.get(current)
            if function is None:
                continue
            for callee in sorted(set(function.get("static_callees", []))):
                if callee in seen or callee not in self._functions:
                    continue
                seen.add(callee)
                result.append((callee, chain + (self._display_name(callee),)))
        return result

    # ------------------------------------------------------------------ public interface

    def find_functions(
        self, name: str, file_path: Optional[str] = None, line: Optional[int] = None
    ) -> List[FunctionInfo]:
        """Functions matching ``name``: the demangled name with or without signature
        ("write_global", "write_global(int)", "ns::Cls::method"), or the PET (mangled) name.
        ``file_path`` (absolute) and ``line`` (any line inside the definition) narrow the
        candidates. Sorted by (file, start_line)."""
        query = name.strip()
        query_base, query_params = _split_signature(query)
        query_components = [c.strip() for c in _split_top_level(query_base, "::")]
        if query_components and query_components[0] == "":
            query_components = query_components[1:]
        wanted_file = _real_path(file_path) if file_path else None

        matches: List[FunctionInfo] = []
        for function in self._functions.values():
            if not self._name_matches(function, query, query_components, query_params):
                continue
            if wanted_file is not None:
                path = self._files.get(function["file_id"])
                if path is None or _real_path(path) != wanted_file:
                    continue
            if line is not None and not (function["start_line"] <= line <= function["end_line"]):
                continue
            matches.append(self._info(function))
        matches.sort(key=lambda info: (info.file or "", info.start_line, info.display_name, info.id))
        return matches

    @staticmethod
    def _name_matches(function: Function, query: str, query_components: List[str], query_params: Optional[str]) -> bool:
        display = function.get("display_name") or function["name"]
        if query in (function["name"], display):
            return True
        if not query_components:
            return False
        base, params = _split_signature(display)
        if query_params is not None and query_params != params:
            return False
        components = [c.strip() for c in _split_top_level(base, "::")]
        if len(query_components) > len(components):
            return False
        tail = components[len(components) - len(query_components) :]
        # the first component of the display name may carry a return type (templates): compare its last word
        if len(tail) == len(components) and tail:
            tail = [tail[0].split(" ")[-1]] + tail[1:]
        return all(q == c or q == _strip_template_args(c) for q, c in zip(query_components, tail))

    def compute(self, function_id: str) -> SideEffects:
        """Side effects of the function with this PET function node id; cached.
        Raises KeyError for an unknown id."""
        cached = self._cache.get(function_id)
        if cached is not None:
            return cached
        if function_id not in self._functions:
            raise KeyError(function_id)
        result = self._compute(function_id)
        self._cache[function_id] = result
        return result

    # ------------------------------------------------------------------ computation

    def _coverage(self, function_id: str) -> Coverage:
        function = self._functions[function_id]
        edges_in = self._edges_into.get(function_id, [])
        is_main = function["name"] == "main" or any(
            self._instance_parent[i] is None for i in self._instances_of.get(function_id, [])
        )
        if not (function.get("executed", False) or edges_in or is_main):
            return "not_executed"
        # main's START edge (call instruction None) matches its root instance (None); a callback edge
        # (None) never matches, since every non-root instance carries a call instruction
        instance_calls = {self._instance_call[i] for i in self._instances_of.get(function_id, [])}
        matched = [c in instance_calls for c in edges_in]
        if not any(matched) and not (is_main and not edges_in):
            return "untracked"
        if not all(matched):
            return "partial"
        for root in self._outermost.get(function_id, []):
            for inst_id in self._subtree(root):
                child_calls = {self._instance_call[c] for c in self._children.get(inst_id, [])}
                for call in self._edges_from.get(self._instance_function[inst_id], []):
                    if call is None or call not in child_calls:
                        return "partial"
        return "executed"

    def _observed_effects(
        self,
        function_id: str,
        acc: Dict[_EffectKey, _EffectAcc],
        touched: Set[str],
        unattributed: Set[Tuple[int, str, int]],
    ) -> None:
        for root in self._outermost.get(function_id, []):
            record_ids: Set[int] = set()
            for inst_id in self._subtree(root):
                record_ids.update(self._records_by_instance.get(inst_id, []))
            for record_id in sorted(record_ids):
                self._apply_record(function_id, root, record_id, acc, touched, unattributed)

    def _apply_record(
        self,
        function_id: str,
        root: int,
        record_id: int,
        acc: Dict[_EffectKey, _EffectAcc],
        touched: Set[str],
        unattributed: Set[Tuple[int, str, int]],
    ) -> None:
        """Adds the effects of one record to ``acc``. An inside end of a callee parameter or of other
        memory whose other end is unknown (a first write, or an other end without a context) cannot
        be checked for crossing the instance; it is added to ``unattributed`` as (record, end, ctx)."""
        record = self._records[record_id]
        record_type = record["type"]
        first_access: Access = "read" if record_type == "RAW" else "write"
        other_access: Access = "write" if record_type in ("RAW", "WAW") else "read"
        first_end = record["first"]
        other_end = record.get("other")
        first_pos = _parse_line_id(first_end[2])
        other_pos = _parse_line_id(other_end[2]) if other_end is not None else None

        def classify_first(inst_id: int) -> Optional[_Classified]:
            if first_pos is None:
                return None
            return self._classify(self._instance_function[inst_id], first_pos[1], record["var"])

        def classify_other(inst_id: int) -> Optional[_Classified]:
            if other_end is None or other_pos is None:
                return None
            return self._classify_other_end(self._instance_function[inst_id], other_pos[1], int(other_end[0]))

        def add(
            classified: _Classified,
            access: Access,
            pos: Tuple[int, int],
            inst_id: int,
            outside: Iterable[str] = (),
        ) -> None:
            kind: Kind = "parameter" if classified.cls == _PARAM else classified.cls  # type: ignore[assignment]
            key: _EffectKey = (classified.name, kind, access, "observed", classified.member_of)
            entry = acc.setdefault(key, _EffectAcc())
            entry.through_pointer = entry.through_pointer or classified.through_pointer
            entry.sites.add(EffectSite(pos[0], pos[1], self._via(root, inst_id, function_id)))
            # without the profiler's GEPRESULT_ prefix and linker names, like Effect.name; only names that differ
            for outside_name in outside:
                if outside_name.startswith(_GEP_PREFIX):
                    outside_name = outside_name[len(_GEP_PREFIX) :]
                outside_name = self._linker_names.get(outside_name, outside_name)
                if outside_name != classified.name:
                    entry.outside_names.add(outside_name)

        def own_rule(classified: Optional[_Classified], inst_id: int) -> bool:
            """global anywhere in sub(I); parameter of F itself in own(I)."""
            if classified is None:
                return False
            return classified.cls == _GLOBAL or (classified.cls == _PARAM and inst_id == root)

        # ends with a counterpart in an exported instance, i.e. whose crossing can be decided below
        mapped_pairs = [
            (f, o) for f, o in record.get("pairs", []) if f in self._ctx_instance and o in self._ctx_instance
        ]
        paired_first = {pair[0] for pair in mapped_pairs}
        paired_other = {pair[1] for pair in mapped_pairs}

        # global and own-parameter effects, per end, regardless of where the other end is
        for ctx in sorted(self._first_contexts(record)):
            inst_id = self._ctx_instance.get(ctx)
            if inst_id is None or not self._in_subtree(inst_id, root) or first_pos is None:
                continue
            touched.add(self._instance_function[inst_id])
            classified = classify_first(inst_id)
            if classified is None or classified.cls == _LOCAL:
                continue
            if own_rule(classified, inst_id):
                add(classified, first_access, first_pos, inst_id)
            elif ctx not in paired_first:
                unattributed.add((record_id, "first", ctx))
        for ctx in sorted(self._other_contexts(record)):
            inst_id = self._ctx_instance.get(ctx)
            if inst_id is None or not self._in_subtree(inst_id, root) or other_pos is None:
                continue
            touched.add(self._instance_function[inst_id])
            classified = classify_other(inst_id)
            if classified is None or classified.cls == _LOCAL:
                continue
            if own_rule(classified, inst_id):
                add(classified, other_access, other_pos, inst_id)
            elif ctx not in paired_other:
                unattributed.add((record_id, "other", ctx))

        # callee parameters and other memory: only where the record crosses the instance
        if other_end is None:
            return
        other_names = self._instruction_names.get(int(other_end[0]), [])
        for first_ctx, other_ctx in record.get("pairs", []):
            first_inst = self._ctx_instance.get(first_ctx)
            other_inst = self._ctx_instance.get(other_ctx)
            if first_inst is None or other_inst is None:
                continue
            first_inside = self._in_subtree(first_inst, root)
            if first_inside == self._in_subtree(other_inst, root):
                continue
            if first_inside:
                classified = classify_first(first_inst)
                inside_inst, access, pos, outside = first_inst, first_access, first_pos, list(other_names)
            else:
                classified = classify_other(other_inst)
                inside_inst, access, pos, outside = other_inst, other_access, other_pos, [record["var"]]
            if classified is None or pos is None or classified.cls == _LOCAL:
                continue
            add(classified, access, pos, inside_inst, outside)

    def _compute(self, function_id: str) -> SideEffects:
        function = self._functions[function_id]
        coverage = self._coverage(function_id)
        closure = self._static_closure(function_id)
        notes: List[str] = []

        acc: Dict[_EffectKey, _EffectAcc] = {}
        touched: Set[str] = set()
        unattributed: Set[Tuple[int, str, int]] = set()
        if coverage in ("executed", "partial"):
            self._observed_effects(function_id, acc, touched, unattributed)

        # static fallback: global accesses referenced in the static call closure but never observed;
        # an observed read does not stand for a write of the same global, nor vice versa
        observed_globals: Dict[str, Set[str]] = {}
        for observed_key in acc:
            if observed_key[1] == "global":
                observed_globals.setdefault(observed_key[0], set()).add(observed_key[2])
                if observed_key[4] is not None:
                    observed_globals.setdefault(observed_key[4], set()).add(observed_key[2])
        for callee_id, chain in closure:
            callee = self._functions[callee_id]
            for ref in callee.get("global_refs", []):
                access: Access = ref["access"] if ref["access"] in ("read", "write") else "unknown"  # type: ignore[assignment]
                observed = observed_globals.get(ref["name"], set())
                if access in observed or (access == "unknown" and {"read", "write"} <= observed):
                    continue
                key: _EffectKey = (ref["name"], "global", access, "static", None)
                entry = acc.setdefault(key, _EffectAcc())
                entry.sites.add(EffectSite(callee["file_id"], ref["line"], chain))

        effects = [
            Effect(
                name=key[0],
                kind=key[1],
                access=key[2],
                source=key[3],
                through_pointer=entry.through_pointer,
                member_of=key[4],
                sites=sorted(entry.sites, key=lambda s: (s.file_id, s.line, s.via)),
                outside_names=sorted(entry.outside_names),
            )
            for key, entry in acc.items()
        ]
        effects.sort(key=lambda e: (e.access, e.kind, e.name, e.member_of or "", e.source))

        contributing = sorted({site.via[-1] for effect in effects for site in effect.sites if site.via})

        unprofiled: Set[str] = set()
        performs_file_io = False
        for callee_id, _ in closure:
            callee = self._functions[callee_id]
            performs_file_io = performs_file_io or bool(callee.get("performs_file_io", False))
            unprofiled.update(n for n in callee.get("unprofiled_calls", []) if not _is_pure_library_function(n))
        unprofiled_calls = sorted(unprofiled)

        fact_functions = {callee_id for callee_id, _ in closure} | touched
        missing_facts = sorted(
            self._display_name(f)
            for f in fact_functions
            if f not in self._functions or not self._functions[f].get("ast_facts", False)
        )
        ast_facts = not missing_facts

        # record ends located in the function or in a function it reaches that could not be attributed
        # to a calling context: effects may be missing, so purity cannot be decided
        # plus the ends inside the function's instances whose other end is unknown, so that crossing
        # the call cannot be decided: effects may be missing, so the result is partial at best
        unmapped_by_function = self.export.get("unmapped_records", {})
        reach = fact_functions | {function_id}
        for root in self._outermost.get(function_id, []):
            reach.update(self._instance_function[inst_id] for inst_id in self._subtree(root))
        unmapped = sum(int(unmapped_by_function.get(f, 0)) for f in reach)
        unmapped += len(unattributed)
        if unmapped > 0 and coverage == "executed":
            coverage = "partial"

        pure = self._purity(coverage, effects, performs_file_io, unprofiled_calls, ast_facts)

        display = self._display_name(function_id)
        if unmapped > 0:
            notes.append(
                f"{unmapped} recorded accesses in {display} or functions it calls could not be attributed "
                "to a calling context or to memory outside the call; effects may be missing."
            )
        if missing_facts:
            shown = ", ".join(missing_facts[:5])
            if len(missing_facts) > 5:
                shown = f"{len(missing_facts)} functions, e.g. {shown}"
            notes.append(
                "No source-level (AST) facts for " + shown + "; their accesses are classified as "
                "'other' and purity cannot be decided."
            )
        if unprofiled_calls:
            notes.append("The functions in unprofiled_calls were not profiled; their memory effects are unknown.")
        if any(e.source == "static" for e in effects):
            notes.append(
                "Globals marked 'static' are referenced in the code but were not observed being accessed; "
                "their access is taken from the source."
            )

        return SideEffects(
            function=self._info(function),
            coverage=coverage,
            pure_on_observed_inputs=pure,
            performs_file_io=performs_file_io,
            unprofiled_calls=unprofiled_calls,
            effects=effects,
            unmapped_records=unmapped,
            contributing_callees=contributing,
            ast_facts=ast_facts,
            notes=notes,
        )

    def _purity(
        self,
        coverage: Coverage,
        effects: List[Effect],
        performs_file_io: bool,
        unprofiled_calls: List[str],
        ast_facts: bool,
    ) -> Optional[bool]:
        if performs_file_io or any(e.access == "write" and e.source == "observed" for e in effects):
            return False
        if coverage != "executed" or unprofiled_calls or not ast_facts:
            return None
        for effect in effects:
            if effect.access != "read":
                # static "unknown" or static "write"
                return None
            if effect.kind == "other":
                return None
            if effect.kind == "parameter" and not all(len(site.via) == 0 for site in effect.sites):
                return None
            if effect.kind == "global":
                name = effect.member_of if effect.member_of is not None else effect.name
                if not self._globals.get(name, False):
                    return None
        return True

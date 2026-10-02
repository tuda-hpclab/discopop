# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Unit tests of the side effect analysis on small hand-written exports (DESIGN_get_side_effects.md, section 1)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

import pytest

from discopop_explorer.side_effects.analysis import SideEffectIndex, _is_pure_library_function
from discopop_explorer.side_effects.result import Effect, SideEffects
from discopop_explorer.side_effects.schema import FORMAT_VERSION, SideEffectExport

FILE = "/src/code.cpp"


class ExportBuilder:
    """Builds a ``SideEffectExport``. Functions live in file 1; ``main`` (id ``1:1``, lines 100-200) and its
    root instance (``self.main``, work context ``self.main_ctx``) always exist, with main's START edge."""

    def __init__(self) -> None:
        self.files: Dict[str, str] = {"1": FILE}
        self.globals: List[Dict[str, Any]] = []
        self.functions: List[Dict[str, Any]] = []
        self.instances: List[Dict[str, Any]] = []
        self.work_contexts: Dict[str, int] = {}
        self.records: List[Dict[str, Any]] = []
        self.instruction_names: Dict[str, List[str]] = {}
        self.executed_calls: List[Dict[str, Any]] = []
        self.unmapped: Dict[str, int] = {}
        self.linker_names: Dict[str, str] = {}
        self._next_ctx = 1000
        self._next_call = 5000
        self.function("1:1", "main", 100, 200, name="main", locals=[("buf", True, False), ("sum", False, False)])
        self.main, self.main_ctx = self.instance("1:1", None, call=None, edge=False)
        self.executed_calls.append({"caller": None, "call_instruction_id": None, "callee": "1:1"})

    def glob(self, name: str, const: bool = False) -> None:
        self.globals.append({"name": name, "const": const})

    def function(
        self,
        fid: str,
        display: str,
        start: int,
        end: int,
        *,
        name: Optional[str] = None,
        file_id: int = 1,
        params: Sequence[Tuple[str, bool]] = (),
        locals: Sequence[Tuple[str, bool, bool]] = (),
        member_accesses: Optional[Dict[int, Dict[str, str]]] = None,
        static_callees: Sequence[str] = (),
        unprofiled: Sequence[str] = (),
        global_refs: Sequence[Tuple[str, int, str]] = (),
        executed: bool = True,
        ast_facts: bool = True,
        file_io: bool = False,
    ) -> str:
        self.functions.append(
            {
                "id": fid,
                "name": name if name is not None else "_Z" + display.split("(")[0].replace(":", ""),
                "display_name": display,
                "file_id": file_id,
                "start_line": start,
                "end_line": end,
                "ast_facts": ast_facts,
                "params": [{"name": n, "reachable": r} for n, r in params],
                "locals": [{"name": n, "pointer": p, "static": s} for n, p, s in locals],
                "member_accesses": {str(k): v for k, v in (member_accesses or {}).items()},
                "performs_file_io": file_io,
                "static_callees": list(static_callees),
                "unprofiled_calls": list(unprofiled),
                "global_refs": [{"name": n, "line": ln, "access": a} for n, ln, a in global_refs],
                "executed": executed,
            }
        )
        return fid

    def ctx(self, instance: int) -> int:
        """An additional work context of ``instance``."""
        self._next_ctx += 1
        self.work_contexts[str(self._next_ctx)] = instance
        return self._next_ctx

    def instance(
        self, function: str, parent: Optional[int], call: Optional[int] = -1, edge: bool = True
    ) -> Tuple[int, int]:
        """A FunctionContext copy of ``function`` below ``parent``, with one work context; by default with a
        fresh call instruction and a matching executed edge. Returns (instance id, work context id)."""
        if call == -1:
            self._next_call += 1
            call = self._next_call
        inst_id = len(self.instances)
        self.instances.append({"id": inst_id, "function": function, "parent": parent, "call_instruction_id": call})
        if edge and parent is not None:
            self.call(self.instances[parent]["function"], call, function)
        return inst_id, self.ctx(inst_id)

    def call(self, caller: Optional[str], instr: Optional[int], callee: str) -> None:
        self.executed_calls.append({"caller": caller, "call_instruction_id": instr, "callee": callee})

    def record(
        self,
        rtype: str,
        var: str,
        first: Tuple[int, int],
        other: Optional[Tuple[int, int]] = None,
        *,
        pairs: Sequence[Tuple[int, int]] = (),
        first_contexts: Sequence[int] = (),
        other_contexts: Sequence[int] = (),
        other_names: Optional[Sequence[str]] = None,
    ) -> None:
        """``first``/``other`` = (instruction id, line in file 1); ``other_names`` go to instruction_names."""
        self.records.append(
            {
                "type": rtype,
                "var": var,
                "first": [first[0], 1, f"1:{first[1]}"],
                "other": None if other is None else [other[0], 1, f"1:{other[1]}"],
                "pairs": [list(p) for p in pairs],
                "first_contexts": list(first_contexts),
                "other_contexts": list(other_contexts),
            }
        )
        if other is not None and other_names is not None:
            self.instruction_names.setdefault(str(other[0]), []).extend(other_names)

    def build(self) -> SideEffectExport:
        export: Dict[str, Any] = {
            "format_version": FORMAT_VERSION,
            "discopop_version": "test",
            "ignore_dependency_states": False,
            "dependency_file": None,
            "files": self.files,
            "globals": self.globals,
            "functions": self.functions,
            "instances": self.instances,
            "work_contexts": self.work_contexts,
            "records": self.records,
            "instruction_names": self.instruction_names,
            "executed_calls": self.executed_calls,
            "unmapped_records": self.unmapped,
            "linker_names": self.linker_names,
        }
        return cast(SideEffectExport, export)

    def index(self) -> SideEffectIndex:
        return SideEffectIndex(self.build())


def effects(result: SideEffects) -> List[Tuple[str, str, str, str]]:
    """(access, kind, name, source) of every effect, sorted."""
    return sorted((e.access, e.kind, e.name, e.source) for e in result.effects)


def find(result: SideEffects, access: str, name: str) -> Effect:
    matches = [e for e in result.effects if e.access == access and e.name == name]
    assert len(matches) == 1, result.effects
    return matches[0]


# ---------------------------------------------------------------------------------------------- globals


def test_global_write_crossing_and_global_read_inside() -> None:
    b = ExportBuilder()
    b.glob("g_counter")
    wg = b.function("1:5", "write_global(int)", 19, 19, params=[("v", False)])
    rg = b.function("1:6", "read_global()", 22, 22)
    i_w, c_w = b.instance(wg, b.main)
    i_r, c_r = b.instance(rg, b.main)
    # read_global reads what write_global wrote
    b.record("RAW", "g_counter", (10, 22), (20, 19), pairs=[(c_r, c_w)], other_names=["g_counter"])
    index = b.index()
    w = index.compute(wg)
    assert effects(w) == [("write", "global", "g_counter", "observed")]
    assert w.effects[0].sites[0].line == 19 and w.effects[0].sites[0].via == ()
    assert effects(index.compute(rg)) == [("read", "global", "g_counter", "observed")]
    # main contains both ends: the global rule reports them regardless of crossing
    assert effects(index.compute("1:1")) == [
        ("read", "global", "g_counter", "observed"),
        ("write", "global", "g_counter", "observed"),
    ]


def test_global_in_a_loop_inside_the_function_counts_without_crossing() -> None:
    b = ExportBuilder()
    b.glob("g_seq")
    nv = b.function("1:7", "next_value()", 50, 50)
    _, c = b.instance(nv, b.main)
    b.record("RAW", "g_seq", (30, 50), (31, 50), pairs=[(c, c)], other_names=["g_seq"])
    result = b.index().compute(nv)
    assert effects(result) == [("read", "global", "g_seq", "observed"), ("write", "global", "g_seq", "observed")]
    assert result.pure_on_observed_inputs is False


def test_init_of_global_is_a_write_and_init_of_local_is_dropped() -> None:
    b = ExportBuilder()
    b.glob("g_sink")
    f = b.function("1:8", "write_only_global(int)", 30, 32, locals=[("i", False, False)])
    _, c = b.instance(f, b.main)
    b.record("INIT", "g_sink", (40, 31), None, first_contexts=[c])
    b.record("INIT", "i", (41, 32), None, first_contexts=[c])
    result = b.index().compute(f)
    assert effects(result) == [("write", "global", "g_sink", "observed")]


def test_static_local_is_global() -> None:
    b = ExportBuilder()
    f = b.function("1:9", "count_calls()", 80, 84, locals=[("calls", False, True)])
    _, c = b.instance(f, b.main)
    b.record("RAW", "calls", (42, 82), (43, 82), pairs=[(c, c)], other_names=["calls"])
    assert effects(b.index().compute(f)) == [
        ("read", "global", "calls", "observed"),
        ("write", "global", "calls", "observed"),
    ]


def test_static_local_recorded_under_its_linker_name_is_global() -> None:
    """The profiler names function-static locals by their linker name (PoC: _ZZ11count_callsvE5calls)."""
    b = ExportBuilder()
    f = b.function("1:9", "count_calls()", 80, 84, locals=[("calls", False, True)])
    b.linker_names["_ZZ11count_callsvE5calls"] = "calls"
    _, c = b.instance(f, b.main)
    b.record(
        "RAW", "_ZZ11count_callsvE5calls", (42, 82), (43, 82), pairs=[(c, c)], other_names=["_ZZ11count_callsvE5calls"]
    )
    assert effects(b.index().compute(f)) == [
        ("read", "global", "calls", "observed"),
        ("write", "global", "calls", "observed"),
    ]


def test_local_and_param_shadow_globals() -> None:
    b = ExportBuilder()
    b.glob("g_counter")
    b.glob("g_x")
    f = b.function("1:10", "shadow(int)", 70, 75, params=[("g_x", False)], locals=[("g_counter", False, False)])
    _, c = b.instance(f, b.main)
    b.record("RAW", "g_counter", (44, 73), (45, 72), pairs=[(c, c)], other_names=["g_counter"])
    b.record("RAW", "g_counter", (46, 150), (47, 73), pairs=[(b.main_ctx, c)], other_names=["g_counter"])
    b.record("WAW", "g_x", (48, 74), (49, 74), pairs=[(c, c)], other_names=["g_x"])
    result = b.index().compute(f)
    assert result.effects == []
    assert result.pure_on_observed_inputs is True


# ---------------------------------------------------------------------------------------------- parameters


def test_own_param_write_and_by_value_param_dropped() -> None:
    b = ExportBuilder()
    f = b.function("1:11", "write_through_param(int*, int)", 25, 30, params=[("p", True), ("n", False)])
    _, c = b.instance(f, b.main)
    b.record("WAW", "GEPRESULT_p", (50, 27), (50, 27), pairs=[(c, c)], other_names=["GEPRESULT_p"])
    b.record("RAW", "n", (51, 26), (52, 26), pairs=[(c, c)], other_names=["n"])
    result = b.index().compute(f)
    assert effects(result) == [("write", "parameter", "p", "observed")]
    assert result.effects[0].through_pointer is True
    assert result.effects[0].sites[0].via == ()


def test_scalar_pointer_param_without_prefix_is_a_param_access() -> None:
    b = ExportBuilder()
    f = b.function("1:12", "bump(int*)", 55, 55, params=[("x", True)])
    _, c = b.instance(f, b.main)
    b.record("RAW", "x", (53, 55), (54, 55), pairs=[(c, c)], other_names=["x"])
    result = b.index().compute(f)
    assert effects(result) == [("read", "parameter", "x", "observed"), ("write", "parameter", "x", "observed")]
    assert all(e.through_pointer for e in result.effects)


def test_by_value_param_whose_address_is_passed_to_a_callee() -> None:
    b = ExportBuilder()
    bump = b.function("1:12", "bump(int*)", 55, 55, params=[("x", True)])
    at = b.function("1:13", "address_taken(int)", 56, 59, params=[("v", False)], static_callees=[bump])
    i_at, c_at = b.instance(at, b.main)
    _, c_bump = b.instance(bump, i_at)
    # address_taken reads v after bump wrote *x: inside address_taken, no crossing
    b.record("RAW", "v", (60, 58), (61, 55), pairs=[(c_at, c_bump)], other_names=["x"])
    # main reads sum, which got address_taken's v (crossing, but v is a by-value param: local)
    b.record("RAW", "sum", (62, 150), (63, 58), pairs=[(b.main_ctx, c_at)], other_names=["v"])
    index = b.index()
    assert index.compute(at).effects == []
    assert index.compute(at).pure_on_observed_inputs is True


def test_callee_param_crossing_reported_via_callee() -> None:
    b = ExportBuilder()
    wtp = b.function("1:11", "write_through_param(int*, int)", 25, 30, params=[("p", True), ("n", False)])
    wr = b.function("1:14", "wrapper(int*, int)", 33, 33, params=[("q", True), ("n", False)], static_callees=[wtp])
    i_wr, _ = b.instance(wr, b.main)
    _, c_wtp = b.instance(wtp, i_wr)
    b.record("RAW", "GEPRESULT_buf", (64, 160), (65, 27), pairs=[(b.main_ctx, c_wtp)], other_names=["GEPRESULT_p"])
    index = b.index()
    result = index.compute(wr)
    assert effects(result) == [("write", "parameter", "p", "observed")]
    effect = result.effects[0]
    assert effect.sites[0].via == ("write_through_param(int*, int)",)
    assert effect.outside_names == ["buf"]  # without the profiler's GEPRESULT_ prefix
    assert effect.is_own is False
    assert result.contributing_callees == ["write_through_param(int*, int)"]
    # write_through_param's outermost instance is the one below wrapper; its own param effect
    callee = index.compute(wtp)
    assert effects(callee) == [("write", "parameter", "p", "observed")]
    assert callee.effects[0].sites[0].via == ()
    # main contains both ends: nothing crosses, p is no parameter of main
    assert index.compute("1:1").effects == []


def test_callee_param_not_crossing_is_internal() -> None:
    b = ExportBuilder()
    wtp = b.function("1:11", "write_through_param(int*, int)", 25, 30, params=[("p", True), ("n", False)])
    lb = b.function("1:15", "local_buffer()", 36, 40, locals=[("local", False, False)], static_callees=[wtp])
    i_lb, c_lb = b.instance(lb, b.main)
    _, c_wtp = b.instance(wtp, i_lb)
    b.record("RAW", "GEPRESULT_local", (66, 39), (67, 27), pairs=[(c_lb, c_wtp)], other_names=["GEPRESULT_p"])
    result = b.index().compute(lb)
    assert result.effects == []
    assert result.pure_on_observed_inputs is True


def test_two_calls_exchanging_data_through_a_callee_param() -> None:
    b = ExportBuilder()
    g = b.function("1:16", "g(int*)", 10, 12, params=[("p", True)])
    f = b.function("1:17", "f()", 13, 15, static_callees=[g])
    i_f1, _ = b.instance(f, b.main)
    i_f2, _ = b.instance(f, b.main)
    _, c_g1 = b.instance(g, i_f1)
    _, c_g2 = b.instance(g, i_f2)
    # the second call's g reads what the first call's g wrote
    b.record("RAW", "GEPRESULT_p", (68, 11), (69, 11), pairs=[(c_g2, c_g1)], other_names=["GEPRESULT_p"])
    result = b.index().compute(f)
    assert effects(result) == [("read", "parameter", "p", "observed"), ("write", "parameter", "p", "observed")]
    assert all(site.via == ("g(int*)",) for e in result.effects for site in e.sites)


def test_param_of_inner_recursive_instance_is_not_a_param_of_f() -> None:
    # f(int* p) { int l; f(&l); *p = 1; }
    b = ExportBuilder()
    f = b.function("1:18", "f(int*)", 1, 5, params=[("p", True)], locals=[("l", False, False)], static_callees=["1:18"])
    i_outer, c_outer = b.instance(f, b.main)
    i_inner, c_inner = b.instance(f, i_outer)
    b.record("INIT", "GEPRESULT_p", (70, 4), None, first_contexts=[c_outer, c_inner])
    b.record("RAW", "l", (71, 3), (72, 4), pairs=[(c_outer, c_inner)], other_names=["GEPRESULT_p"])
    b.call(f, None, f)  # the innermost recursion level (beyond the inlined instances)
    index = b.index()
    assert index._outermost[f] == [i_outer]
    result = index.compute(f)
    assert effects(result) == [("write", "parameter", "p", "observed")]
    # one site: the inner instance's *p is not F's parameter
    assert [(s.line, s.via) for s in result.effects[0].sites] == [(4, ())]


def test_recursion_global_effect_in_nested_instance_has_empty_via() -> None:
    b = ExportBuilder()
    b.glob("g_counter")
    r = b.function("1:19", "recurse(int)", 100, 106, params=[("n", False)], static_callees=["1:19"])
    i1, _ = b.instance(r, b.main)
    i2, _ = b.instance(r, i1)
    _, c3 = b.instance(r, i2)
    b.record("RAW", "g_counter", (73, 102), (74, 102), pairs=[(c3, c3)], other_names=["g_counter"])
    b.call(r, 9999, r)  # the deepest instance's recursive call has no inlined child
    result = b.index().compute(r)
    assert effects(result) == [
        ("read", "global", "g_counter", "observed"),
        ("write", "global", "g_counter", "observed"),
    ]
    assert all(site.via == () for e in result.effects for site in e.sites)
    assert result.coverage == "partial"


# ---------------------------------------------------------------------------------------------- other memory


def test_pointer_local_is_other_only_when_crossing() -> None:
    b = ExportBuilder()
    f = b.function("1:20", "alloc_fill()", 10, 20, locals=[("q", True, False)])
    _, c = b.instance(f, b.main)
    # main reads what f wrote through q (escaping heap memory)
    b.record("RAW", "call101", (75, 150), (76, 15), pairs=[(b.main_ctx, c)], other_names=["q"])
    # f reads through q what it wrote itself: not crossing
    b.record("RAW", "GEPRESULT_q", (77, 16), (78, 15), pairs=[(c, c)], other_names=["GEPRESULT_q"])
    result = b.index().compute(f)
    assert effects(result) == [("write", "other", "q", "observed")]
    assert result.effects[0].through_pointer is True
    assert result.effects[0].outside_names == ["call101"]


def test_stack_local_names_are_dropped_even_when_crossing() -> None:
    b = ExportBuilder()
    bump = b.function("1:12", "bump(int*)", 55, 55, params=[("x", True)])
    sa = b.function("1:21", "sibling_a()", 60, 64, locals=[("a", False, False)], static_callees=[bump])
    sb = b.function("1:22", "sibling_b()", 65, 69, locals=[("b", False, False)], static_callees=[bump])
    i_a, c_a = b.instance(sa, b.main)
    i_b, c_b = b.instance(sb, b.main)
    _, c_bump_a = b.instance(bump, i_a)
    # the reused stack slot: sibling_b's local b reads what sibling_a's bump wrote
    b.record("RAW", "b", (79, 67), (80, 55), pairs=[(c_b, c_bump_a)], other_names=["x"])
    index = b.index()
    assert index.compute(sb).effects == []
    # documented limitation: for sibling_a the slot looks like a callee param crossing
    assert effects(index.compute(sa)) == [("write", "parameter", "x", "observed")]


def test_unknown_name_is_other_when_crossing() -> None:
    b = ExportBuilder()
    f = b.function("1:23", "tmp()", 10, 12)
    _, c = b.instance(f, b.main)
    b.record("WAR", "call7", (81, 11), (82, 150), pairs=[(c, b.main_ctx)], other_names=["buf"])
    result = b.index().compute(f)
    assert effects(result) == [("write", "other", "call7", "observed")]
    assert result.pure_on_observed_inputs is False


def test_read_of_other_memory_makes_purity_unknown() -> None:
    b = ExportBuilder()
    f = b.function("1:23", "tmp()", 10, 12)
    _, c = b.instance(f, b.main)
    b.record("RAW", "call7", (81, 11), (82, 150), pairs=[(c, b.main_ctx)], other_names=["buf"])
    result = b.index().compute(f)
    assert effects(result) == [("read", "other", "call7", "observed")]
    assert result.pure_on_observed_inputs is None


# ---------------------------------------------------------------------------------------------- members


def test_member_access_via_member_expr() -> None:
    b = ExportBuilder()
    f = b.function("1:24", "set_member(Pair*)", 27, 27, params=[("s", True)], member_accesses={27: {"second": "s"}})
    _, c = b.instance(f, b.main)
    b.record("INIT", "second", (83, 27), None, first_contexts=[c])
    result = b.index().compute(f)
    assert effects(result) == [("write", "parameter", "second", "observed")]
    assert result.effects[0].member_of == "s"
    assert result.effects[0].through_pointer is True


def test_member_access_through_gep_prefix_and_this_and_unknown_base() -> None:
    b = ExportBuilder()
    b.glob("second")  # a global of the member's name must not capture the member access
    f = b.function(
        "1:25",
        "Cls::m()",
        40,
        45,
        member_accesses={41: {"second": "this"}, 42: {"arr": "this"}, 43: {"first": ""}},
    )
    _, c = b.instance(f, b.main)
    b.record("INIT", "second", (84, 41), None, first_contexts=[c])
    b.record("INIT", "GEPRESULT_arr", (85, 42), None, first_contexts=[c])
    b.record("RAW", "first", (86, 150), (87, 43), pairs=[(b.main_ctx, c)], other_names=["first"])
    result = b.index().compute(f)
    assert effects(result) == [
        ("write", "other", "first", "observed"),
        ("write", "parameter", "arr", "observed"),
        ("write", "parameter", "second", "observed"),
    ]
    assert find(result, "write", "second").member_of == "this"
    assert find(result, "write", "first").member_of is None


def test_poc_form_of_member_write_gepresult_of_param() -> None:
    b = ExportBuilder()
    f = b.function("1:24", "set_member(Pair*)", 27, 27, params=[("s", True)])
    _, c = b.instance(f, b.main)
    b.record("INIT", "GEPRESULT_s", (83, 27), None, first_contexts=[c])
    assert effects(b.index().compute(f)) == [("write", "parameter", "s", "observed")]


def test_member_of_a_local_struct_is_dropped() -> None:
    b = ExportBuilder()
    f = b.function("1:26", "local_pair()", 10, 12, locals=[("pr", False, False)], member_accesses={11: {"first": "pr"}})
    _, c = b.instance(f, b.main)
    b.record("RAW", "first", (88, 150), (89, 11), pairs=[(b.main_ctx, c)], other_names=["first"])
    assert b.index().compute(f).effects == []


# ---------------------------------------------------------------------------------------------- names


def test_missing_instruction_name_for_other_end() -> None:
    b = ExportBuilder()
    b.glob("g")
    f = b.function("1:27", "f()", 10, 12)
    _, c = b.instance(f, b.main)
    # other end inside, unnamed: not classified, no effect
    b.record("RAW", "g", (90, 150), (91, 11), pairs=[(b.main_ctx, c)])
    result = b.index().compute(f)
    assert result.effects == []

    b2 = ExportBuilder()
    b2.glob("g")
    f2 = b2.function("1:27", "f()", 10, 12)
    _, c2 = b2.instance(f2, b2.main)
    # first end inside, other end outside and unnamed: reported under the inside name, no outside names
    b2.record("WAR", "g", (92, 11), (93, 150), pairs=[(c2, b2.main_ctx)])
    result2 = b2.index().compute(f2)
    assert effects(result2) == [("write", "global", "g", "observed")]
    assert result2.effects[0].outside_names == []


def test_several_names_for_the_other_end_pick_the_most_significant() -> None:
    b = ExportBuilder()
    b.glob("g")
    f = b.function("1:28", "f()", 10, 12, locals=[("tmp", False, False)])
    _, c = b.instance(f, b.main)
    b.record("RAW", "x", (94, 150), (95, 11), pairs=[(b.main_ctx, c)], other_names=["tmp", "g"])
    result = b.index().compute(f)
    assert effects(result) == [("write", "global", "g", "observed")]
    assert result.effects[0].outside_names == ["x"]


def test_missing_ast_facts_makes_everything_other() -> None:
    b = ExportBuilder()
    b.glob("g")
    f = b.function("1:29", "sys_fn(int*)", 10, 12, ast_facts=False)
    _, c = b.instance(f, b.main)
    b.record("RAW", "g", (96, 11), (97, 11), pairs=[(c, c)], other_names=["g"])  # not crossing: dropped
    b.record("WAR", "GEPRESULT_p", (98, 11), (99, 150), pairs=[(c, b.main_ctx)], other_names=["buf"])
    result = b.index().compute(f)
    assert effects(result) == [("write", "other", "p", "observed")]
    assert result.effects[0].through_pointer is True
    assert result.ast_facts is False
    assert any("AST" in note for note in result.notes)


def test_missing_ast_facts_of_a_callee_makes_purity_unknown() -> None:
    b = ExportBuilder()
    callee = b.function("1:30", "std::helper()", 1, 2, ast_facts=False)
    f = b.function("1:31", "f()", 10, 12, static_callees=[callee])
    i_f, _ = b.instance(f, b.main)
    b.instance(callee, i_f)
    result = b.index().compute(f)
    assert result.effects == []
    assert result.ast_facts is False
    assert result.pure_on_observed_inputs is None


# ---------------------------------------------------------------------------------------------- static facts


def test_static_fallback_for_unobserved_globals() -> None:
    b = ExportBuilder()
    b.glob("g_table", const=True)
    b.glob("g_counter")
    helper = b.function("1:32", "helper()", 1, 3, global_refs=[("g_table", 2, "read")])
    f = b.function(
        "1:33",
        "read_const_table(int)",
        35,
        35,
        params=[("i", False)],
        static_callees=[helper],
        global_refs=[("g_table", 35, "read"), ("g_counter", 35, "read")],
    )
    i_f, c = b.instance(f, b.main)
    b.instance(helper, i_f)
    # g_counter is observed, g_table is not
    b.record("RAW", "g_counter", (100, 35), (101, 150), pairs=[(c, b.main_ctx)], other_names=["g_counter"])
    result = b.index().compute(f)
    assert effects(result) == [
        ("read", "global", "g_counter", "observed"),
        ("read", "global", "g_table", "static"),
    ]
    table = find(result, "read", "g_table")
    assert [(s.line, s.via) for s in table.sites] == [(2, ("helper()",)), (35, ())]
    assert result.contributing_callees == ["helper()"]
    assert any("static" in note for note in result.notes)
    # g_counter is mutable
    assert result.pure_on_observed_inputs is None


def test_static_read_of_const_global_only_is_pure() -> None:
    b = ExportBuilder()
    b.glob("g_table", const=True)
    f = b.function("1:33", "read_const_table(int)", 35, 35, global_refs=[("g_table", 35, "read")])
    b.instance(f, b.main)
    result = b.index().compute(f)
    assert effects(result) == [("read", "global", "g_table", "static")]
    assert result.pure_on_observed_inputs is True


@pytest.mark.parametrize("access", ["unknown", "write", "bogus"])
def test_static_unknown_or_write_access_makes_purity_unknown(access: str) -> None:
    b = ExportBuilder()
    b.glob("g", const=True)
    f = b.function("1:34", "f()", 10, 12, global_refs=[("g", 11, access)])
    b.instance(f, b.main)
    result = b.index().compute(f)
    assert result.effects[0].source == "static"
    assert result.effects[0].access == ("write" if access == "write" else "unknown")
    assert result.pure_on_observed_inputs is None


def test_static_closure_is_cycle_safe() -> None:
    b = ExportBuilder()
    b.glob("g", const=True)
    a = b.function("1:35", "a()", 1, 2, static_callees=["1:36", "1:99"])
    b.function("1:36", "b()", 3, 4, static_callees=["1:35", "1:36"], global_refs=[("g", 4, "read")])
    b.instance(a, b.main)
    result = b.index().compute(a)
    assert [(s.line, s.via) for s in result.effects[0].sites] == [(4, ("b()",))]


def test_unprofiled_calls_with_allowlist_and_file_io() -> None:
    b = ExportBuilder()
    log = b.function("1:37", "log_value(int)", 1, 2, unprofiled=["printf"], file_io=True)
    f = b.function(
        "1:38",
        "f(int*, int)",
        10,
        12,
        static_callees=[log],
        unprofiled=["memset", "sqrt", "std::sqrt(double)", "std::max<int>", "::fabs", "mylib::sqrt"],
    )
    i_f, _ = b.instance(f, b.main)
    b.instance(log, i_f)
    result = b.index().compute(f)
    assert result.unprofiled_calls == ["memset", "mylib::sqrt", "printf"]
    assert result.performs_file_io is True
    assert result.pure_on_observed_inputs is False
    assert any("memset" in note for note in result.notes)


def test_unprofiled_calls_make_purity_unknown() -> None:
    b = ExportBuilder()
    f = b.function("1:39", "clear(int*, int)", 10, 12, unprofiled=["memset"])
    g = b.function("1:40", "root(double)", 13, 14, unprofiled=["sqrt", "std::pow(double, double)"])
    b.instance(f, b.main)
    b.instance(g, b.main)
    index = b.index()
    assert index.compute(f).pure_on_observed_inputs is None
    assert index.compute(g).unprofiled_calls == []
    assert index.compute(g).pure_on_observed_inputs is True


def test_library_allowlist_normalization() -> None:
    assert _is_pure_library_function("sqrt")
    assert _is_pure_library_function("std::__1::sqrt(double)")
    assert _is_pure_library_function("std::min<double>")
    assert _is_pure_library_function("min")  # matches std::min
    assert _is_pure_library_function("memcpy") is False
    assert _is_pure_library_function("ns::floor(double)") is False


# ---------------------------------------------------------------------------------------------- coverage


def test_coverage_not_executed_reports_only_static_facts() -> None:
    b = ExportBuilder()
    b.glob("g_unused")
    nc = b.function("1:41", "never_called()", 90, 90, executed=False, global_refs=[("g_unused", 90, "write")])
    _, c = b.instance(nc, b.main, edge=False)
    # states are inherited: a record may be mapped to the never executed instance
    b.record("INIT", "g_unused", (102, 90), None, first_contexts=[c])
    result = b.index().compute(nc)
    assert result.coverage == "not_executed"
    assert effects(result) == [("write", "global", "g_unused", "static")]
    assert result.pure_on_observed_inputs is None
    assert any("not executed" in note for note in result.notes)


def test_coverage_untracked_function_pointer_target_and_partial_caller() -> None:
    b = ExportBuilder()
    b.glob("g_pointer_target")
    pt = b.function("1:42", "pointer_target()", 1, 1)
    cvp = b.function("1:43", "call_via_pointer(void (*)())", 2, 2, params=[("f", False)])
    b.instance(cvp, b.main)
    b.call(cvp, 777, pt)  # executed through the pointer, no inlined context
    index = b.index()
    target = index.compute(pt)
    assert target.coverage == "untracked"
    assert target.effects == []
    assert target.pure_on_observed_inputs is None
    assert any("attributed" in note for note in target.notes)
    caller = index.compute(cvp)
    assert caller.coverage == "partial"
    assert caller.pure_on_observed_inputs is None
    # partial propagates to main (the edge's caller lies below main)
    assert index.compute("1:1").coverage == "partial"


def test_coverage_depth_limit_chain() -> None:
    b = ExportBuilder()
    b.glob("g_chain")
    c3 = b.function("1:46", "chain3()", 3, 3, global_refs=[("g_chain", 3, "write")])
    c2 = b.function("1:45", "chain2()", 2, 2, static_callees=[c3])
    c1 = b.function("1:44", "chain1()", 1, 1, static_callees=[c2])
    i1, _ = b.instance(c1, b.main)
    b.instance(c2, i1)
    b.call(c2, 888, c3)  # chain2 -> chain3 beyond the inlining depth
    index = b.index()
    r1 = index.compute(c1)
    assert r1.coverage == "partial"
    assert effects(r1) == [("write", "global", "g_chain", "static")]
    assert r1.effects[0].sites[0].via == ("chain2()", "chain3()")
    assert index.compute(c3).coverage == "untracked"


def test_coverage_partial_when_only_some_edges_into_f_match() -> None:
    b = ExportBuilder()
    f = b.function("1:47", "f()", 1, 1)
    b.instance(f, b.main)
    b.call("1:1", None, f)  # a callback from library code into f
    assert b.index().compute(f).coverage == "partial"


def test_coverage_executed_and_main() -> None:
    b = ExportBuilder()
    f = b.function("1:48", "pure_add(int, int)", 1, 1, params=[("a", False), ("b", False)])
    b.instance(f, b.main)
    index = b.index()
    result = index.compute(f)
    assert result.coverage == "executed"
    assert result.effects == []
    assert result.pure_on_observed_inputs is True
    assert result.notes == []
    assert index.compute("1:1").coverage == "executed"


def test_unmapped_records_make_purity_unknown_also_for_callers() -> None:
    """Accesses that could not be attributed to a calling context may hide effects: never 'pure'."""
    b = ExportBuilder()
    callee = b.function("1:50", "g()", 2, 2)
    f = b.function("1:49", "f()", 1, 1, static_callees=[callee])
    i_f, _ = b.instance(f, b.main)
    b.instance(callee, i_f)
    assert b.index().compute(f).pure_on_observed_inputs is True
    b.unmapped[callee] = 2
    result = b.index().compute(f)
    assert result.pure_on_observed_inputs is None
    assert any("could not be attributed" in note for note in result.notes)


def test_global_access_counts_when_only_one_end_is_mapped() -> None:
    """The other end may lie beyond the inlining depth: the per-access rule needs only its own end."""
    b = ExportBuilder()
    b.glob("g")
    f = b.function("1:49", "f()", 1, 1)
    _, c = b.instance(f, b.main)
    # read in f of a value written by code without a context (no pairs at all)
    b.record("RAW", "g", (10, 1), (11, 90), first_contexts=[c])
    # write in f that is only paired with an unmapped later read
    b.record("RAW", "g", (12, 95), (13, 1), other_contexts=[c], other_names=["g"])
    assert effects(b.index().compute(f)) == [("read", "global", "g", "observed"), ("write", "global", "g", "observed")]


def test_unmapped_records_are_reported_not_folded_into_coverage() -> None:
    b = ExportBuilder()
    f = b.function("1:49", "f()", 1, 1)
    b.instance(f, b.main)
    b.unmapped[f] = 3
    result = b.index().compute(f)
    assert result.unmapped_records == 3
    assert result.coverage == "executed"
    assert any("3 recorded" in note for note in result.notes)


# ---------------------------------------------------------------------------------------------- purity


def test_pure_truth_table() -> None:
    b = ExportBuilder()
    b.glob("g_mut")
    b.glob("g_const", const=True)
    wtp = b.function("1:11", "write_through_param(int*, int)", 25, 30, params=[("p", True)])
    rp = b.function("1:50", "read_param(int*)", 1, 1, params=[("p", True)])
    rc = b.function("1:51", "read_const()", 2, 2)
    rm = b.function("1:52", "read_mut()", 3, 3)
    rcp = b.function("1:53", "read_via_callee(int*)", 4, 4, params=[("q", True)], static_callees=[rp])
    _, c_wtp = b.instance(wtp, b.main)
    _, c_rp = b.instance(rp, b.main)
    _, c_rc = b.instance(rc, b.main)
    _, c_rm = b.instance(rm, b.main)
    i_rcp, _ = b.instance(rcp, b.main)
    _, c_rp2 = b.instance(rp, i_rcp)
    b.record("RAW", "GEPRESULT_p", (103, 1), (104, 27), pairs=[(c_rp, c_wtp), (c_rp2, c_wtp)], other_names=["p"])
    b.record("RAW", "g_const", (105, 2), (106, 150), pairs=[(c_rc, b.main_ctx)], other_names=["g_const"])
    b.record("RAW", "g_mut", (107, 3), (108, 150), pairs=[(c_rm, b.main_ctx)], other_names=["g_mut"])
    index = b.index()
    assert index.compute(wtp).pure_on_observed_inputs is False  # observed write
    assert index.compute(rp).pure_on_observed_inputs is True  # read through own param
    assert index.compute(rc).pure_on_observed_inputs is True  # read of a const global
    assert index.compute(rm).pure_on_observed_inputs is None  # read of a mutable global
    assert index.compute(rcp).pure_on_observed_inputs is None  # read through a callee's param


def test_observed_write_is_impure_under_any_coverage() -> None:
    b = ExportBuilder()
    b.glob("g")
    f = b.function("1:54", "f()", 1, 1)
    _, c = b.instance(f, b.main)
    b.call("1:1", None, f)
    b.record("INIT", "g", (109, 1), None, first_contexts=[c])
    result = b.index().compute(f)
    assert result.coverage == "partial"
    assert result.pure_on_observed_inputs is False


def test_partial_coverage_without_writes_is_unknown() -> None:
    b = ExportBuilder()
    f = b.function("1:55", "f()", 1, 1)
    b.instance(f, b.main)
    b.call("1:1", None, f)
    assert b.index().compute(f).pure_on_observed_inputs is None


# ---------------------------------------------------------------------------------------------- lookup


def lookup_index() -> SideEffectIndex:
    b = ExportBuilder()
    b.files["2"] = "/src/other.cpp"
    b.function("1:5", "write_global(int)", 19, 19, name="_Z12write_globali")
    b.function("1:60", "ns::Cls::method(int) const", 40, 45, name="_ZNK2ns3Cls6methodEi")
    b.function("1:61", "ns::Cls::method(double)", 46, 50, name="_ZN2ns3Cls6methodEd")
    b.function("1:62", "foo()", 60, 65)
    b.function("2:3", "foo()", 5, 9, file_id=2)
    b.function("1:63", "int tmpl<int>(int)", 70, 72)
    return b.index()


@pytest.mark.parametrize(
    "query, expected",
    [
        ("write_global", ["1:5"]),
        ("write_global(int)", ["1:5"]),
        ("write_global( int )", ["1:5"]),
        ("_Z12write_globali", ["1:5"]),
        ("write_global(double)", []),
        ("ns::Cls::method", ["1:60", "1:61"]),
        ("Cls::method", ["1:60", "1:61"]),
        ("method", ["1:60", "1:61"]),
        ("method(int)", ["1:60"]),
        ("ns::Cls::method(double)", ["1:61"]),
        ("ns::Cls::method(int) const", ["1:60"]),
        ("::ns::Cls::method(double)", ["1:61"]),
        ("ls::method", []),
        ("tmpl", ["1:63"]),
        ("tmpl<int>", ["1:63"]),
        ("unknown", []),
    ],
)
def test_find_functions_name_forms(query: str, expected: List[str]) -> None:
    assert sorted(info.id for info in lookup_index().find_functions(query)) == expected


def test_find_functions_ambiguity_narrowed_by_file_and_line(tmp_path: Any) -> None:
    index = lookup_index()
    both = index.find_functions("foo")
    assert [(i.file, i.start_line) for i in both] == [("/src/code.cpp", 60), ("/src/other.cpp", 5)]
    assert [i.id for i in index.find_functions("foo", file_path="/src/other.cpp")] == ["2:3"]
    assert [i.id for i in index.find_functions("foo", file_path="/src/../src/other.cpp")] == ["2:3"]
    assert [i.id for i in index.find_functions("foo", line=62)] == ["1:62"]
    assert [i.id for i in index.find_functions("foo", line=9)] == ["2:3"]
    assert index.find_functions("foo", line=10) == []
    assert index.find_functions("foo", file_path="/src/none.cpp") == []
    info = both[0]
    assert (info.name, info.display_name, info.file_id, info.end_line) == ("_Zfoo", "foo()", 1, 65)


def test_find_functions_resolves_symlinked_paths(tmp_path: Any) -> None:
    real = tmp_path / "real.cpp"
    real.write_text("")
    link = tmp_path / "link.cpp"
    link.symlink_to(real)
    b = ExportBuilder()
    b.files["1"] = str(real)
    b.function("1:2", "foo()", 1, 3)
    assert [i.id for i in b.index().find_functions("foo", file_path=str(link))] == ["1:2"]


# ---------------------------------------------------------------------------------------------- index


def test_compute_cache_and_unknown_id() -> None:
    b = ExportBuilder()
    f = b.function("1:70", "f()", 1, 1)
    b.instance(f, b.main)
    index = b.index()
    assert index.compute(f) is index.compute(f)
    with pytest.raises(KeyError):
        index.compute("9:99")


def test_instance_parent_cycle_does_not_hang() -> None:
    b = ExportBuilder()
    f = b.function("1:71", "f()", 1, 1)
    g = b.function("1:72", "g()", 2, 2)
    b.instances.append({"id": 1, "function": f, "parent": 2, "call_instruction_id": 1})
    b.instances.append({"id": 2, "function": g, "parent": 1, "call_instruction_id": 2})
    c = b.ctx(1)
    b.record("INIT", "x", (110, 1), None, first_contexts=[c, 424242])
    index = b.index()
    assert len(index._order) == 3
    result = index.compute(f)
    assert result.coverage == "untracked"


def test_unmapped_context_in_pair_is_ignored() -> None:
    b = ExportBuilder()
    f = b.function("1:73", "f()", 1, 1)
    _, c = b.instance(f, b.main)
    b.record("RAW", "call1", (111, 1), (112, 150), pairs=[(c, 999999)], other_names=["x"])
    assert b.index().compute(f).effects == []


def test_sites_are_sorted_and_merged() -> None:
    b = ExportBuilder()
    b.glob("g")
    f = b.function("1:74", "f()", 1, 9)
    _, c = b.instance(f, b.main)
    b.record("INIT", "g", (113, 8), None, first_contexts=[c])
    b.record("INIT", "g", (114, 3), None, first_contexts=[c])
    b.record("WAW", "GEPRESULT_g", (115, 3), (114, 3), pairs=[(c, c)], other_names=["g"])
    result = b.index().compute(f)
    write = find(result, "write", "g")
    assert [s.line for s in write.sites] == [3, 8]
    assert write.through_pointer is True

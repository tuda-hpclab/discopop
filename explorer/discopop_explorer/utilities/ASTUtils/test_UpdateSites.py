# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for UpdateSites, on real clang JSON ASTs.

``testdata/update_sites/updates.cpp`` holds one small function per case, ``ast.json`` is its AST, dumped with::

    clang++ -std=c++17 -fsyntax-only -Xclang -ast-dump=json -Xclang -ast-dump-filter=upd_ updates.cpp > ast.json

Expected columns are the 1-based byte columns of ``updates.cpp``. When the source is edited, the line numbers
below and the dump have to be regenerated together.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List

import networkx as nx
import pytest

from discopop_explorer.utilities.ASTUtils.ASTGraph import ClangASTGraph
from discopop_explorer.utilities.ASTUtils.ASTLoader import ClangASTLoader
from discopop_explorer.utilities.ASTUtils.ASTPatternDetectionIntegration import ASTPatternDetectionHelper
from discopop_explorer.utilities.ASTUtils.UpdateSites import (
    DEPENDENT_TYPE,
    INSTANTIATIONS_DIFFER,
    MACRO,
    MULTI_LINE,
    NOT_A_STATEMENT,
    NOT_ALONE_ON_LINE,
    RHS_REFERENCES_LHS,
    UpdateSite,
    file_facts,
    update_sites_on_line,
)

# ast.json was dumped from inside testdata/update_sites with
#   clang++ -std=c++17 -fsyntax-only -Xclang -ast-dump=json -Xclang -ast-dump-filter=upd_ updates.cpp
TESTDATA = Path(__file__).parent / "testdata" / "update_sites"
SOURCE = "updates.cpp"

# lines of updates.cpp
TMPL_LINE = 9  # out[idx[i]] += in[i];  (instantiated for double and float)
NEVER_LINE = 14  # out[i] += in[i];  (template never instantiated)
BASIC_LINE = 23  # a[idx[i]] += v;
POSTFIX_INC_LINE = 28  # h[k]++;
PREFIX_INC_LINE = 29  # ++h[k];
POSTFIX_DEC_LINE = 30  # h[k]--;
MUL_LINE, AND_LINE, OR_LINE, XOR_LINE, SUB_LINE = 35, 36, 37, 38, 39
PREFIX_SUM_LINE = 44  # p[i + 1] += p[i];
VALUE_USED_LINE = 50  # y[k] = h[k]++;
BRACELESS_LINE = 52  # for (...) s += x[i];
TWO_ON_LINE = 56  # a[k] += 1; b[k] += 1;
BLOCK_ON_LINE = 58  # for (...) { a[k] += 1; }
MULTI_LINE_LINE = 62  # a[k] +=\n v[k];
MACRO_LINE = 68  # ADD(a[k], 1.0);
VECTOR_LINE = 73  # v[k] += x[k];
MEMBER_CALL_LINE = 74  # d.fx(n) += f;
COMPLEX_LINE = 79  # c += z;  (std::complex)
NO_UPDATE_LINE = 84  # a[k] = 1.0;
FOR_HEADER_LINE = 22  # for (int i = 0; i < n; i++)


@pytest.fixture(scope="module")  # type: ignore[misc]
def graph() -> nx.DiGraph[str]:
    return ClangASTGraph().build_from_ast(ClangASTLoader.load_ast(str(TESTDATA / "ast.json")))


def _sites(graph: nx.DiGraph[str], line: int) -> List[UpdateSite]:
    return update_sites_on_line(graph, SOURCE, line)


def _only(graph: nx.DiGraph[str], line: int) -> UpdateSite:
    sites = _sites(graph, line)
    assert len(sites) == 1, sites
    return sites[0]


def test_compound_assignment_alone_on_line_covers_exactly_the_gap_between_the_operands(
    graph: nx.DiGraph[str],
) -> None:
    site = _only(graph, BASIC_LINE)
    assert site.problem is None
    assert site.operator == "+="
    assert site.operator_class == "+"
    assert site.variable == "a"
    # "        a[idx[i]] += v;": a[idx[i]] spans columns 9..17, the operator is at 19..20, v at 22
    assert (site.first_column, site.last_column) == (18, 21)
    assert site.covers(19) and site.covers(20)
    assert not site.covers(17) and not site.covers(22)
    assert (site.begin_column, site.end_column) == (9, 22)


def test_postfix_increment_is_reported_at_the_operator_column(graph: nx.DiGraph[str]) -> None:
    site = _only(graph, POSTFIX_INC_LINE)  # "        h[k]++;" -> "++" at 13
    assert site.problem is None
    assert (site.operator, site.operator_class, site.variable) == ("++", "+", "h")
    assert site.first_column == site.last_column == 13


def test_prefix_increment_is_reported_at_the_operator_column(graph: nx.DiGraph[str]) -> None:
    site = _only(graph, PREFIX_INC_LINE)  # "        ++h[k];" -> "++" at 9
    assert site.problem is None
    assert (site.operator, site.variable) == ("++", "h")
    assert site.first_column == site.last_column == 9


def test_postfix_decrement_is_reported_at_the_operator_column(graph: nx.DiGraph[str]) -> None:
    site = _only(graph, POSTFIX_DEC_LINE)  # "        h[k]--;" -> "--" at 13
    assert site.problem is None
    assert (site.operator, site.operator_class) == ("--", "+")
    assert site.first_column == site.last_column == 13


@pytest.mark.parametrize(  # type: ignore[misc]
    "line, operator, operator_class",
    [
        (MUL_LINE, "*=", "*"),
        (AND_LINE, "&=", "&"),
        (OR_LINE, "|=", "|"),
        (XOR_LINE, "^=", "^"),
        (SUB_LINE, "-=", "+"),
    ],
)
def test_operator_classes(graph: nx.DiGraph[str], line: int, operator: str, operator_class: str) -> None:
    site = _only(graph, line)
    assert site.problem is None
    assert site.operator == operator
    assert site.operator_class == operator_class
    # "        m[k] *= v;": m[k] ends at 12, the operand starts at 17
    assert (site.first_column, site.last_column) == (13, 16)


def test_prefix_sum_references_its_own_left_hand_side(graph: nx.DiGraph[str]) -> None:
    site = _only(graph, PREFIX_SUM_LINE)
    assert site.problem == RHS_REFERENCES_LHS
    assert (site.operator, site.variable) == ("+=", "p")


def test_update_whose_value_is_used_is_not_a_statement(graph: nx.DiGraph[str]) -> None:
    site = _only(graph, VALUE_USED_LINE)  # y[k] = h[k]++;
    assert site.problem == NOT_A_STATEMENT
    assert (site.operator, site.variable) == ("++", "h")
    assert site.first_column == site.last_column == 20


def test_braceless_loop_body_is_not_a_statement(graph: nx.DiGraph[str]) -> None:
    # "    for (int i = 0; i < n; i++) s += x[i];"
    sites = _sites(graph, BRACELESS_LINE)
    assert [(s.operator, s.variable, s.problem) for s in sites] == [
        ("++", "i", NOT_A_STATEMENT),
        ("+=", "s", NOT_A_STATEMENT),
    ]


def test_for_loop_increment_on_the_header_line_is_not_a_statement(graph: nx.DiGraph[str]) -> None:
    site = _only(graph, FOR_HEADER_LINE)
    assert (site.operator, site.variable, site.problem) == ("++", "i", NOT_A_STATEMENT)


def test_two_statements_on_one_line_are_both_not_alone(graph: nx.DiGraph[str]) -> None:
    sites = _sites(graph, TWO_ON_LINE)  # "        a[k] += 1; b[k] += 1;"
    assert [(s.variable, s.problem) for s in sites] == [("a", NOT_ALONE_ON_LINE), ("b", NOT_ALONE_ON_LINE)]
    assert sites[0].first_column < sites[1].first_column


def test_block_opening_on_the_same_line_is_not_alone(graph: nx.DiGraph[str]) -> None:
    sites = [s for s in _sites(graph, BLOCK_ON_LINE) if s.operator == "+="]  # "for (...) { a[k] += 1; }"
    assert len(sites) == 1
    assert (sites[0].variable, sites[0].problem) == ("a", NOT_ALONE_ON_LINE)


def test_statement_spanning_two_lines_is_multi_line(graph: nx.DiGraph[str]) -> None:
    site = _only(graph, MULTI_LINE_LINE)  # "a[k] +=" / "v[k];"
    assert site.problem == MULTI_LINE
    assert (site.operator, site.variable) == ("+=", "a")


@pytest.mark.xfail(  # type: ignore[misc]
    reason="ASTGraph attributes a macro expansion to the previous line: clang omits the line of the expansion "
    "location when it equals the last printed one (the macro argument's spelling location, line 68), and the "
    "graph then inherits line 67 (the for header). The site is found on line 67 instead, with problem 'macro'.",
)
def test_macro_expansion_is_reported_with_macro_problem(graph: nx.DiGraph[str]) -> None:
    site = _only(graph, MACRO_LINE)  # ADD(a[k], 1.0);
    assert site.problem == MACRO
    assert site.operator == "+="


def test_template_instantiations_are_one_site(graph: nx.DiGraph[str]) -> None:
    site = _only(graph, TMPL_LINE)  # instantiated for double and float, plus the uninstantiated pattern
    assert site.problem is None
    assert (site.operator, site.variable) == ("+=", "out")
    assert (site.first_column, site.last_column) == (20, 23)


def test_never_instantiated_template_has_dependent_type_problem(graph: nx.DiGraph[str]) -> None:
    site = _only(graph, NEVER_LINE)
    assert site.problem == DEPENDENT_TYPE
    assert (site.operator, site.variable) == ("+=", "out")


def test_std_vector_element_update_names_the_vector(graph: nx.DiGraph[str]) -> None:
    site = _only(graph, VECTOR_LINE)  # v[k] += x[k];
    assert site.problem is None
    assert (site.operator, site.variable) == ("+=", "v")
    assert (site.first_column, site.last_column) == (13, 16)


def test_member_call_lvalue_names_the_object(graph: nx.DiGraph[str]) -> None:
    site = _only(graph, MEMBER_CALL_LINE)  # d.fx(n) += f;
    assert site.problem is None
    assert (site.operator, site.variable) == ("+=", "d")
    assert (site.first_column, site.last_column) == (16, 19)


def test_overloaded_operator_on_class_type_is_no_site(graph: nx.DiGraph[str]) -> None:
    assert _sites(graph, COMPLEX_LINE) == []  # c += z; with std::complex<double>


def test_line_without_update_has_no_sites(graph: nx.DiGraph[str]) -> None:
    assert _sites(graph, NO_UPDATE_LINE) == []


def test_unknown_file_has_no_sites(graph: nx.DiGraph[str]) -> None:
    assert update_sites_on_line(graph, "other.cpp", BASIC_LINE) == []


def _project(tmp_path: Path) -> Path:
    project = tmp_path / ".discopop"
    (project / "profiler").mkdir(parents=True)
    source = tmp_path / SOURCE
    shutil.copy(TESTDATA / SOURCE, source)
    shutil.copy(TESTDATA / "ast.json", project / "profiler" / "ast_dump.json")
    (project / "FileMapping.txt").write_text(f"1\t{source}\n")
    return project


def test_helper_resolves_file_id_and_reports_sites(tmp_path: Path) -> None:
    helper = ASTPatternDetectionHelper()
    helper.load_ast_from_project(str(_project(tmp_path)))
    sites = helper.get_update_sites(1, BASIC_LINE)
    assert len(sites) == 1
    assert (sites[0].operator, sites[0].variable, sites[0].problem) == ("+=", "a", None)
    assert (sites[0].first_column, sites[0].last_column) == (18, 21)
    # memoized: the same tuple again
    assert helper.get_update_sites(1, BASIC_LINE) is sites
    assert helper.get_update_sites(1, NO_UPDATE_LINE) == ()


def test_helper_returns_nothing_for_unknown_file_id(tmp_path: Path) -> None:
    helper = ASTPatternDetectionHelper()
    helper.load_ast_from_project(str(_project(tmp_path)))
    assert helper.get_update_sites(2, BASIC_LINE) == ()


def test_helper_returns_nothing_without_loaded_ast() -> None:
    assert ASTPatternDetectionHelper().get_update_sites(1, BASIC_LINE) == ()


CALLS_FP_LINE, CALLS_VIRTUAL_LINE, CALLS_PLAIN_METHOD_LINE, CALLS_FUNCTION_LINE = 94, 95, 96, 97
MIXED_TEMPLATE_LINE = 102  # a[k] += v; instantiated for double and std::complex<double>


def test_calls_through_a_function_pointer_or_a_virtual_method_are_indirect(graph: nx.DiGraph[str]) -> None:
    facts = file_facts(graph)[SOURCE]
    lines = {line for line, _column in facts.indirect_calls}
    assert CALLS_FP_LINE in lines
    assert CALLS_VIRTUAL_LINE in lines
    assert CALLS_PLAIN_METHOD_LINE not in lines
    assert CALLS_FUNCTION_LINE not in lines


def test_the_references_to_a_variable_are_listed_by_position(graph: nx.DiGraph[str]) -> None:
    references = file_facts(graph)[SOURCE].references["h"]
    assert [line for line, _ in references if CALLS_FP_LINE <= line <= CALLS_FUNCTION_LINE] == [94, 95, 96, 97]
    assert references == sorted(references)


def test_an_instantiation_with_an_overloaded_operator_makes_the_instantiations_differ(
    graph: nx.DiGraph[str],
) -> None:
    assert _only(graph, MIXED_TEMPLATE_LINE).problem == INSTANTIATIONS_DIFFER

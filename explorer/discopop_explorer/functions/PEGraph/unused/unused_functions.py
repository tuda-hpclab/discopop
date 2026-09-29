# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import itertools
from typing import List, Sequence, Set, cast
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Dependency import Dependency
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.variable import Variable
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.functions.PEGraph.properties.is_passed_by_reference import is_passed_by_reference
from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.functions.PEGraph.traversal.parent import get_parent_function


def unused_check_alias(pet: PEGraphX, s: NodeID, t: NodeID, d: Dependency, root_loop: Node) -> bool:
    sub = subtree_of_type(pet, root_loop, CUNode)
    parent_func_sink = get_parent_function(pet, pet.node_at(s))
    parent_func_source = get_parent_function(pet, pet.node_at(t))

    res = False
    d_var_name_str = cast(str, d.var_name)

    if unused_is_global(pet, d_var_name_str, sub) and not (
        is_passed_by_reference(pet, d, parent_func_sink) and is_passed_by_reference(pet, d, parent_func_source)
    ):
        return res
    return not res


def unused_is_global(pet: PEGraphX, var: str, tree: Sequence[Node]) -> bool:
    """Checks if variable is global

    :param var: variable name
    :param tree: nodes to search
    :return: true if global
    """

    for node in tree:
        if isinstance(node, CUNode):
            for gv in node.global_vars:
                if gv.name == var:
                    # TODO from tmp global vars
                    return False
    return False


def unused_get_first_written_vars_in_loop(
    pet: PEGraphX, undefinedVarsInLoop: List[Variable], node: Node, root_loop: Node
) -> Set[Variable]:
    root_children = subtree_of_type(pet, root_loop, CUNode)
    loop_node_ids = [n.id for n in root_children]
    fwVars = set()

    raw = set()
    war = set()
    waw = set()
    sub = root_children
    for sub_node in sub:
        raw.update(pet.get_dep(sub_node, DepType.RAW, False))
        war.update(pet.get_dep(sub_node, DepType.WAR, False))
        waw.update(pet.get_dep(sub_node, DepType.WAW, False))

    for var in undefinedVarsInLoop:
        if var not in fwVars:
            for i in raw:
                if i[2].var_name == var and i[0] in loop_node_ids and i[1] in loop_node_ids:
                    for e in itertools.chain(war, waw):
                        if e[2].var_name == var and e[0] in loop_node_ids and e[1] in loop_node_ids:
                            if e[2].sink_line == i[2].source_line:
                                fwVars.add(var)

    return fwVars


def unused_is_first_written_in_loop(pet: PEGraphX, dep: Dependency, root_loop: Node) -> bool:
    """Checks whether a variable is first written inside the current node

    :param var:
    :param raw_deps: raw dependencies of the loop
    :param war_deps: war dependencies of the loop
    :param reverse_raw_deps:
    :param reverse_war_deps:
    :param tree: subtree of the loop
    :return: true if first written
    """

    result = False
    children = subtree_of_type(pet, root_loop, CUNode)

    for v in children:
        for t, d in [
            (t, d)
            for s, t, d in out_edges(pet, v.id, EdgeType.DATA)
            if d.dtype == DepType.WAR or d.dtype == DepType.WAW
        ]:
            if d.var_name is None:
                return False
            assert d.var_name is not None
            if dep.var_name == d.var_name:
                if dep.source_line == d.sink_line:
                    result = True
                    break
            # None may occur because __get_variables doesn't check for actual elements
    return result

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from __future__ import annotations
from typing import TYPE_CHECKING, Any, List, Tuple, Type, Union, overload

from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.classes.PEGraph.NodeT import NodeT

if TYPE_CHECKING:
    from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX


@overload
def all_nodes(pet: PEGraphX) -> List[Node]: ...


@overload
def all_nodes(pet: PEGraphX, type: Union[Type[NodeT], Tuple[Type[NodeT], ...]]) -> List[NodeT]: ...


def all_nodes(pet: PEGraphX, type: Any = Node) -> List[NodeT]:
    """List of all nodes of specified type

    :param type: type(s) of nodes
    :return: List of all nodes
    """
    return [n[1] for n in pet.g.nodes(data="data") if isinstance(n[1], type)]

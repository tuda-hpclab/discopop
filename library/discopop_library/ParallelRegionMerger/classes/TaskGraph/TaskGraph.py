# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from typing import List, Optional, Tuple, Union, cast
from matplotlib import pyplot as plt
import matplotlib
import networkx as nx  # type: ignore

from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.FunctionNode import FunctionNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_library.ParallelRegionMerger.classes.TaskGraph.CallEdge import CallEdge
from discopop_library.ParallelRegionMerger.classes.TaskGraph.ContainsEdge import ContainsEdge
from discopop_library.ParallelRegionMerger.classes.TaskGraph.DataflowEdge import DataflowEdge
from discopop_library.ParallelRegionMerger.classes.TaskGraph.DoallModifierNode import DoAllModifierNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.Edge import Edge
from discopop_library.ParallelRegionMerger.classes.TaskGraph.EnterParallelNode import EnterParallelNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.ExitParallelNode import ExitParallelNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.FriendlyModifierNode import FriendlyModifierNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.ModifierEdge import ModifierEdge
from discopop_library.ParallelRegionMerger.classes.TaskGraph.ModifierNode import ModifierNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.ParallelRegionConnectionEdge import (
    ParallelRegionConnectionEdge,
)
from discopop_library.ParallelRegionMerger.classes.TaskGraph.ReductionModifierNode import ReductionModifierNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.SuccessorEdge import SuccessorEdge
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TGFunctionNode import TGFunctionNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TGLoopNode import TGLoopNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TGNode import TGNode
from discopop_library.ParallelRegionMerger.classes.TaskGraph.TaskNode import TaskNode
from discopop_explorer.classes.variable import Variable
from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo
from discopop_explorer.pattern_detectors.reduction_detector import ReductionInfo


class TaskGraph(object):
    graph: nx.MultiDiGraph
    node_count: int
    parallel_region_count: int
    pos = None

    def __init__(self) -> None:
        self.graph = nx.MultiDiGraph()
        self.parallel_region_count = 0

    def __get_parallel_region_id(self) -> int:
        buffer = self.parallel_region_count
        self.parallel_region_count += 1
        return buffer

    def add_function_node(self, fn: FunctionNode) -> None:
        self.graph.add_node(TGFunctionNode(fn))

    def add_cu_node(self, cu: CUNode) -> None:
        tn = TaskNode()
        tn.contained_pet_nodes = [cu]
        self.graph.add_node(tn)

    def add_loop_node(self, loop: LoopNode) -> None:
        ln = TGLoopNode()
        ln.contained_pet_nodes = [loop]
        self.graph.add_node(ln)

    def add_reduction_modifier_node(self, base_node: TGNode, reduction_pattern: ReductionInfo) -> None:
        rmn = ReductionModifierNode(reduction_pattern)
        self.graph.add_node(rmn)
        self.add_modifier_edge(rmn, base_node)

    def add_doall_modifier_node(self, base_node: TGNode, doall_pattern: DoAllInfo) -> None:
        damn = DoAllModifierNode(doall_pattern)
        self.graph.add_node(damn)
        self.add_modifier_edge(damn, base_node)

    def add_friendly_modifier(self, base_node_0: TGNode, base_node_1: TGNode, base_node_2: TGNode) -> None:
        fmn = FriendlyModifierNode()
        self.graph.add_node(fmn)
        self.add_modifier_edge(fmn, base_node_0)
        self.add_modifier_edge(fmn, base_node_1)
        self.add_modifier_edge(fmn, base_node_2)

    def add_parallel_region_around(self, base_node: TGNode, shared_vars: List[Variable]) -> None:
        parallel_region_id = self.__get_parallel_region_id()
        enter = EnterParallelNode(
            parallel_region_id, shared_vars, self.get_first_successive_task(base_node), cast(TaskNode, base_node)
        )
        exit = ExitParallelNode(parallel_region_id)
        # redirect incoming edges
        redirect_in_edges: List[Tuple[TGNode, TGNode]] = []
        for in_edges in self.graph.in_edges(base_node):
            for edge_type in self.graph.get_edge_data(in_edges[0], base_node):
                if type(edge_type) == SuccessorEdge:
                    # found incoming successor edge
                    redirect_in_edges.append((in_edges[0], base_node))
        for tpl in list(dict.fromkeys(redirect_in_edges)):
            self.add_successor_edge(tpl[0], enter)
            self.graph.remove_edge(tpl[0], tpl[1])
        # redirect outgoing edges
        redirect_out_edges: List[Tuple[TGNode, TGNode]] = []
        for out_edges in self.graph.out_edges(base_node):
            for edge_type in self.graph.get_edge_data(base_node, out_edges[1]):
                if type(edge_type) == SuccessorEdge:
                    # found outgoing successor edge
                    redirect_out_edges.append((base_node, out_edges[1]))
        for tpl in list(dict.fromkeys(redirect_out_edges)):
            self.add_successor_edge(exit, tpl[1])
            self.graph.remove_edge(tpl[0], tpl[1])
        # connect enter and exit
        self.add_successor_edge(enter, base_node)
        self.add_successor_edge(base_node, exit)
        # connect enter and exit with a ParallelRegionConnectionEdge for faster traversal
        self.graph.add_edge(enter, exit, ParallelRegionConnectionEdge())

    def add_parallel_region_around_nodes(
        self, entry_node: TGNode, exit_node: TGNode, shared_vars: List[Variable]
    ) -> EnterParallelNode:
        parallel_region_id = self.__get_parallel_region_id()

        enter = EnterParallelNode(
            parallel_region_id,
            shared_vars,
            self.get_first_successive_task(entry_node),
            self.get_closest_preceeding_task(exit_node),
        )
        exit = ExitParallelNode(parallel_region_id)
        # redirect incoming edges
        redirect_in_edges: List[Tuple[TGNode, TGNode]] = []
        for in_edges in self.graph.in_edges(entry_node):
            for edge_type in self.graph.get_edge_data(in_edges[0], entry_node):
                if type(edge_type) == SuccessorEdge:
                    # found incoming successor edge
                    redirect_in_edges.append((in_edges[0], entry_node))
        for tpl in list(dict.fromkeys(redirect_in_edges)):
            self.add_successor_edge(tpl[0], enter)
            self.graph.remove_edge(tpl[0], tpl[1])
        # redirect outgoing edges
        redirect_out_edges: List[Tuple[TGNode, TGNode]] = []
        for out_edges in self.graph.out_edges(exit_node):
            for edge_type in self.graph.get_edge_data(exit_node, out_edges[1]):
                if type(edge_type) == SuccessorEdge:
                    # found outgoing successor edge
                    redirect_out_edges.append((exit_node, out_edges[1]))
        for tpl in list(dict.fromkeys(redirect_out_edges)):
            self.add_successor_edge(exit, tpl[1])
            self.graph.remove_edge(tpl[0], tpl[1])
        # connect enter and exit
        self.add_successor_edge(enter, entry_node)
        self.add_successor_edge(exit_node, exit)
        # connect enter and exit with a ParallelRegionConnectionEdge for faster traversal
        self.graph.add_edge(enter, exit, ParallelRegionConnectionEdge())
        return enter

    def add_modifier_edge(self, source: TGNode, target: TGNode) -> None:
        self.graph.add_edge(source, target, ModifierEdge())

    def add_contains_edge(self, source: TGNode, target: TGNode) -> None:
        self.graph.add_edge(source, target, ContainsEdge())

    def add_successor_edge(self, source: TGNode, target: TGNode) -> None:
        self.graph.add_edge(source, target, SuccessorEdge())

    def add_call_edge(self, source: TGNode, target: TGNode) -> None:
        self.graph.add_edge(source, target, CallEdge())

    def add_dataflow_edge(self, source: TGNode, target: TGNode) -> None:
        self.graph.add_edge(source, target, DataflowEdge())

    def has_predecessor(self, base_node: TGNode) -> bool:
        for in_edges in self.graph.in_edges(base_node):
            for edge_type in self.graph.get_edge_data(in_edges[0], base_node):
                if type(edge_type) == SuccessorEdge:
                    return True
        return False

    def has_successor(self, base_node: TGNode) -> bool:
        for out_edges in self.graph.out_edges(base_node):
            for edge_type in self.graph.get_edge_data(base_node, out_edges[1]):
                if type(edge_type) == SuccessorEdge:
                    return True
        return False

    def get_predecessor(self, base_node: TGNode) -> Optional[TGNode]:
        for in_edges in self.graph.in_edges(base_node):
            for edge_type in self.graph.get_edge_data(in_edges[0], base_node):
                if type(edge_type) == SuccessorEdge:
                    return cast(TGNode, in_edges[0])
        return None

    def get_connected_exit(self, base_node: EnterParallelNode) -> Optional[ExitParallelNode]:
        for out_edges in self.graph.out_edges(base_node):
            for edge_type in self.graph.get_edge_data(base_node, out_edges[1]):
                if type(edge_type) == ParallelRegionConnectionEdge:
                    return cast(ExitParallelNode, out_edges[1])
        return None

    def get_connected_entry(self, base_node: ExitParallelNode) -> Optional[EnterParallelNode]:
        for in_edges in self.graph.in_edges(base_node):
            for edge_type in self.graph.get_edge_data(in_edges[0], base_node):
                if type(edge_type) == ParallelRegionConnectionEdge:
                    return cast(EnterParallelNode, in_edges[0])
        return None

    def get_predecessors(self, base_node: TGNode) -> List[TGNode]:
        res: List[TGNode] = []
        for in_edges in self.graph.in_edges(base_node):
            for edge_type in self.graph.get_edge_data(in_edges[0], base_node):
                if type(edge_type) == SuccessorEdge:
                    res.append(in_edges[0])
        return res

    def get_callers(self, base_node: TGNode) -> List[TGNode]:
        res: List[TGNode] = []
        for in_edges in self.graph.in_edges(base_node):
            for edge_type in self.graph.get_edge_data(in_edges[0], base_node):
                if type(edge_type) == CallEdge:
                    res.append(in_edges[0])
        return res

    def get_successors(self, base_node: TGNode) -> List[TGNode]:
        res: List[TGNode] = []
        for out_edges in self.graph.out_edges(base_node):
            for edge_type in self.graph.get_edge_data(base_node, out_edges[1]):
                if type(edge_type) == SuccessorEdge:
                    res.append(out_edges[1])
        return res

    def get_first_successive_task(self, base_node: TGNode) -> TaskNode:
        queue: List[TGNode] = [base_node]
        while queue:
            current = queue.pop()
            if type(current) == TaskNode:
                return current
            queue += self.get_successors(current)
        raise ValueError("No successive Task could be found for base node: ", base_node)

    def get_closest_preceeding_task(self, base_node: TGNode) -> TaskNode:
        queue: List[TGNode] = [base_node]
        while queue:
            current = queue.pop()
            if type(current) == TaskNode:
                return current
            queue += self.get_predecessors(current)
        raise ValueError("No preceeding Task could be found for base node: ", base_node)

    def get_contained(self, base_node: TGNode) -> List[TGNode]:
        res: List[TGNode] = []
        for out_edges in self.graph.out_edges(base_node):
            for edge_type in self.graph.get_edge_data(base_node, out_edges[1]):
                if type(edge_type) == ContainsEdge:
                    res.append(out_edges[1])
        return res

    def get_modifiers(self, base_node: TGNode) -> List[ModifierNode]:
        res: List[ModifierNode] = []
        for in_edges in self.graph.in_edges(base_node):
            for edge_type in self.graph.get_edge_data(in_edges[0], base_node):
                if type(edge_type) == ModifierEdge:
                    res.append(in_edges[0])
        return res

    def get_called(self, base_node: TGNode) -> List[TGNode]:
        res: List[TGNode] = []
        for out_edges in self.graph.out_edges(base_node):
            for edge_type in self.graph.get_edge_data(base_node, out_edges[1]):
                if type(edge_type) == CallEdge:
                    res.append(out_edges[1])
        return res

    def get_parent(self, base_node: TGNode) -> Optional[TGNode]:
        for in_edges in self.graph.in_edges(base_node):
            for edge_type in self.graph.get_edge_data(in_edges[0], base_node):
                if type(edge_type) == ContainsEdge:
                    # found incoming contains edge
                    return cast(TGNode, in_edges[0])
        return None

    def get_dataflow_edges(self) -> List[DataflowEdge]:
        edges: List[DataflowEdge] = []
        for edge in self.graph.edges:
            for edge_type in self.graph.get_edge_data(edge[0], edge[1]):
                if type(edge_type) == DataflowEdge:
                    edges.append(edge)
        return edges

    def get_dataflow_targets(self, base_node: TGNode) -> List[TGNode]:
        res: List[TGNode] = []
        for out_edges in self.graph.out_edges(base_node):
            for edge_type in self.graph.get_edge_data(base_node, out_edges[1]):
                if type(edge_type) == DataflowEdge:
                    res.append(out_edges[1])
        return res

    def get_dataflow_sources(self, base_node: TGNode) -> List[TGNode]:
        res: List[TGNode] = []
        for in_edges in self.graph.in_edges(base_node):
            for edge_type in self.graph.get_edge_data(in_edges[0], base_node):
                if type(edge_type) == DataflowEdge:
                    res.append(in_edges[0])
        return res

    def get_node(self, node: Node) -> Optional[TGNode]:
        for tgn in self.graph.nodes:
            if isinstance(tgn, TGFunctionNode):
                if tgn.fn == node:
                    return tgn
            if not isinstance(tgn, TaskNode):
                continue
            if node in tgn.contained_pet_nodes:
                return tgn
        return None

    def get_all_nodes(self) -> List[TGNode]:
        return cast(List[TGNode], self.graph.nodes)

    def get_first_contained_pet_node(self, base_node: TGNode) -> CUNode:
        queue: List[TGNode] = [base_node]
        visited: List[TGNode] = []
        while queue:
            current = queue.pop(0)
            visited.append(current)
            if isinstance(current, TaskNode) and len(current.contained_pet_nodes) != 0:
                return cast(CUNode, current.contained_pet_nodes[0])
            # due to queue.pop(0), order of traversal is reversed
            # first, check contained nodes, afterwards, check successive nodes
            for succ in self.get_successors(current):
                if succ not in visited and succ not in queue:
                    queue.insert(0, succ)
            for child in self.get_contained(current):
                if child not in visited and child not in queue:
                    queue.insert(0, child)

        raise ValueError("Could not find contained pet node from base_node: " + str(base_node))

    def get_last_contained_pet_node(self, base_node: TGNode) -> CUNode:
        queue: List[TGNode] = [base_node]
        visited: List[TGNode] = []
        candidates: List[CUNode] = []
        while queue:
            current = queue.pop(0)
            visited.append(current)
            if (
                type(current) == TaskNode
                and len(current.contained_pet_nodes) == 1
                and len(self.get_contained(current)) == 0
            ):
                candidates.append(cast(CUNode, current.contained_pet_nodes[0]))
                continue
            # traverse children
            for child in self.get_contained(current):
                if child not in queue and child not in visited:
                    queue.insert(0, child)
        if len(candidates) == 0:
            raise ValueError("Could not find contained pet node from base_node: " + str(base_node))
        # select the last CU Node by LineID
        current_last_cu_node = candidates[0]
        for candidate in candidates:
            if candidate.file_id == current_last_cu_node.file_id:
                if candidate.end_line > current_last_cu_node.end_line:
                    current_last_cu_node = candidate
        return current_last_cu_node

    def get_nodes_contained_in_region(self, epn: Union[TGNode, EnterParallelNode, ExitParallelNode]) -> List[TGNode]:
        res: List[TGNode] = []
        queue: List[TGNode] = []
        outer_parallel_region_id: Optional[int] = None
        if type(epn) == EnterParallelNode or type(epn) == ExitParallelNode:
            outer_parallel_region_id = epn.parallel_region_id
        if type(epn) == ExitParallelNode:
            tmp_entry = self.get_connected_entry(epn)
            if tmp_entry is None:
                return res
            queue.append(tmp_entry)
        else:
            queue.append(epn)

        while queue:
            current = queue.pop()
            if current not in res:
                res.append(current)
            for s in self.get_successors(current):
                if s not in queue and s not in res:
                    if (
                        outer_parallel_region_id is not None
                        and type(s) == ExitParallelNode
                        and s.parallel_region_id == outer_parallel_region_id
                    ):
                        # do not consider nodes past the ExitParallelNode
                        continue
                    queue.append(s)
            for c in self.get_contained(current):
                if c not in queue and c not in res:
                    queue.append(c)
            for f in self.get_called(current):
                if f not in queue and f not in res:
                    queue.append(f)
        return res

    def is_direct_child(self, potential_parent: TGNode, potential_child: TGNode) -> bool:
        """checks if potential_parent is a direct parent of potential_child, i.e. a contained relation exists with no pet node inbetween.
        Empty task nodes are allow as intermediate nodes.
        Returns true, if the relation is valid. False, otherwise."""
        current = potential_child
        while current is not None:
            if current == potential_parent:
                return True
            # stop, if parent has a pet node contained
            if type(current) == TaskNode:
                if len(current.contained_pet_nodes) != 0:
                    return False
            # traverse contains edges upwards, if not PET node is encountered
            parent = self.get_parent(current)
            if parent is None:  # added due to mypy typing
                return False
            current = parent
        return False

    def replace_loops_with_single_tasks(self) -> None:
        queue: List[TGLoopNode] = [n for n in self.graph.nodes if isinstance(n, TGLoopNode)]
        while queue:
            current_loop = queue.pop()
            # check if only tasks are contained. if not, postpone processing
            only_tasks_contained = True
            for out_edge in self.graph.out_edges(current_loop):
                for edge_type in self.graph.get_edge_data(current_loop, out_edge[1]):
                    if type(edge_type) == ContainsEdge:
                        if type(out_edge[1]) != TaskNode:
                            only_tasks_contained = False
                            break

            if not only_tasks_contained:
                queue.append(current_loop)
                continue
            else:
                # create single task node
                tn = TaskNode()
                self.graph.add_node(tn)

                # redirect incoming and outgoing edges
                contained_in_loop: List[TGNode] = [current_loop]
                for out_edge in self.graph.out_edges(current_loop):
                    for edge_type in self.graph.get_edge_data(current_loop, out_edge[1]):
                        if type(edge_type) == ContainsEdge:
                            contained_in_loop.append(out_edge[1])

                for node in contained_in_loop:
                    redirect_in_edges: List[Tuple[TGNode, TGNode]] = []
                    for in_edges in self.graph.in_edges(node):
                        if in_edges[0] not in contained_in_loop:
                            found_incoming = False
                            for edge_type in self.graph.get_edge_data(in_edges[0], node):
                                if type(edge_type) == SuccessorEdge:
                                    # found incoming successor edge
                                    found_incoming = True
                                    break
                            if found_incoming:
                                redirect_in_edges.append((in_edges[0], node))
                    for tpl in redirect_in_edges:
                        self.add_successor_edge(tpl[0], tn)
                        self.graph.remove_edge(tpl[0], tpl[1])

                    redirect_out_edges: List[Tuple[TGNode, TGNode]] = []
                    for out_edges in self.graph.out_edges(node):
                        if out_edges[1] not in contained_in_loop:
                            found_outgoing = False
                            for edge_type in self.graph.get_edge_data(node, out_edges[1]):
                                if type(edge_type) == SuccessorEdge:
                                    # found outgoing successor edge
                                    found_outgoing = True
                                    break
                            if found_outgoing:
                                redirect_out_edges.append((node, out_edges[1]))
                    for tpl in redirect_out_edges:
                        self.add_successor_edge(tn, tpl[1])
                        self.graph.remove_edge(tpl[0], tpl[1])

                    redirect_contains_edges: List[Tuple[TGNode, TGNode]] = []
                    for in_edges in self.graph.in_edges(node):
                        if in_edges[0] not in contained_in_loop:
                            found_incoming = False
                            for edge_type in self.graph.get_edge_data(in_edges[0], node):
                                if type(edge_type) == ContainsEdge:
                                    # found incoming contains edge
                                    found_incoming = True
                                    break
                            if found_incoming:
                                redirect_contains_edges.append((in_edges[0], node))
                    for tpl in redirect_contains_edges:
                        self.add_contains_edge(tpl[0], tn)
                        self.graph.remove_edge(tpl[0], tpl[1])

                # let the loop be contained in the newly created Task only after the redirection step is finished
                self.add_contains_edge(tn, current_loop)

    def dummy(self) -> None:
        pass

    def calculate_plot_positions(self) -> None:
        self.pos = nx.nx_pydot.graphviz_layout(self.graph, prog="sfdp")  # prog="dot")

    def show(self, dataflow: bool = True) -> None:
        """Plots the graph

        :return:
        """
        matplotlib.use("TkAgg")

        if self.pos is None:
            self.calculate_plot_positions()

        plt.plot()  # type: ignore

        # draw nodes
        nx.draw_networkx_nodes(
            self.graph,
            pos=self.pos,
            node_size=200,
            node_color="#2B85FD",
            node_shape="o",
            nodelist=[n for n in self.graph.nodes if isinstance(n, TaskNode)],
        )
        nx.draw_networkx_nodes(
            self.graph,
            pos=self.pos,
            node_size=200,
            node_color="green",
            node_shape="s",
            nodelist=[n for n in self.graph.nodes if isinstance(n, TGFunctionNode)],
        )
        nx.draw_networkx_nodes(
            self.graph,
            pos=self.pos,
            node_size=200,
            node_color="red",
            node_shape="d",
            nodelist=[n for n in self.graph.nodes if isinstance(n, TGLoopNode)],
        )
        nx.draw_networkx_nodes(
            self.graph,
            pos=self.pos,
            node_size=200,
            node_color="yellow",
            node_shape="d",
            nodelist=[n for n in self.graph.nodes if isinstance(n, ModifierNode)],
        )
        nx.draw_networkx_nodes(
            self.graph,
            pos=self.pos,
            node_size=200,
            node_color="yellow",
            node_shape="o",
            nodelist=[n for n in self.graph.nodes if isinstance(n, EnterParallelNode)],
        )
        nx.draw_networkx_nodes(
            self.graph,
            pos=self.pos,
            node_size=200,
            node_color="yellow",
            node_shape="o",
            nodelist=[n for n in self.graph.nodes if isinstance(n, ExitParallelNode)],
        )
        # id as label
        labels = {}
        for n in self.graph.nodes:
            labels[n] = n.get_label()
        nx.draw_networkx_labels(self.graph, self.pos, labels, font_size=7)

        nx.draw_networkx_edges(
            self.graph,
            self.pos,
            edge_color="red",
            edgelist=[e for e in self.graph.edges if type(e[2]) == ContainsEdge],
        )
        nx.draw_networkx_edges(
            self.graph,
            self.pos,
            edge_color="green",
            edgelist=[e for e in self.graph.edges if type(e[2]) == SuccessorEdge],
        )
        nx.draw_networkx_edges(
            self.graph,
            self.pos,
            edge_color="blue",
            edgelist=[e for e in self.graph.edges if type(e[2]) == CallEdge],
        )
        if dataflow:
            nx.draw_networkx_edges(
                self.graph,
                self.pos,
                edge_color="orange",
                style="dashed",
                edgelist=[e for e in self.graph.edges if type(e[2]) == DataflowEdge],
            )
        nx.draw_networkx_edges(
            self.graph,
            self.pos,
            edge_color="yellow",
            edgelist=[e for e in self.graph.edges if type(e[2]) == ModifierEdge],
        )
        nx.draw_networkx_edges(
            self.graph,
            self.pos,
            edge_color="yellow",
            edgelist=[e for e in self.graph.edges if type(e[2]) == ParallelRegionConnectionEdge],
        )

        plt.show()

    def print_to_console(self) -> None:
        print("\n##################")
        print("### TaskGraph: ###")
        print("##################")
        function_nodes: List[TGFunctionNode] = []
        for tgn in self.get_all_nodes():
            if type(tgn) == TGFunctionNode:
                function_nodes.append(tgn)

        for func in function_nodes:
            print()
            queue: List[Tuple[TGNode, int]] = [(func, 0)]
            visited: List[TGNode] = [func]
            while queue:
                current_node, indent = queue.pop(0)
                hook = "├" if self.has_successor(current_node) else "└"
                if indent > 1:
                    prefix = "│   " * (indent - 1) + hook + "─" * 2 + " "
                elif indent == 0:
                    prefix = ""
                else:
                    prefix = hook + "─" * 2 * indent + " "
                modifiers = ""
                for modifier in self.get_modifiers(current_node):
                    if type(modifier) == FriendlyModifierNode and (
                        isinstance(current_node, EnterParallelNode) or isinstance(current_node, ExitParallelNode)
                    ):
                        continue
                    modifiers += " " + modifier.get_label()

                print(prefix + str(type(current_node).__name__) + ": " + current_node.get_label() + modifiers)

                # first traverse called, then contained, then successors due to queue.pop(0)
                for succ in self.get_successors(current_node):
                    if succ in visited:
                        continue
                    queue.insert(0, (succ, indent))
                    visited.append(succ)
                seen_child = False
                required_add_random_child = True
                for child in self.get_contained(current_node):
                    seen_child = True
                    if child in visited:
                        continue
                    # select entry to successor sequence
                    if len(self.get_predecessors(child)) != 0:
                        continue
                    queue.insert(0, (child, indent + 1))
                    visited.append(child)
                    required_add_random_child = False
                if seen_child and required_add_random_child:
                    # select the child with the lowest line id

                    children = self.get_contained(current_node)
                    children_first_pet_nodes = [self.get_first_contained_pet_node(c) for c in children]
                    children_first_lines = [p.start_line for p in children_first_pet_nodes]
                    children_with_lines = [(children[idx], children_first_lines[idx]) for idx, c in enumerate(children)]
                    sorted_children_with_lines = sorted(children_with_lines, key=lambda x: x[1])
                    selected_child = sorted_children_with_lines[0][0]
                    if selected_child not in visited:
                        queue.insert(0, (selected_child, indent + 1))
                        visited.append(selected_child)

                for called in self.get_called(current_node):
                    if called not in visited:
                        queue.insert(0, (called, indent + 1))
                        visited.append(called)
        print()

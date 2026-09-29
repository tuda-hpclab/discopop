# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Set, Optional, cast, Dict, Tuple

from discopop_explorer.classes.PEGraph.PEGraphX import (
    PEGraphX,
)
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.classes.PEGraph.Node import Node
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.NodeType import NodeType
from discopop_explorer.enums.DepType import DepType
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.classes.variable import Variable
from discopop_explorer.functions.PEGraph.queries.edges import in_edges, out_edges
from discopop_explorer.functions.PEGraph.queries.subtree import subtree_of_type
from discopop_explorer.functions.PEGraph.traversal.children import direct_children
from discopop_explorer.pattern_detectors.simple_gpu_patterns.GPULoop import GPULoopPattern
from discopop_explorer.pattern_detectors.simple_gpu_patterns.GPUMemory import map_node
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_library.StatusReporting.console import progress


class GPURegionInfo(PatternInfo):
    """Class, that represents an identified GPU Region"""

    contained_loops: List[GPULoopPattern]
    contained_cu_ids: List[NodeID]
    map_from_vars: List[str]
    map_to_vars: List[str]
    map_to_from_vars: List[str]
    map_alloc_vars: List[str]
    map_delete_vars: List[str]
    produced_vars: List[str]
    consumed_vars: List[str]
    project_folder_path: str

    def __init__(
        self,
        pet: PEGraphX,
        contained_loops: List[GPULoopPattern],
        contained_cu_ids: List[NodeID],
        map_to_vars: List[str],
        map_from_vars: List[str],
        map_to_from_vars: List[str],
        map_alloc_vars: List[str],
        map_delete_vars: List[str],
        produced_vars: List[str],
        consumed_vars: List[str],
        project_folder_path: str,
    ):
        node_id = sorted([loop.nodeID for loop in contained_loops])[0]
        PatternInfo.__init__(self, pet.node_at(node_id))
        self.contained_loops = contained_loops
        self.contained_cu_ids = contained_cu_ids
        self.map_to_vars = map_to_vars
        self.map_from_vars = map_from_vars
        self.map_to_from_vars = map_to_from_vars
        self.map_alloc_vars = map_alloc_vars
        self.map_delete_vars = map_delete_vars
        self.produced_vars = produced_vars
        self.consumed_vars = consumed_vars
        self.start_line = min([l.start_line for l in contained_loops])
        self.end_line = max([l.end_line for l in contained_loops])
        self.project_folder_path = project_folder_path

    def __str__(self) -> str:
        raise NotImplementedError()  # used to identify necessity to call to_string() instead

    def to_string(self, pet: PEGraphX) -> str:
        contained_loops_str = "\n" if len(self.contained_loops) > 0 else ""
        for loop in self.contained_loops:
            loop_str = loop.to_string(pet)
            # pretty printing
            loop_str = "".join(["\t" + s + "\n" for s in loop_str.split("\n")])
            contained_loops_str += loop_str

        return (
            f"GPU Region at: {self.node_id}\n"
            f"Start line: {self.start_line}\n"
            f"End line: {self.end_line}\n"
            f"Map to: {self.map_to_vars}\n"
            f"Map from: {self.map_from_vars}\n"
            f"Map to/from: {self.map_to_from_vars}\n"
            f"Map alloc: {self.map_alloc_vars}\n"
            f"Map delete: {self.map_delete_vars}\n"
            f"Contained patterns: {contained_loops_str}\n"
        )

    def get_entry_cus(self, pet: PEGraphX) -> List[str]:
        """returns a list of contained cus with predecessors outside the GPU Region,
        i.e. entry points into the region"""
        entry_cus: List[str] = []
        for contained_cu_id in self.contained_cu_ids:
            # check if contained_cu has only predecessors inside the gpu region
            for predecessor_id, _, _ in in_edges(pet, contained_cu_id, EdgeType.SUCCESSOR):
                if predecessor_id not in self.contained_cu_ids:
                    # found entry node
                    entry_cus.append(contained_cu_id)
        # remove duplicates
        entry_cus = list(dict.fromkeys(entry_cus))
        return entry_cus

    def get_exit_cus(self, pet: PEGraphX) -> Tuple[List[str], List[str]]:
        """returns a list of contained cus with successors outside the GPU Region,
        i.e. exit points of the region. as well as a list of their successors, i.e. the nodes after the region
        """
        contained_exit_cus: List[str] = []
        outside_cus: List[str] = []
        for contained_cu_id in self.contained_cu_ids:
            # check if contained_cu_id has only successors inside the gpu region
            for _, successor_id, _ in out_edges(pet, contained_cu_id, EdgeType.SUCCESSOR):
                if successor_id not in self.contained_cu_ids:
                    # found exit node
                    contained_exit_cus.append(contained_cu_id)
                    outside_cus.append(successor_id)
        # remove duplicates
        contained_exit_cus = list(dict.fromkeys(contained_exit_cus))
        outside_cus = list(dict.fromkeys(outside_cus))
        return contained_exit_cus, outside_cus


class GPURegions:
    cascadingLoopsInRegions: List[List[NodeID]]
    gpu_loop_patterns: List[GPULoopPattern]
    loopsInRegion: List[str]
    pet: PEGraphX
    numRegions: int
    cu_ids_by_region: Dict[Tuple[NodeID, ...], List[NodeID]]
    map_type_from_by_region: Dict[Tuple[str, ...], List[str]]
    map_type_to_by_region: Dict[Tuple[str, ...], List[str]]
    map_type_tofrom_by_region: Dict[Tuple[str, ...], List[str]]
    map_type_alloc_by_region: Dict[Tuple[str, ...], List[str]]
    map_type_delete_by_region: Dict[Tuple[str, ...], List[str]]
    produced_vars: Dict[Tuple[str, ...], List[str]]
    consumed_vars: Dict[Tuple[str, ...], List[str]]
    project_folder_path: str

    def __init__(self, pet: PEGraphX, gpu_patterns: List[GPULoopPattern], project_folder_path: str):
        self.loopsInRegion = []
        self.gpu_loop_patterns = gpu_patterns
        self.project_folder_path = project_folder_path
        self.cascadingLoopsInRegions = [[]]
        self.numRegions = 0
        self.pet = pet
        self.cu_ids_by_region = dict()
        self.map_type_from_by_region = dict()
        self.map_type_to_by_region = dict()
        self.map_type_tofrom_by_region = dict()
        self.map_type_alloc_by_region = dict()
        self.map_type_delete_by_region = dict()
        self.produced_vars = dict()  # includes implicitly mapped variables as well
        self.consumed_vars = dict()  # includes implicitly mapped variables as well

    def findGPULoop(self, nodeID: str) -> Optional[GPULoopPattern]:
        """

        :param nodeID:
        :return:
        """
        for i in self.gpu_loop_patterns:
            if i.node_id == nodeID:
                return i
        return None

    def reachableCUs(self, cuID: NodeID, nextCUID: NodeID) -> bool:
        """

        :param cuID:
        :param nextCUID:
        :return:
        """
        loop: LoopNode = cast(LoopNode, map_node(self.pet, cuID))
        nextLoop: LoopNode = cast(LoopNode, map_node(self.pet, nextCUID))

        # next loop is not a loop!
        if nextLoop.type != 2:
            return False

        loopFirstChild: Node = direct_children(self.pet, loop)[0]
        CUIDsofLoop = out_edges(self.pet, loopFirstChild.id, EdgeType.SUCCESSOR)
        lastCUofLoop = map_node(self.pet, CUIDsofLoop[-1][1])
        nextLoopFirstChild: Node = direct_children(self.pet, nextLoop)[0]
        successors = out_edges(self.pet, lastCUofLoop.id, EdgeType.SUCCESSOR)
        if successors:
            if nextLoopFirstChild.id == successors[0][1]:
                return True
            else:
                return False
        return False

    def identifyGPURegions(self) -> None:
        """

        :return:
        """
        regionNum = 0
        # find the next loop of each loop in the source code
        self.findNextLoop()

        self.cascadingLoopsInRegions[regionNum].append(self.gpu_loop_patterns[0].nodeID)
        for i in progress(range(0, len(self.gpu_loop_patterns)), desc="Identifying cascading loops"):
            if self.gpu_loop_patterns[i].nextLoop is not None:
                if map_node(self.pet, cast(NodeID, self.gpu_loop_patterns[i].nextLoop)).type == 2:
                    if self.reachableCUs(
                        self.gpu_loop_patterns[i].nodeID,
                        cast(NodeID, self.gpu_loop_patterns[i].nextLoop),
                    ):
                        self.cascadingLoopsInRegions[regionNum].append(cast(NodeID, self.gpu_loop_patterns[i].nextLoop))
                    else:
                        regionNum += 1
                        self.cascadingLoopsInRegions.append([])
                        self.cascadingLoopsInRegions[regionNum].append(cast(NodeID, self.gpu_loop_patterns[i].nextLoop))

        self.numRegions = regionNum + 1

    def determineDataMapping(self) -> None:
        """determine data mapping for each GPU Region and their contained GPU Loops."""

        for region in progress(self.cascadingLoopsInRegions, desc="Determining data mapping"):
            # determine CUs which belong to the region (= which are located inside the region)
            region_cus: List[Node] = []
            region_loop_patterns: List[GPULoopPattern] = []
            for loop_id in region:
                loop_node: LoopNode = cast(LoopNode, self.pet.node_at(loop_id))
                gpu_lp: GPULoopPattern = [p for p in self.gpu_loop_patterns if p.parentLoop == loop_id][0]
                region_loop_patterns.append(gpu_lp)
                region_cus += [cu for cu in subtree_of_type(self.pet, loop_node) if cu not in region_cus]
                # add loop initialization to region cus (predecessor of first child of loop, if positions are suitable)
                loop_entry_cu = out_edges(self.pet, loop_id, EdgeType.CHILD)[0][1]
                predecessors = [s for s, t, d in in_edges(self.pet, loop_entry_cu, EdgeType.SUCCESSOR)]
                for predecessor_id in predecessors:
                    predecessor_node = self.pet.node_at(predecessor_id)
                    if (
                        predecessor_node.start_line >= loop_node.start_line
                        and predecessor_node.end_line <= loop_node.end_line
                    ):
                        # predecessor is loop initialization
                        if predecessor_node not in region_cus:
                            region_cus.append(predecessor_node)

            self.cu_ids_by_region[tuple(region)] = [n.id for n in region_cus]

            # determine start and end line of region
            region_start_line = min([cu.start_line for cu in region_cus])
            region_end_line = max([cu.end_line for cu in region_cus])

            # determine variables which are written outside the region and read inside
            consumed_vars: List[str] = []
            for cu in region_cus:
                in_dep_edges = out_edges(self.pet, cu.id, EdgeType.DATA)

                # var is consumed, if incoming RAW dep exists
                for sink_cu_id, source_cu_id, dep in in_dep_edges:
                    # unpack dep for sake of clarity
                    sink_line = dep.sink_line
                    source_line = dep.source_line
                    var_name = dep.var_name

                    if self.pet.node_at(source_cu_id) not in region_cus:
                        if dep.dtype == DepType.RAW:
                            if dep.var_name not in consumed_vars and dep.var_name is not None:
                                consumed_vars.append(dep.var_name)

            # determine variables which are read afterwards and written in the region
            produced_vars: List[str] = []
            for cu in region_cus:
                out_dep_edges = in_edges(self.pet, cu.id, EdgeType.DATA)
                # var is produced, if outgoing RAW or WAW dep exists
                for sink_cu_id, source_cu_id, dep in out_dep_edges:
                    # unpack dep for sake of clarity
                    sink_line = dep.sink_line
                    source_line = dep.source_line
                    var_name = dep.var_name
                    if self.pet.node_at(sink_cu_id) not in region_cus:
                        if dep.dtype in [DepType.RAW, DepType.WAW]:
                            if dep.var_name not in produced_vars and dep.var_name is not None:
                                produced_vars.append(dep.var_name)

            # gather consumed, produced, allocated and deleted variables from mapping information
            map_to_vars: List[str] = []
            for loop_pattern in region_loop_patterns:
                map_to_vars += [v.name for v in loop_pattern.map_type_to + loop_pattern.map_type_tofrom]
            map_to_vars = list(dict.fromkeys(map_to_vars))

            map_from_vars: List[str] = []
            for loop_pattern in region_loop_patterns:
                map_from_vars += [v.name for v in loop_pattern.map_type_from + loop_pattern.map_type_tofrom]
            map_from_vars = list(dict.fromkeys(map_from_vars))

            map_alloc_vars: List[str] = []
            for loop_pattern in region_loop_patterns:
                map_alloc_vars += [v.name for v in loop_pattern.map_type_alloc]
            map_alloc_vars = list(dict.fromkeys(map_alloc_vars))

            map_to_from_vars = [var for var in map_to_vars if var in map_from_vars]

            # allocate unknown variables
            map_alloc_vars += [var for var in map_from_vars if var not in consumed_vars + map_to_vars + map_alloc_vars]
            map_alloc_vars = list(dict.fromkeys(map_alloc_vars))

            # store results
            self.map_type_from_by_region[tuple(region)] = [var for var in map_from_vars if var not in map_to_from_vars]
            self.map_type_to_by_region[tuple(region)] = [var for var in map_to_vars if var not in map_to_from_vars]
            self.map_type_tofrom_by_region[tuple(region)] = map_to_from_vars
            self.map_type_alloc_by_region[tuple(region)] = map_alloc_vars
            self.map_type_delete_by_region[tuple(region)] = []
            self.produced_vars[tuple(region)] = produced_vars
            self.consumed_vars[tuple(region)] = consumed_vars

    def old_mapData(self) -> None:
        """
        :return:
        """

        for i in range(0, self.numRegions):
            for j in self.cascadingLoopsInRegions[i]:
                gpuLoop = self.findGPULoop(j)
                if gpuLoop is None:
                    continue
                gpuLoop.printGPULoop()
        print(f"==============================================")
        for i in range(0, self.numRegions):
            t: int = len(self.cascadingLoopsInRegions[i]) - 1
            firstNodeID = self.cascadingLoopsInRegions[i][0]
            lastNodeID = self.cascadingLoopsInRegions[i][t]
            fn = map_node(self.pet, firstNodeID)
            ln = map_node(self.pet, lastNodeID)
            start = fn.start_position()
            end = ln.end_position()
            gpuRegionLoop = GPULoopPattern(self.pet, firstNodeID, start, end, 1000, self.project_folder_path)
            visitedVars: Set[Variable] = set()
            while t >= 0:
                loopIter = self.findGPULoop(
                    self.cascadingLoopsInRegions[i][t]
                )  # tmp_result contains GPU loops inside the parent region

                if loopIter is None:
                    t -= 1
                    continue

                varis: Set[Variable] = set([])
                varis.update(loopIter.map_type_alloc)
                varis.update(loopIter.map_type_to)
                varis.update(loopIter.map_type_from)
                varis.update(loopIter.map_type_tofrom)
                # loopIter.printGPULoop()
                for v in varis:
                    if loopIter.findMappedVar("from", v):
                        if v in visitedVars:
                            if gpuRegionLoop.findMappedVar("to", v):
                                # // cout << "gpuRegionLoop to: " << get_var_name(v) << endl;
                                gpuRegionLoop.map_type_to.remove(v)
                                # gpuRegionLoop.map_type_to.erase(remove(gpuRegionLoop.map_type_to.begin(),
                                #                                       gpuRegionLoop.map_type_to.end(), v),
                                #                                gpuRegionLoop.map_type_to.end())
                                gpuRegionLoop.map_type_alloc.append(v)
                                visitedVars.add(v)
                            else:
                                gpuRegionLoop.map_type_from.append(v)
                                visitedVars.add(v)
                        else:
                            # // cout << "visited from: " << get_var_name(v) << endl;
                            gpuRegionLoop.map_type_from.append(v)
                            visitedVars.add(v)
                    elif loopIter.findMappedVar("to", v):
                        if v in visitedVars:
                            # // cout << "loopIter to: " << get_var_name(v) << endl;
                            if gpuRegionLoop.findMappedVar("alloc", v):
                                # // cout << "gpuRegionLoop alloc: " << get_var_name(v) << endl;
                                gpuRegionLoop.map_type_alloc.remove(v)

                                gpuRegionLoop.map_type_to.append(v)
                                visitedVars.add(v)
                        else:
                            # // cout << "visited to: " << get_var_name(v) << endl;
                            gpuRegionLoop.map_type_to.append(v)
                            visitedVars.add(v)
                    elif loopIter.findMappedVar("tofrom", v):
                        if v not in visitedVars:
                            # // cout << "loopIter tofrom: " << get_var_name(v) << endl;
                            gpuRegionLoop.map_type_tofrom.append(v)
                            visitedVars.add(v)
                        else:
                            if gpuRegionLoop.findMappedVar("to", v):
                                gpuRegionLoop.map_type_to.remove(v)
                                gpuRegionLoop.map_type_alloc.append(v)
                            elif gpuRegionLoop.findMappedVar("from", v):
                                gpuRegionLoop.map_type_from.remove(v)
                                gpuRegionLoop.map_type_tofrom.append(v)
                    elif loopIter.findMappedVar("alloc", v):
                        if v not in visitedVars:
                            gpuRegionLoop.map_type_alloc.append(v)
                            visitedVars.add(v)
                t -= 1

            # gpuRegionLoop.printGPULoop()  # only prints first loop of the region.
            # first loop of the region is used to store the map_to behavior
            # last loop if the region should be used to store the map_from behavior

    def findNextLoop(self) -> None:
        """

        :return:
        """

        i: int = 0
        while i < len(self.gpu_loop_patterns):
            skip: int = i
            for k in self.gpu_loop_patterns[skip].nestedLoops:
                """To find the next loop for a loop,
                we need to skip over the nested loops in the identified GPU loops.
                Also, some loops may not be do-all or reduction
                and not listed in the gpu_loop_patterns. We need to skip them
                Create a dummy GPULoopPattern and
                search for the gpu loops with the same NodeID
                """
                dd = GPULoopPattern(
                    self.pet,
                    k,
                    self.gpu_loop_patterns[skip].start_line,
                    self.gpu_loop_patterns[skip].end_line,
                    self.gpu_loop_patterns[skip].iteration_count,
                    self.project_folder_path,
                )
                for ii in self.gpu_loop_patterns:
                    if dd.nodeID == ii.nodeID:  # TODO: check remaining attributes too
                        i += 1

            if (i + 1) < len(self.gpu_loop_patterns):
                self.gpu_loop_patterns[skip].nextLoop = self.gpu_loop_patterns[i + 1].node_id

            i += 1

    def getParentLoop(self, node: CUNode) -> bool:
        """

        :param node:
        :return:
        """
        main: Node = self.pet.main
        path: List[Node] = self.pet.path(map_node(self.pet, main.id), node)
        path.reverse()

        for parent in path:
            if not parent.id == node.id and parent.type == NodeType.LOOP:
                return True
        return False

    def get_gpu_region_info(self, pet: PEGraphX, project_folder_path: str) -> List[GPURegionInfo]:
        """Construct GPURegionInfo representations of all identified GPU Regions and return them in a list"""
        gpu_region_info: List[GPURegionInfo] = []
        for region in progress(self.cascadingLoopsInRegions, desc="Getting GPU region info"):
            contained_loop_patterns = [pattern for pattern in self.gpu_loop_patterns if pattern.nodeID in region]
            # save OpenMP constructs in GPULoops for the exporting to JSON
            for loop in contained_loop_patterns:
                loop.save_omp_constructs(pet, project_folder_path)
            device_cu_ids = self.cu_ids_by_region[tuple(region)]
            for loop in contained_loop_patterns:
                for func_node_id in loop.called_functions:
                    for child in direct_children(pet, pet.node_at(func_node_id)):
                        device_cu_ids.append(child.id)

            device_cu_ids = list(dict.fromkeys(device_cu_ids))
            current_info = GPURegionInfo(
                self.pet,
                contained_loop_patterns,
                device_cu_ids,
                self.map_type_to_by_region[tuple(region)],
                self.map_type_from_by_region[tuple(region)],
                self.map_type_tofrom_by_region[tuple(region)],
                self.map_type_alloc_by_region[tuple(region)],
                self.map_type_delete_by_region[tuple(region)],
                self.produced_vars[tuple(region)],
                self.consumed_vars[tuple(region)],
                project_folder_path,
            )
            gpu_region_info.append(current_info)
        return gpu_region_info

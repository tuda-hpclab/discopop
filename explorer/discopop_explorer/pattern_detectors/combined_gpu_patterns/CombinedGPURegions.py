# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import sys
from typing import List, Tuple, Dict, Set, cast

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.CUNode import CUNode
from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_explorer.aliases.NodeID import NodeID
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.functions.PEGraph.properties.check_reachability import check_reachability
from discopop_explorer.functions.PEGraph.traversal.children import direct_children
from discopop_explorer.functions.PEGraph.traversal.successors import direct_successors
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import (
    VarName,
)
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Dependency import Dependency
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.EntryPoint import EntryPoint
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Enums import (
    ExitPointPositioning,
    EntryPointPositioning,
    ExitPointType,
    EntryPointType,
    UpdateType,
)
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.ExitPoint import ExitPoint
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Update import Update
from discopop_explorer.pattern_detectors.combined_gpu_patterns.prepare_metadata import (
    get_dependencies_as_metadata,
)
from discopop_explorer.pattern_detectors.combined_gpu_patterns.step_1 import (
    get_written_and_read_memory_regions_by_cu,
    get_cu_and_varname_to_memory_regions,
    get_memory_region_to_cu_and_variables_dict,
)
from discopop_explorer.pattern_detectors.combined_gpu_patterns.step_2 import (
    populate_live_data,
    add_memory_regions_to_device_liveness,
    propagate_memory_regions,
    convert_liveness,
    calculate_host_liveness,
)
from discopop_explorer.pattern_detectors.combined_gpu_patterns.step_3 import (
    initialize_writes,
    cleanup_writes,
    group_writes_by_cu,
)
from discopop_explorer.pattern_detectors.combined_gpu_patterns.step_4 import (
    create_circle_free_function_graphs,
    add_accesses_from_called_functions,
    identify_updates_in_unrolled_function_graphs,
)
from discopop_explorer.pattern_detectors.combined_gpu_patterns.step_5 import (
    propagate_variable_name_associations,
)
from discopop_explorer.pattern_detectors.combined_gpu_patterns.step_6 import (
    convert_updates_to_entry_and_exit_points,
    identify_end_of_life_points,
    add_aliases,
    extend_region_liveness_using_unrolled_functions,
    join_entryPoint_elements,
    join_exitPoint_elements,
    join_update_elements,
    remove_duplicates,
)
from discopop_explorer.pattern_detectors.simple_gpu_patterns.GPURegions import GPURegionInfo


class CombinedGPURegion(PatternInfo):
    contained_regions: List[GPURegionInfo]
    update_instructions: List[
        Tuple[NodeID, NodeID, UpdateType, str, str]
    ]  # (source_cu_id, sink_cu_id, UpdateType, target_vars, meta_line_num)
    target_data_regions: Dict[str, List[Tuple[List[NodeID], NodeID, NodeID, str, str]]]
    # {var: ([contained cu_s], entry_cu, exit_after_cu, meta_entry_line_num, meta_exit_line_num)
    data_region_entry_points: List[
        Tuple[str, NodeID, NodeID, EntryPointType, str, EntryPointPositioning]
    ]  # [(var, cu_id, entry_point_type, meta_line_num, positioning)]
    data_region_exit_points: List[
        Tuple[str, NodeID, NodeID, ExitPointType, str, ExitPointPositioning]
    ]  # [(var, cu_id, exit_point_type, meta_line_num, positioning)]
    data_region_depend_in: List[Tuple[VarName, NodeID, str]]  # [(var, cu_id, meta_line_num)]
    data_region_depend_out: List[Tuple[VarName, NodeID, str]]  # [(var, cu_id, meta_line_num)]
    device_cu_ids: List[NodeID]
    # meta information, mainly for display and overview purposes
    meta_device_lines: List[str]
    meta_host_lines: List[str]
    meta_device_liveness: Dict[MemoryRegion, List[str]]
    meta_host_liveness: Dict[MemoryRegion, List[str]]
    project_folder_path: str

    def __init__(self, pet: PEGraphX, contained_regions: List[GPURegionInfo], project_folder_path: str):
        self.project_folder_path = project_folder_path
        node_id = sorted([region.node_id for region in contained_regions])[0]
        device_cu_ids: List[NodeID] = []
        for region in contained_regions:
            device_cu_ids += [NodeID(cu_id_str) for cu_id_str in region.contained_cu_ids]
            device_cu_ids = list(dict.fromkeys(device_cu_ids))
        PatternInfo.__init__(self, pet.node_at(node_id))
        self.contained_regions = contained_regions
        self.device_cu_ids = device_cu_ids
        self.start_line = min(
            [l.start_line for l in contained_regions]
        )  # todo: not correct anymore since multiple files contained now
        self.end_line = max(
            [l.end_line for l in contained_regions]
        )  # todo: not correct anymore since multiple files contained now
        print("\n\n", file=sys.stderr)
        print("DEVICE CU IDS: ", file=sys.stderr)
        print(self.device_cu_ids, file=sys.stderr)

        # initialize object
        self.update_instructions = []
        self.data_region_entry_points = []
        self.data_region_exit_points = []
        self.data_region_depend_in = []
        self.data_region_depend_out = []
        self.meta_device_liveness: Dict[MemoryRegion, List[str]] = dict()
        self.meta_host_liveness: Dict[MemoryRegion, List[str]] = dict()
        self.meta_host_lines: Dict[VarName, List[str]]

        # ### STEP 1: INITIALIZATION
        # get written and read memory regions by CU
        written_memory_regions_by_cu: Dict[NodeID, Set[MemoryRegion]]
        read_memory_regions_by_cu: Dict[NodeID, Set[MemoryRegion]]
        (
            written_memory_regions_by_cu,
            read_memory_regions_by_cu,
        ) = get_written_and_read_memory_regions_by_cu(self.contained_regions, pet)

        # get memory region and variable associations for each CU
        cu_and_variable_to_memory_regions: Dict[NodeID, Dict[VarName, Set[MemoryRegion]]] = (
            get_cu_and_varname_to_memory_regions(self.contained_regions, pet, written_memory_regions_by_cu)
        )

        print("WRITTEN MEMORY REGIONS BY CU: ", file=sys.stderr)
        print(written_memory_regions_by_cu, file=sys.stderr)
        print(file=sys.stderr)

        print("READ MEMORY REGIONS BY CU: ", file=sys.stderr)
        print(read_memory_regions_by_cu, file=sys.stderr)
        print(file=sys.stderr)

        # get memory regions to cus and variables names
        memory_regions_to_cus_and_variables: Dict[MemoryRegion, Dict[NodeID, Set[VarName]]] = (
            get_memory_region_to_cu_and_variables_dict(cu_and_variable_to_memory_regions)
        )
        print("MEMORY REGIONS TO CUS AND VARIABLES:", file=sys.stderr)
        print(memory_regions_to_cus_and_variables, file=sys.stderr)
        print(file=sys.stderr)

        # ### STEP 2.1: INITIALIZE LIVE DATA USING MAPPING CLAUSES AND CONVERSION TO MEMORY REGIONS
        live_device_variables = populate_live_data(self, pet, ignore_update_instructions=True)
        print("LIVE DEVICE VARIABLES:", file=sys.stderr)
        print(live_device_variables, file=sys.stderr)
        print(file=sys.stderr)

        # extend device liveness with memory regions
        device_liveness_plus_memory_regions: Dict[VarName, List[Tuple[NodeID, Set[MemoryRegion]]]] = (
            add_memory_regions_to_device_liveness(live_device_variables, cu_and_variable_to_memory_regions)
        )

        # ### STEP 2.2: CALCULATE LIVE DATA BY PROPAGATING MEMORY REGIONS AND EXTENDING LIFESPAN

        # propagate memory regions
        device_liveness_plus_memory_regions = propagate_memory_regions(device_liveness_plus_memory_regions)

        print("PROPAGATED DEVICE VARIABLES + MEMORY:", file=sys.stderr)
        print(device_liveness_plus_memory_regions, file=sys.stderr)
        print(file=sys.stderr)

        # convert liveness to memory regions as basis
        memory_region_liveness = convert_liveness(device_liveness_plus_memory_regions)
        print("CONVERTED DEVICE MEMORY REGION LIVENESS:", file=sys.stderr)
        print(memory_region_liveness, file=sys.stderr)
        print(file=sys.stderr)

        # extend data liveness
        extended_memory_region_liveness = memory_region_liveness  # extend_data_lifespan(pet, memory_region_liveness)

        print("EXTENDED DEVICE MEMORY REGION LIVENESS:", file=sys.stderr)
        print(extended_memory_region_liveness, file=sys.stderr)
        print(file=sys.stderr)

        # ### STEP 2.3: CALCULATE HOST LIVENESS
        host_liveness = calculate_host_liveness(self, pet)
        print("HOST LIVENESS:", file=sys.stderr)
        print(host_liveness, file=sys.stderr)
        print(file=sys.stderr)
        host_memory_region_liveness = convert_liveness(host_liveness)
        extended_host_memory_region_liveness = (
            host_memory_region_liveness  # extend_data_lifespan(           pet, host_memory_region_liveness        )
        )
        print("EXTENDED HOST MEMORY REGION LIVENESS:", file=sys.stderr)
        print(extended_host_memory_region_liveness, file=sys.stderr)
        print(file=sys.stderr)

        # ### STEP 3: MARK WRITTEN VARIABLES
        # initialize writes
        device_writes = initialize_writes(extended_memory_region_liveness, written_memory_regions_by_cu)
        host_writes = initialize_writes(extended_host_memory_region_liveness, written_memory_regions_by_cu)

        # propagate writes to parents, successors and the children of successors
        propagated_device_writes = device_writes  # propagate_writes(self, pet, device_writes)
        print("PROPAGATED DEVICE WRITES:", file=sys.stderr)
        print(propagated_device_writes, file=sys.stderr)
        print(file=sys.stderr)

        propagated_host_writes = host_writes  # propagate_writes(self, pet, host_writes)
        print("PROPAGATED HOST WRITES:", file=sys.stderr)
        print(propagated_host_writes, file=sys.stderr)
        print(file=sys.stderr)

        # cleanup propagated writes (remove None entries if they are overwritten by at least one write)
        propagated_device_writes = cleanup_writes(propagated_device_writes)
        propagated_host_writes = cleanup_writes(propagated_host_writes)
        print("CLEANED HOST WRITES:", file=sys.stderr)
        print(propagated_host_writes, file=sys.stderr)
        print(file=sys.stderr)

        # group by cus
        device_writes_by_cu = group_writes_by_cu(propagated_device_writes)
        print("DEVICE WRITES BY CU:", file=sys.stderr)
        print(device_writes_by_cu, file=sys.stderr)
        print(file=sys.stderr)

        host_writes_by_cu = group_writes_by_cu(propagated_host_writes)
        print("HOST WRITES BY CU:", file=sys.stderr)
        print(host_writes_by_cu, file=sys.stderr)
        print(file=sys.stderr)

        # ### STEP 4: IDENTIFY SYNCHRONOUS UPDATE POINTS
        writes_by_device = {0: host_writes_by_cu, 1: device_writes_by_cu}

        # unroll function bodies to create circle-free graphs
        unrolled_function_graphs = create_circle_free_function_graphs(pet, add_dummy_node=False)
        # TODO add accesses from called function to the calling CUs
        writes_by_device = add_accesses_from_called_functions(
            pet, writes_by_device, force_called_functions_to_host=True
        )

        # identify updates based on the circle-free graph
        # TODO parallelize on function level

        # issued_updates = identify_updates(self, pet, writes_by_device)  # old code
        issued_updates = identify_updates_in_unrolled_function_graphs(
            self, pet, writes_by_device, unrolled_function_graphs
        )

        print("ISSUED UPDATES:", file=sys.stderr)
        for update in issued_updates:
            print(update, file=sys.stderr)
        print(file=sys.stderr)

        # remove dummy marks from CU ID's created during loop unrolling
        for update in issued_updates:
            update.remove_dummy_marks()

        # ### STEP 5: CONVERT MEMORY REGIONS IN UPDATES TO VARIABLE NAMES
        # propagate memory region to variable name associations within function body
        memory_regions_to_functions_and_variables: Dict[MemoryRegion, Dict[NodeID, Set[VarName]]] = (
            propagate_variable_name_associations(pet, memory_regions_to_cus_and_variables)
        )
        print("MEMORY REGIONS TO FUNCTIONS AND VARIABLES:", file=sys.stderr)
        print(memory_regions_to_functions_and_variables, file=sys.stderr)
        print(file=sys.stderr)

        # determine variable name for memory regions in update instructions
        for update in issued_updates:
            update.convert_memory_regions_to_variable_names(pet, memory_regions_to_functions_and_variables)

        # ### POTENTIAL STEP 6: CONVERT MEMORY REGIONS TO STRUCTURE INDICES

        # ### STEP 6: convert updates to entry / exit points if possible

        # extend memory region liveness based on unrolled function graphs
        extended_memory_region_liveness = extend_region_liveness_using_unrolled_functions(
            pet, extended_memory_region_liveness, unrolled_function_graphs
        )
        extended_host_memory_region_liveness = extend_region_liveness_using_unrolled_functions(
            pet, extended_host_memory_region_liveness, unrolled_function_graphs
        )

        # add aliases to updates
        aliased_updates = add_aliases(
            pet,
            issued_updates,
            memory_regions_to_functions_and_variables,
        )

        memory_region_liveness_by_device = {
            0: extended_host_memory_region_liveness,
            1: extended_memory_region_liveness,
        }
        entry_points, exit_points, updates = convert_updates_to_entry_and_exit_points(
            pet, aliased_updates, memory_region_liveness_by_device
        )

        # identify exit points
        exit_points.update(
            identify_end_of_life_points(
                pet,
                entry_points,
                exit_points,
                memory_region_liveness_by_device,
                memory_regions_to_functions_and_variables,
            )
        )

        # remove duplicates
        updates = cast(Set[Update], remove_duplicates(updates))
        entry_points = cast(Set[EntryPoint], remove_duplicates(entry_points))
        exit_points = cast(Set[ExitPoint], remove_duplicates(exit_points))

        # join entries
        updates = join_update_elements(updates)
        entry_points = join_entryPoint_elements(entry_points)
        exit_points = join_exitPoint_elements(exit_points)

        # ### PREPARE METADATA
        # prepare device liveness
        #        self.meta_device_liveness = prepare_liveness_metadata(
        #            pet,
        #            extended_memory_region_liveness,
        #            propagated_device_writes,
        #            self.meta_device_liveness,
        #        )
        # prepare host liveness
        #        self.meta_host_liveness = prepare_liveness_metadata(
        #            pet,
        #            extended_host_memory_region_liveness,
        #            propagated_host_writes,
        #            self.meta_host_liveness,
        #        )
        # prepare update instructions
        self.update_instructions = [
            update.get_as_metadata_using_variable_names(pet, self.project_folder_path) for update in updates
        ]
        # prepare entry points
        self.data_region_entry_points = [
            entry_point.get_as_metadata(pet, self.project_folder_path) for entry_point in entry_points
        ]

        # prepare exit points
        self.data_region_exit_points = [
            exit_point.get_as_metadata(pet, self.project_folder_path) for exit_point in exit_points
        ]

        # prepare dependencies
        all_dependencies: Set[Dependency] = set()
        for update in updates:
            all_dependencies.update(update.dependencies)
        for entry_point in entry_points:
            all_dependencies.update(entry_point.dependencies)
        for exit_point in exit_points:
            all_dependencies.update(exit_point.dependencies)

        self.data_region_depend_in, self.data_region_depend_out = get_dependencies_as_metadata(pet, all_dependencies)

    def __str__(self) -> str:
        raise NotImplementedError()  # used to identify necessity to call to_string() instead

    def to_string(self, pet: PEGraphX) -> str:
        contained_regions_str = "\n" if len(self.contained_regions) > 0 else ""
        for region in self.contained_regions:
            region_str = region.to_string(pet)
            # pretty printing
            region_str = "".join(["\t" + s + "\n" for s in region_str.split("\n")])
            contained_regions_str += region_str

        return (
            f"COMBINED GPU Region at: {self.node_id}\n"
            f"Start line: {self.start_line}\n"
            f"End line: {self.end_line}\n"
            f"Device CUs: {self.device_cu_ids}\n"
            f"Device lines: {self.meta_device_lines}\n"
            f"Host lines: {self.meta_host_lines}\n"
            f"Contained regions: {contained_regions_str}\n"
        )


def find_combined_gpu_regions(
    pet: PEGraphX, gpu_regions: List[GPURegionInfo], project_folder_path: str
) -> List[CombinedGPURegion]:
    # create combined gpu regions from original gpu regions
    combined_gpu_regions = []
    for gpu_region in gpu_regions:
        combined_gpu_regions.append(CombinedGPURegion(pet, [gpu_region], project_folder_path))

    # determine relations between single-element regions
    combinable_pairs: List[Tuple[CombinedGPURegion, CombinedGPURegion]] = find_all_pairwise_gpu_region_combinations(
        combined_gpu_regions, pet
    )

    intra_function_combinations = find_combinations_within_function_body(pet, combinable_pairs)

    true_successor_combinations = find_true_successor_combinations(pet, intra_function_combinations)

    # combine regions
    for combinable_1, combinable_2 in intra_function_combinations:  # true_successor_combinations:
        if combinable_1 in combined_gpu_regions:
            combined_gpu_regions.remove(combinable_1)
        if combinable_2 in combined_gpu_regions:
            combined_gpu_regions.remove(combinable_2)
        combined_gpu_regions.append(combine_regions(pet, combinable_1, combinable_2, project_folder_path))

    #    # combine all known regions
    #    combined_region: Optional[CombinedGPURegion] = None
    #    for cgr in combined_gpu_regions:
    #        if combined_region is None:
    #            combined_region = cgr
    #        else:
    #            combined_region = combine_regions(pet, combined_region, cgr, project_folder_path)

    #    if combined_region is None:
    #        return []
    #    else:
    #        return [combined_region]

    return combined_gpu_regions


def find_all_pairwise_gpu_region_combinations(
    gpu_regions: List[CombinedGPURegion], pet: PEGraphX
) -> List[Tuple[CombinedGPURegion, CombinedGPURegion]]:
    combinable_pairs: List[Tuple[CombinedGPURegion, CombinedGPURegion]] = []  # [(region1, region2)
    # get all pairwise combinations of gpu regions
    for gpu_region_1 in gpu_regions:
        for gpu_region_2 in gpu_regions:
            if gpu_region_1 == gpu_region_2:
                continue
            combinable_pairs.append((gpu_region_1, gpu_region_2))
    return combinable_pairs


def find_combinations_within_function_body(
    pet: PEGraphX, combinable_pairs: List[Tuple[CombinedGPURegion, CombinedGPURegion]]
) -> List[Tuple[CombinedGPURegion, CombinedGPURegion]]:
    """Check regions pairwise for reachability via successor edges.
    Only combinations within a function's body are possible in this way since successor edges only exist
    for function body's."""
    result = []
    for region_1, region_2 in combinable_pairs:
        if region_1 == region_2:
            continue
        # check reachability in both directions via successor edges
        # consider children, as loop nodes do not have successors on their own
        for region_1_child in direct_children(pet, pet.node_at(region_1.contained_regions[0].node_id)):
            for region_2_child in direct_children(pet, pet.node_at(region_2.contained_regions[0].node_id)):
                if region_1_child == region_2_child:
                    continue
                if check_reachability(pet, region_2_child, region_1_child, [EdgeType.SUCCESSOR]):
                    result.append((region_1, region_2))
                elif check_reachability(pet, region_1_child, region_2_child, [EdgeType.SUCCESSOR]):
                    result.append((region_2, region_1))
    # remove duplicates (deterministic ordering not relevant, hence list(set(..)) is fine)
    result = list(set(result))
    return result


def find_true_successor_combinations(
    pet: PEGraphX, intra_function_combinations: List[Tuple[CombinedGPURegion, CombinedGPURegion]]
) -> List[Tuple[CombinedGPURegion, CombinedGPURegion]]:
    """Check for combinations options without branching inbetween.
    As a result, both regions will always be executed in succession."""
    result = []
    # a successor path between region_1 and region_2 must exist.
    # a true successor relation exists, if every successor path outgoing from any child of region_1 arrives at region_2
    for region_1, region_2 in intra_function_combinations:
        true_successors = True
        queue: List[CUNode] = cast(
            List[CUNode], direct_children(pet, pet.node_at(region_1.contained_regions[0].node_id))
        )
        visited: List[CUNode] = []
        while queue:
            current_node: CUNode = queue.pop()
            visited.append(current_node)
            if current_node in direct_children(pet, pet.node_at(region_2.contained_regions[0].node_id)):
                # reached region_2
                continue
            # region_2 not reached
            successors = direct_successors(pet, current_node)
            if len(successors) == 0:
                # end of the function body reached, region_2 not reached
                true_successors = False
                break
            else:
                # end of the function's body not yet reached, continue searching
                # add successors to queue
                queue += [cast(CUNode, succ) for succ in successors if succ not in visited]
        if true_successors:
            result.append((region_1, region_2))
    return result


def combine_regions(
    pet: PEGraphX,
    region_1: CombinedGPURegion,
    region_2: CombinedGPURegion,
    project_folder_path: str,
) -> CombinedGPURegion:
    """Combines regions. Individual contained regions are not yet merged!
    Analysis of Live-data and necessary update pragmas needs ti happen in a subsequent step."""
    combined_region = CombinedGPURegion(
        pet, region_1.contained_regions + region_2.contained_regions, project_folder_path
    )
    return combined_region

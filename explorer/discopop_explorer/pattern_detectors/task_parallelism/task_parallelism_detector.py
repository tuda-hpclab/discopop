# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


from typing import Dict, List, Optional, Tuple, cast

from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.DummyNode import DummyNode
from discopop_explorer.enums.MWType import MWType
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.functions.PEGraph.traversal.children import direct_children_or_called_nodes
from discopop_explorer.utilities.PEGraphConstruction.parser import parse_inputs
from discopop_explorer.classes.patterns.PatternInfo import PatternInfo
from discopop_explorer.pattern_detectors.do_all_detector import run_detection as detect_do_all
from discopop_explorer.pattern_detectors.reduction_detector import ReductionInfo, run_detection as detect_reduction
from discopop_explorer.pattern_detectors.task_parallelism.classes import (
    TaskParallelismInfo,
    TPIType,
)
from discopop_explorer.pattern_detectors.task_parallelism.filter import (
    filter_data_sharing_clauses,
    remove_useless_barrier_suggestions,
    remove_duplicate_data_sharing_clauses,
    filter_data_depend_clauses,
    remove_duplicates,
)
from discopop_explorer.pattern_detectors.task_parallelism.postprocessor import (
    group_task_suggestions,
    sort_output,
)
from discopop_explorer.pattern_detectors.task_parallelism.preprocessor import (
    cu_xml_preprocessing,
    check_loop_scopes,
)
from discopop_explorer.pattern_detectors.task_parallelism.suggesters.auxiliary import (
    suggest_parallel_regions,
    set_task_contained_lines,
    detect_taskloop_reduction,
    combine_omittable_cus,
)
from discopop_explorer.pattern_detectors.task_parallelism.suggesters.barriers import (
    detect_barrier_suggestions,
    suggest_barriers_for_uncovered_tasks_before_return,
    validate_barriers,
    suggest_missing_barriers_for_global_vars,
)
from discopop_explorer.pattern_detectors.task_parallelism.suggesters.data_sharing_clauses import (
    suggest_shared_clauses_for_all_tasks_in_function_body,
)
from discopop_explorer.pattern_detectors.task_parallelism.suggesters.dependency_clauses import (
    detect_dependency_clauses_alias_based,
)
from discopop_explorer.pattern_detectors.task_parallelism.suggesters.tasks import (
    detect_task_suggestions,
    correct_task_suggestions_in_loop_body,
)
from discopop_explorer.pattern_detectors.task_parallelism.tp_utils import (
    create_task_tree,
    __forks,
    set_global_llvm_cxxfilt_path,
    detect_mw_types,
    get_var_definition_line_dict,
)
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType

__global_llvm_cxxfilt_path: str = ""


def build_preprocessed_graph_and_run_detection(
    cu_xml: str,
    dep_file: str,
    reduction_file: str,
    file_mapping: str,
    cu_inst_result_file: str,
    llvm_cxxfilt_path: Optional[str],
    discopop_build_path: Optional[str],
    hotspots: Optional[Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]],
    reduction_info: List[ReductionInfo],
) -> List[PatternInfo]:
    """execute preprocessing of given cu xml file and construct a new cu graph.
    execute run_detection on newly constructed graph afterwards.
    :param cu_xml: Path (string) to the CU xml file to be used
    :param dep_file: Path (string) to the dependence file to be used
    :param loop_counter_file: Path (string) to the loop counter file file to be used
    :param reduction_file: Path (string) to the reduction file to be used
    :param file_mapping: Path (string) to the FileMapping.txt to be used
    :param cu_inst_result_file: Path (string) to the _CUInstResult.txt to be used
    :param llvm_cxxfilt_path: Path (string) to the llvm-cxxfilt executable to be used or None.
    :param discopop_build_path: path (string) to discopop build folder.
    :return: List of detected pattern info
    """
    global __global_llvm_cxxfilt_path
    if llvm_cxxfilt_path is None:
        __global_llvm_cxxfilt_path = "None"
    else:
        __global_llvm_cxxfilt_path = llvm_cxxfilt_path
    if discopop_build_path is None or discopop_build_path == "None":
        raise ValueError("Path to DiscoPoP build directory not specified!")
    set_global_llvm_cxxfilt_path(__global_llvm_cxxfilt_path)
    preprocessed_cu_xml = cu_xml_preprocessing(cu_xml)
    preprocessed_graph = PEGraphX.from_parsed_input(
        *parse_inputs(preprocessed_cu_xml, dep_file, reduction_file, file_mapping)  # type: ignore
    )

    # execute reduction detector to enable taskloop-reduction-detection
    detect_reduction(preprocessed_graph, hotspots)
    detect_do_all(preprocessed_graph, hotspots, reduction_info)

    suggestions = run_detection(
        preprocessed_graph,
        preprocessed_cu_xml,
        file_mapping,
        dep_file,
        cu_inst_result_file,
        discopop_build_path,
    )

    return suggestions


def run_detection(
    pet: PEGraphX,
    cu_xml: str,
    file_mapping: str,
    dep_file: str,
    cu_ist_result_file: str,
    discopop_build_path: str,
) -> List[PatternInfo]:
    """Computes the Task Parallelism Pattern for a node:
    (Automatic Parallel Pattern Detection in the Algorithm Structure Design Space p.46)
    1.) first merge all children of the node -> all children nodes get the dependencies
        of their children nodes and the list of the children nodes (saved in node.childrenNodes)
    2.) To detect Task Parallelism, we use Breadth First Search (BFS)
        a.) the hotspot becomes a fork
        b.) all child nodes become first worker if they are not marked as worker before
        c.) if a child has dependence to more than one parent node, it will be marked as barrier
    3.) if two barriers can run in parallel they are marked as barrierWorkers.
        Two barriers can run in parallel if there is not a directed path from one to the other
        :param pet: PET graph
        :param cu_xml: Path (string) to the CU xml file to be used
        :param file_mapping: Path (string) to the FileMapping.txt to be used
        :param dep_file: Path (string) to the dependencies-file to be used
        :param cu_ist_result_file: Path(string) to the CUInstResult.txt
        :param discopop_build_path: path to discopop build folder
        :return: List of detected pattern info
    """
    result: List[PatternInfo] = []

    for node in all_nodes(pet):
        if isinstance(node, DummyNode):
            continue
        if direct_children_or_called_nodes(pet, node):
            detect_mw_types(pet, node)

        if node.mw_type == MWType.NONE:
            node.mw_type = MWType.ROOT

    __forks.clear()
    create_task_tree(pet, pet.main)

    fs = [f for f in __forks if f.node_id == "130:0"]

    for fork in fs:
        if fork.child_tasks:
            result.append(
                TaskParallelismInfo(fork.nodes[0], TPIType.DUMMY, ["dummy_fork"], fork.start_line, [], [], [])
            )
    # Preprocessing
    check_loop_scopes(pet)
    # Suggestion generation
    result += detect_task_suggestions(pet)
    result += suggest_parallel_regions(pet, cast(List[TaskParallelismInfo], result))
    result = cast(List[PatternInfo], set_task_contained_lines(cast(List[TaskParallelismInfo], result)))
    result = cast(List[PatternInfo], detect_taskloop_reduction(pet, cast(List[TaskParallelismInfo], result)))
    result = cast(
        List[PatternInfo],
        remove_useless_barrier_suggestions(pet, cast(List[TaskParallelismInfo], result)),
    )
    result = detect_barrier_suggestions(pet, result)
    result = validate_barriers(pet, result)
    result = detect_dependency_clauses_alias_based(
        pet, result, file_mapping, cu_xml, dep_file, cu_ist_result_file, discopop_build_path
    )
    result = suggest_missing_barriers_for_global_vars(pet, result)
    result = combine_omittable_cus(pet, result)
    result = suggest_barriers_for_uncovered_tasks_before_return(pet, result)
    result = suggest_shared_clauses_for_all_tasks_in_function_body(pet, result)
    result = remove_duplicates(result)
    result = correct_task_suggestions_in_loop_body(pet, result)
    result = filter_data_sharing_clauses(pet, result, get_var_definition_line_dict(cu_xml))
    result = filter_data_depend_clauses(pet, result, get_var_definition_line_dict(cu_xml))
    result = remove_duplicate_data_sharing_clauses(result)
    result = group_task_suggestions(pet, result)
    result = sort_output(result)

    return result

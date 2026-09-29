# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
import json
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple, cast

from discopop_explorer.classes.TaskGraph.TaskGraph import TaskGraph
from discopop_explorer.utilities.ASTUtils import ASTPatternDetectionHelper
from discopop_explorer.functions.PEGraph.queries.edges import out_edges
from discopop_explorer.functions.PEGraph.queries.nodes import all_nodes
from discopop_explorer.pattern_detectors.combined_gpu_patterns.classes.Aliases import VarName
from discopop_explorer.pattern_detectors.task_parallelism.task_parallelism_detector import (
    build_preprocessed_graph_and_run_detection as detect_tp,
)
from discopop_explorer.classes.variable import Variable
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.JSONHandler.JSONHandler import read_patterns_from_json_to_json
from discopop_library.result_classes.DetectionResult import DetectionResult
from discopop_library.StatusReporting.console import banner, stage
from discopop_explorer.classes.PEGraph.PEGraphX import PEGraphX
from discopop_explorer.classes.PEGraph.DummyNode import DummyNode
from discopop_explorer.classes.PEGraph.LoopNode import LoopNode
from discopop_explorer.enums.EdgeType import EdgeType
from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo, run_detection as detect_do_all
from discopop_explorer.pattern_detectors.geometric_decomposition_detector import run_detection as detect_gd
from discopop_explorer.pattern_detectors.pipeline_detector import run_detection as detect_pipeline
from discopop_explorer.pattern_detectors.reduction_detector import ReductionInfo, run_detection as detect_reduction
from discopop_explorer.pattern_detectors.simple_gpu_patterns.gpu_pattern_detector import run_detection as detect_gpu
from discopop_library.ParallelRegionMerger.inflated_parallel_region_pattern import (
    run_detection as detect_inflated_parallel_regions,
)
from discopop_explorer.pattern_detectors.new_task_detector import run_detection as detect_tasking
from discopop_explorer.pattern_detectors.new_do_all_detector import run_detection as detect_do_all_and_reduction_new

try:
    from discopop_gui.Visualizers.Base import Base as Visualizer
except (ImportError, ModuleNotFoundError):
    Visualizer = object  # type: ignore[assignment, misc]


class PatternDetectorX(object):
    pet: PEGraphX
    ast_helper: ASTPatternDetectionHelper

    def __init__(self, pet_graph: PEGraphX) -> None:
        """This class runs detection algorithms on CU graph

        :param pet_graph: CU graph
        """
        self.pet = pet_graph
        self.ast_helper = ASTPatternDetectionHelper()

    def __merge(self, loop_type: bool, remove_dummies: bool) -> None:
        """Removes dummy nodes

        :param loop_type: loops only
        :param remove_dummies: remove dummy nodes
        """
        dummies_to_remove = set()
        for node in all_nodes(self.pet):
            if not loop_type or isinstance(node, LoopNode):
                if remove_dummies and isinstance(node, DummyNode):
                    continue
                for s, t, e in out_edges(self.pet, node.id, [EdgeType.CHILD, EdgeType.CALLSNODE]):
                    if remove_dummies and isinstance(self.pet.node_at(t), DummyNode):
                        dummies_to_remove.add(t)

        for n in dummies_to_remove:
            self.pet.g.remove_node(n)

    def detect_patterns(
        self,
        project_path: str,
        cu_dict: str,
        dependencies: str,
        loop_data: str,
        reduction_vars: str,
        file_mapping: Optional[str],
        cu_inst_result_file: Optional[str],
        llvm_cxxfilt_path: Optional[str],
        discopop_build_path: Optional[str],
        enable_patterns: str,
        enable_task_pattern: bool,
        enable_detection_of_scheduling_clauses: bool,
        hotspots: Optional[Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]],
        jobs: Optional[int],
        enable_task_graph_plot: bool,
        enable_context_graph_plot: bool,
        visualizer: Visualizer | None = None,
        ignore_dependency_states: bool = False,
    ) -> DetectionResult:
        """Runs pattern discovery on the CU graph"""
        with stage("Loading AST"):
            self.ast_helper.load_ast_from_project(project_path)
        # self.ast_helper.print_ast_structure()
        # These five passes prepare the PET graph and used to run without any progress output,
        # which made them invisible in the timing breakdown - on larger inputs they dominate
        # pattern detection.
        with stage("Merging CU nodes", 1, total=5):
            self.__merge(False, True)
        with stage("Mapping static and dynamic dependencies", 2, total=5):
            self.pet.map_static_and_dynamic_dependencies()
        with stage("Calculating function metadata", 3, total=5):
            self.pet.calculateFunctionMetadata(hotspots)
        with stage("Calculating loop metadata", 4, total=5):
            self.pet.calculateLoopMetadata()
        with stage("Enforcing single function exit nodes", 5, total=5):
            self.pet.enforce_single_function_exit_node()
        res = DetectionResult(self.pet)

        # create TaskGraph from pet
        dynamic_deps_file = dependencies
        static_deps_file = os.path.join(Path(dependencies).parent, "static_dependencies.txt")
        with stage("Constructing TaskGraph"):
            task_graph = TaskGraph(
                self.pet,
                dynamic_deps_file,
                static_deps_file,
                visualizer,
                ignore_dependency_states=ignore_dependency_states,
            )
        if enable_task_graph_plot:
            task_graph.plot()
        #        if enable_context_graph_plot:
        #            task_graph.plot_context_graph(plt.gca())

        # detect parallel tasks
        if "*" in enable_patterns or "task" in enable_patterns:
            res.patterns.task = detect_tasking(self.pet, task_graph, visualizer)

        if "*" in enable_patterns or "doall" in enable_patterns or "reduction" in enable_patterns:
            tmp_result = detect_do_all_and_reduction_new(self.pet, task_graph, self.ast_helper)
            if "*" in enable_patterns or "doall" in enable_patterns:
                res.patterns.do_all = [p for p in tmp_result if isinstance(p, DoAllInfo)]
            if "*" in enable_patterns or "reduction" in enable_patterns:
                res.patterns.reduction = [p for p in tmp_result if isinstance(p, ReductionInfo)]

        # reduction before doall!

        #        if "*" in enable_patterns or "reduction" in enable_patterns:
        #            print("REDUCTIONS...")
        #            res.patterns.reduction = detect_reduction(self.pet, hotspots, jobs)
        #            print("\tDONE.")
        #        if "*" in enable_patterns or "doall" in enable_patterns:
        #            print("DOALL...")
        #            res.patterns.do_all = detect_do_all(self.pet, hotspots, res.patterns.reduction, jobs)
        #            print("\tDONE.")
        #        if "*" in enable_patterns or "pipeline" in enable_patterns:
        #            print("PIPELINE...")
        #            res.patterns.pipeline = detect_pipeline(self.pet, hotspots)
        #            print("\tDONE.")
        #        if "*" in enable_patterns or "geodec" in enable_patterns:
        #            print("GEO. DEC...")
        #            res.patterns.geometric_decomposition = detect_gd(self.pet, hotspots)
        #            print("\tDONE.")

        # check if task pattern should be enabled
        #        if enable_task_pattern:
        #            if cu_inst_result_file is None:
        #                raise ValueError("cu_inst_result_file not specified.")
        #            if file_mapping is None:
        #                raise ValueError("file_mapping not specified.")
        #            res.patterns.task = detect_tp(
        #                cu_dict,
        #                dependencies,
        #                reduction_vars,
        #                file_mapping,
        #                cu_inst_result_file,
        #                llvm_cxxfilt_path,
        #                discopop_build_path,
        #                hotspots,
        #                res.patterns.reduction,
        #            )
        #
        #       # detect GPU patterns based on previously identified patterns
        #       if "*" in enable_patterns or "simplegpu" in enable_patterns:
        #           print("SIMPLE GPU...")
        #           res.patterns.simple_gpu = detect_gpu(self.pet, res, project_path)
        #           print("\tDONE.")
        #
        # detect combined GPU patterns
        # disabled currently due to high additional overhead.
        # will be moved and calculated based on the optimization graph
        # res.combined_gpu = detect_combined_gpu(self.pet, res, project_folder_path)

        #        if enable_detection_of_scheduling_clauses:
        # identify scheduling clauses
        #            return self.__identify_scheduling_clauses(res, project_path, file_mapping)

        return res

    # todo: re-enable identification of scheduling clauses
    #   def __identify_scheduling_clauses(
    #       self,
    #       res: DetectionResult,
    #       project_folder_path: str,
    #       file_mapping_path: str,
    #   ) -> DetectionResult:
    #       """Identifies scheduling clauses for suggestions and returns the updated DetectionResult"""
    #       # construct optimization graph (basically an acyclic representation of the PET)
    #       system = System()
    #       discopop_output_path = project_folder_path
    #       discopop_optimizer_path = "INVALID_DUMMY"
    #       code_export_path = "INVALID_DUMMY"
    #       arguments_1 = {"--compile-command": "make"}
    #       experiment = Experiment(
    #           project_folder_path,
    #           discopop_output_path,
    #           discopop_optimizer_path,
    #           code_export_path,
    #           file_mapping_path,
    #           system,
    #           res,
    #           arguments_1,
    #       )
    #       arguments_2 = {"--exhaustive-search": False, "--headless-mode": True}
    #       optimization_graph = OptimizationGraph(project_folder_path, experiment, arguments_2, None, False)
    #
    #        for do_all_suggestion in res.do_all:
    #            for node_id in get_nodes_from_cu_id(experiment.optimization_graph, do_all_suggestion.node_id):
    #                workload_delta, min_workload, max_workload = get_workload_delta_for_cu_node(experiment, node_id)
    #                print(
    #                    "DOALL @ ",
    #                    do_all_suggestion.node_id,
    #                    " -> ",
    #                    "node_id: ",
    #                    node_id,
    #                    " --> Delta WL: ",
    #                    workload_delta,
    #                    " (",
    #                    min_workload,
    #                    "/",
    #                    max_workload,
    #                    ")",
    #                    file=sys.stderr,
    #                )
    #                # todo
    #                #  very naive and non-robust approach, needs improvement in the future
    #                #  reflects the behavior as described in https://dl.acm.org/doi/pdf/10.1145/3330345.3330375
    #                if workload_delta != 0:
    #                    do_all_suggestion.scheduling_clause = "dynamic"
    #
    #        return res

    def load_existing_doall_and_reduction_patterns(
        self,
        project_path: str,
        cu_dict: str,
        dependencies: str,
        loop_data: str,
        reduction_vars: str,
        file_mapping: Optional[str],
        cu_inst_result_file: Optional[str],
        llvm_cxxfilt_path: Optional[str],
        discopop_build_path: Optional[str],
        enable_patterns: str,
        enable_task_pattern: bool,
        enable_detection_of_scheduling_clauses: bool,
        hotspots: Optional[Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]],
    ) -> DetectionResult:
        """skips the pattern discovery on the CU graph and loads a pre-existing pattern file"""
        self.__merge(False, True)
        self.pet.map_static_and_dynamic_dependencies()
        self.pet.calculateFunctionMetadata(hotspots)
        self.pet.calculateLoopMetadata()
        res = DetectionResult(self.pet)

        # init pattern lists
        res.patterns.reduction = []
        res.patterns.do_all = []
        res.patterns.pipeline = []
        res.patterns.geometric_decomposition = []
        res.patterns.task = []
        res.patterns.simple_gpu = []
        res.patterns.combined_gpu = []
        res.patterns.optimizer_output = []
        res.patterns.merged_pattern = []

        if not os.path.exists(os.path.join("explorer", "patterns.json")):
            raise FileNotFoundError(os.path.join("explorer", "patterns.json"))

        pattern_contents = read_patterns_from_json_to_json(
            os.path.join("explorer", "patterns.json"), ["do_all", "reduction"]
        )
        banner("Loaded existing patterns")
        print(pattern_contents)

        def __get_var_obj_from_name(name: VarName) -> Variable:
            return Variable(type="", name=name, defLine="", accessMode="", sizeInByte=0)

        def __get_red_var_obj_from_name(name: str) -> Variable:
            split_name = name.split(":")
            v = Variable(type="", name=VarName(split_name[0]), defLine="", accessMode="", sizeInByte=0)
            v.operation = split_name[1]
            return v

        # unpack do_all
        for pattern_json_str in pattern_contents["do_all"]:
            pattern_dict = json.loads(pattern_json_str)
            pt = DoAllInfo(self.pet, self.pet.node_at(pattern_dict["node_id"]))
            # patternBase
            pt.pattern_id = pattern_dict["pattern_id"]
            pt.node_id = pattern_dict["node_id"]
            pt.start_line = pattern_dict["start_line"]
            pt.end_line = pattern_dict["end_line"]
            pt.applicable_pattern = pattern_dict["applicable_pattern"]
            # patternInfo
            pt.iterations_count = pattern_dict["iterations_count"]
            pt.average_iteration_count = pattern_dict["average_iteration_count"]
            pt.entries = pattern_dict["entries"]
            pt.workload = pattern_dict["workload"]
            pt.per_iteration_workload = pattern_dict["per_iteration_workload"]
            pt.device_id = pattern_dict["device_id"]
            pt.device_type = pattern_dict["device_type"]
            # doall specific
            pt.first_private = [__get_var_obj_from_name(v) for v in pattern_dict["first_private"]]
            pt.private = [__get_var_obj_from_name(v) for v in pattern_dict["private"]]
            pt.last_private = [__get_var_obj_from_name(v) for v in pattern_dict["last_private"]]
            pt.shared = [__get_var_obj_from_name(v) for v in pattern_dict["shared"]]
            pt.reduction = [__get_red_var_obj_from_name(v) for v in pattern_dict["reduction"]]
            pt.scheduling_clause = pattern_dict["scheduling_clause"]
            pt.collapse_level = pattern_dict["collapse_level"]
            # absent in pattern files written before the loop collapse analysis was introduced
            pt.collapsed_pattern_ids = pattern_dict.get("collapsed_pattern_ids", [])
            res.patterns.do_all.append(pt)

        # unpack reduction
        for pattern_json_str in pattern_contents["reduction"]:
            pattern_dict = json.loads(pattern_json_str)
            pt = DoAllInfo(self.pet, self.pet.node_at(pattern_dict["node_id"]))
            # patternBase
            pt.pattern_id = pattern_dict["pattern_id"]
            pt.node_id = pattern_dict["node_id"]
            pt.start_line = pattern_dict["start_line"]
            pt.end_line = pattern_dict["end_line"]
            pt.applicable_pattern = pattern_dict["applicable_pattern"]
            # patternInfo
            pt.iterations_count = pattern_dict["iterations_count"]
            pt.average_iteration_count = pattern_dict["average_iteration_count"]
            pt.entries = pattern_dict["entries"]
            pt.workload = pattern_dict["workload"]
            pt.per_iteration_workload = pattern_dict["per_iteration_workload"]
            pt.device_id = pattern_dict["device_id"]
            pt.device_type = pattern_dict["device_type"]
            # reduction specific
            pt.first_private = [__get_var_obj_from_name(v) for v in pattern_dict["first_private"]]
            pt.private = [__get_var_obj_from_name(v) for v in pattern_dict["private"]]
            pt.last_private = [__get_var_obj_from_name(v) for v in pattern_dict["last_private"]]
            pt.shared = [__get_var_obj_from_name(v) for v in pattern_dict["shared"]]
            pt.reduction = [__get_red_var_obj_from_name(v) for v in pattern_dict["reduction"]]
            res.patterns.reduction.append(cast(ReductionInfo, pt))

        return res

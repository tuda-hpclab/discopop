# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
from cProfile import Profile
import os
from pathlib import Path
from typing import Dict, Tuple, Set, Optional, List, Any

import networkx as nx  # type: ignore
from sympy import Integer, Symbol, Expr, Float  # type: ignore

from discopop_explorer.aliases.MemoryRegion import MemoryRegion
from discopop_library.HostpotLoader.HotspotType import HotspotType
from discopop_library.MemoryRegions.utils import get_sizes_of_memory_regions
from discopop_library.PathManagement.PathManagement import load_file_mapping
from discopop_library.discopop_optimizer.OptimizerArguments import OptimizerArguments
from discopop_library.discopop_optimizer.classes.enums.Distributions import FreeSymbolDistribution

from discopop_library.discopop_optimizer.classes.context.ContextObject import ContextObject
from discopop_library.HostpotLoader.HotspotNodeType import HotspotNodeType
from discopop_library.discopop_optimizer.CostModels.CostModel import CostModel
from discopop_library.discopop_optimizer.classes.nodes.FunctionRoot import FunctionRoot
from discopop_library.result_classes.DetectionResult import DetectionResult
from discopop_library.discopop_optimizer.classes.system.System import System


class Experiment(object):
    ## SETTINGS
    # todo: convert Costs into estimated runtime, removes need for high overhead weight
    workload_overhead_weight = Integer(1500)
    do_all_overhead_weight_by_device: Dict[int, Expr] = {
        0: Integer(300),
        1: Integer(300),
        2: Integer(300),
    }
    reduction_overhead_weight_by_device: Dict[int, Expr] = {
        0: Integer(300),
        1: Integer(300),
        2: Integer(300),
    }

    ## END OF SETTINGS

    __system: System

    # all free symbols will be added to this list for simple retrieval and user query
    free_symbols: Set[Symbol] = set()
    substitutions: Dict[Symbol, Expr] = dict()
    sorted_free_symbols: List[Symbol] = []
    free_symbol_ranges: Dict[Symbol, Tuple[float, float]] = dict()
    free_symbol_distributions: Dict[Symbol, FreeSymbolDistribution] = dict()
    # value suggestions for all free symbols will be stored in this dictionary
    suggested_values: Dict[Symbol, Expr] = dict()

    __memory_region_sizes: Dict[MemoryRegion, int]  # sizes in Bytes

    project_path: Path
    discopop_output_path: Path
    profiler_dir: Path
    code_export_path: Path

    file_mapping: Dict[int, Path]  # file-mapping

    arguments: OptimizerArguments

    detection_result: DetectionResult

    function_models: Dict[FunctionRoot, List[Tuple[CostModel, ContextObject, str]]]
    selected_paths_per_function: Dict[FunctionRoot, Tuple[CostModel, ContextObject]]

    optimization_graph: nx.DiGraph
    next_free_node_id: int
    suggestion_to_node_ids_dict: Dict[int, List[int]]
    node_id_to_suggestion_dict: Dict[int, int]
    pattern_id_to_decisions_dict: Dict[int, List[int]]

    hotspot_functions: Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]]
    hotspot_function_node_ids: List[int]

    profile: Optional[Profile]

    def __init__(
        self,
        file_mapping: Dict[int, Path],
        system: System,
        detection_result: DetectionResult,
        profiler_dir: str,
        arguments: OptimizerArguments,
        hotspot_functions: Dict[HotspotType, List[Tuple[int, int, HotspotNodeType, str, float]]],
    ):
        self.__system = system
        self.detection_result = detection_result
        self.arguments = arguments

        self.__memory_region_sizes = get_sizes_of_memory_regions(
            set(),
            os.path.join(profiler_dir, "memory_regions.txt"),
            return_all_memory_regions=True,
        )

        self.file_mapping = file_mapping
        self.function_models = dict()
        self.selected_paths_per_function = dict()
        self.suggestion_to_node_ids_dict = dict()
        self.node_id_to_suggestion_dict = dict()
        self.pattern_id_to_decisions_dict = dict()
        self.hotspot_functions = hotspot_functions
        self.hotspot_function_node_ids = []

        # collect free symbols from system
        for free_symbol, value_suggestion in system.get_free_symbols():
            self.register_free_symbol(free_symbol, value_suggestion)

    def get_memory_region_size(
        self, memory_region: MemoryRegion, use_symbolic_value: bool = False
    ) -> Tuple[Expr, Expr]:
        if memory_region not in self.__memory_region_sizes:
            self.__memory_region_sizes[memory_region] = 8  # assume 8 Bytes for unknown sizes

        if use_symbolic_value:
            symbolic_memory_region_size = Symbol("mem_reg_size_" + str(memory_region))
            # register the symbolic value in the environment
            self.register_free_symbol(
                symbolic_memory_region_size,
                value_suggestion=Integer(self.__memory_region_sizes[memory_region]),
            )
            return symbolic_memory_region_size, Integer(self.__memory_region_sizes[memory_region])
        else:
            return Integer(self.__memory_region_sizes[memory_region]), Integer(0)

    def register_free_symbol(self, symbol: Symbol, value_suggestion: Optional[Expr] = None) -> None:
        self.free_symbols.add(symbol)
        if value_suggestion is not None:
            self.suggested_values[symbol] = value_suggestion

    def get_next_free_node_id(self) -> int:
        buffer = self.next_free_node_id
        self.next_free_node_id += 1
        return buffer

    def get_system(self) -> System:
        return self.__system

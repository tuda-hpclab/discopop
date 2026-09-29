# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from argparse import ArgumentParser
from pathlib import Path
from typing import List, Optional
from discopop_library.GlobalLogger.setup import setup_logger

from discopop_library.HostpotLoader.HotspotType import parse_hotspot_types
from discopop_library.PathManagement.PathManagement import get_path, get_path_or_none
from discopop_explorer.discopop_explorer import ExplorerArguments, run


def parse_args(argv: Optional[List[str]] = None) -> ExplorerArguments:
    """Parse the arguments passed to the discopop_explorer"""
    parser = ArgumentParser(description="DiscoPoP Explorer")
    # all flags that are not considered stable should be added to the experimental_parser
    experimental_parser = parser.add_argument_group(
        "EXPERIMENTAL",
        "Arguments for the task pattern detector and other experimental features. These flags are considered EXPERIMENTAL and they may or may not be removed or changed in the near future.",
    )

    # fmt: off
    parser.add_argument(
        "--path", type=str, default="./",
        help="Path to the .discopop directory to be analyzed")
    parser.add_argument(
        "--cu-xml", type=str, default="profiler/Data.xml",
        help="CU node xml file")
    parser.add_argument(
        "--dep-file", type=str, default="profiler/dynamic_dependencies.txt",
        help="Dependencies text file"
    )
    parser.add_argument(
        "--loop-counter", type=str, default="profiler/loop_counter_output.txt",
        help="Loop counter data"
    )
    parser.add_argument(
        "--reduction", type=str, default="profiler/reduction.txt",
        help="Reduction variables file"
    )
    parser.add_argument(
        "--fmap", type=str, default="FileMapping.txt",
        help="File mapping")
    parser.add_argument(
        "--plugins", type=str, nargs="*", default=[],
        help="Plugins to execute")
    parser.add_argument(
        "--dp-build-path", type=str, default=Path(__file__).resolve().parent.parent / "build",
        help="Path to DiscoPoP build folder"
    )
    # flags related to output and formatting:
    parser.add_argument(
        "--json", type=str, nargs="?", default="explorer/patterns.json",
        help="Json output")
    parser.add_argument(
        "--profiling", type=str, nargs="?", default=None, const="explorer/profiling_stats.txt",
        help="Enable profiling. If a path is given, the profiling stats are written to the given file, otherwise to profiling_stats.txt",
    )
    parser.add_argument(
        "--dump-pet", type=str, nargs="?", default=None, const="explorer/pet_dump.json",
        help="Dump PET Graph to JSON file. If a path is given, the PET Graph is written to the given file, otherwise to pet_dump.json",
    )
    parser.add_argument(
        "--dump-detection-result", type=str, nargs="?", default="explorer/detection_result_dump.json",
        help="Dump DetectionResult object to JSON file. If a path is given, the DetectionResult object is written to the given file, otherwise to detection_result_dump.json. Contents are equivalent to the json output. NOTE: This dump contains a dump of the PET Graph!",
    )
    parser.add_argument(
        "--enable-patterns", type=str, nargs="?", default="reduction,doall",
        help="Specify comma-separated list of pattern types to be identified. Options: reduction,doall,task,pipeline,geodec,simplegpu. Default: reduction,doall",
    )
    parser.add_argument(
        "--hotspot-types", type=str, default="yes,maybe",
        help="Comma-separated list of hotspot types whose code regions are considered during the analysis. Only takes effect if hotspot information exists (hotspot_detection/Hotspots.json); without it, the whole program is analyzed. Options: yes,no,maybe. Default: yes,maybe",
    )
    parser.add_argument("--load-existing-doall-and-reduction-patterns", action="store_true", help="Skip pattern detection and insert existing patterns.json contents into the created detection_result.json")
    parser.add_argument("--log", type=str, default="WARNING", help="Specify log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    parser.add_argument("--write-log", action="store_true", help="Create Logfile.")
    parser.add_argument("-j", "--jobs", type=int, help="Allow the use of N threads. Use 0 or 1 to disable threading. Default: Unlimited", default=None)

    # EXPERIMENTAL FLAGS:
    # temporary flag for microbenchmark file
    experimental_parser.add_argument(
        "--microbench-file", type=str, default=None,
        help="path to a microbenchmark json file",
    )

    # flags related to task pattern detector:
    experimental_parser.add_argument(
        "--task-pattern", action="store_true",
        help="Enables the task parallelism pattern identification. Requires --cu-inst-res and --llvm-cxxfilt-path to be set.",
    )
#    experimental_parser.add_argument(
#        "--detect-scheduling-clauses", action="store_true",
#        help="Enables the detection of scheduling clauses for parallel loops.")

    experimental_parser.add_argument(
        "--generate-data-cu-inst", type=str, default=None,
        help="Generates Data_CUInst.txt file and stores it in the given directory. Stops the regular execution of the discopop_explorer. Requires --cu-xml, --dep-file, --loop-counter, --reduction.",
    )
    experimental_parser.add_argument(
        "--cu-inst-res", type=str, default=None,
        help="CU instantiation result file."
    )
    experimental_parser.add_argument(
        "--llvm-cxxfilt-path", type=str, default=None,
        help="Path to llvm-cxxfilt executable. Required for task pattern detector if non-standard path should be used.",
    )
    experimental_parser.add_argument(
        "--enable-statistics", action="store_true", help="Enable the calculation and storing of statistics for code and generated suggestions."
    )
    experimental_parser.add_argument(
        "--ignore-dependency-states", action="store_true",
        help="Ignore the callpath state markers (\"@<state_id>\") contained in the dependency data. Dependencies are then interpreted as if the profiler had not distinguished between callpath states, which also reclassifies the affected dependencies from dynamic to static. Useful to compare pattern detection with and without state information.",
    )
    experimental_parser.add_argument(
        "--plot-pet", type=str, nargs="?", default=None, const="explorer/pet_plot.gexf",
        help="Plots PET as a GEXF file. If a path is given (file extension has to be .gexf), the PET Graph is written to the given file, otherwise to pet_plot.gexf"
    )
    experimental_parser.add_argument(
        "--plot-task-graph", action="store_true", help="Enables interactive plotting of the task graph."
    )
    experimental_parser.add_argument(
        "--plot-context-graph", action="store_true", help="Enables interactive plotting of the context graph."
    )
    parser.add_argument("--visualize", action="store_true", help="Enable the visualizer.")
    # fmt: on

    arguments = parser.parse_args(argv)

    # ensure that --cu-inst-res and --llvm-cxxfilt-path are set if --task-pattern is set
    if arguments.task_pattern and (arguments.cu_inst_res is None or arguments.llvm_cxxfilt_path is None):
        parser.error("--task-pattern requires --cu-inst-res and --llvm-cxxfilt-path to be set")

    try:
        hotspot_types = parse_hotspot_types(arguments.hotspot_types)
    except ValueError as error:
        parser.error("--hotspot-types: " + str(error) + " Options: yes,no,maybe")

    # ensure that --cu-xml, --dep-file, --loop-counter, --reduction are set if --generate-data-cu-inst is set
    # NOTE: no need to check, the defaults got us covered
    # if arguments.generate_data_cu_inst is not None and (arguments.cu_xml is None or arguments.dep_file is None or arguments.loop_counter is None or arguments.reduction is None):
    #    parser.error("--generate-data-cu-inst requires --cu-xml, --dep-file, --loop-counter, --reduction to be set")

    # post processing of arguments: interpret relative paths as relative to project path
    arguments.path = str(Path(arguments.path).resolve())
    arguments.cu_xml = get_path(arguments.path, arguments.cu_xml)
    arguments.dep_file = get_path(arguments.path, arguments.dep_file)
    arguments.loop_counter = get_path(arguments.path, arguments.loop_counter)
    arguments.reduction = get_path(arguments.path, arguments.reduction)
    arguments.fmap = get_path(arguments.path, arguments.fmap)
    arguments.json = get_path_or_none(arguments.path, arguments.json)
    arguments.cu_inst_res = get_path_or_none(arguments.path, arguments.cu_inst_res)
    arguments.generate_data_cu_inst = get_path_or_none(arguments.path, arguments.generate_data_cu_inst)
    arguments.profiling = get_path_or_none(arguments.path, arguments.profiling)
    arguments.dump_pet = get_path_or_none(arguments.path, arguments.dump_pet)
    arguments.dump_detection_result = get_path_or_none(arguments.path, arguments.dump_detection_result)
    arguments.microbench_file = get_path_or_none(arguments.path, arguments.microbench_file)
    arguments.plot_pet = get_path_or_none(arguments.path, arguments.plot_pet)

    return ExplorerArguments(
        discopop_build_path=arguments.dp_build_path,
        microbench_file=arguments.microbench_file,
        project_path=arguments.path,
        cu_xml_file=arguments.cu_xml,
        dep_file=arguments.dep_file,
        loop_counter_file=arguments.loop_counter,
        reduction_file=arguments.reduction,
        file_mapping_file=arguments.fmap,
        plugins=arguments.plugins,
        hotspot_types=hotspot_types,
        enable_task_pattern=arguments.task_pattern,
        #        detect_scheduling_clauses=arguments.detect_scheduling_clauses,
        detect_scheduling_clauses=False,
        enable_profiling_dump_file=arguments.profiling,
        enable_pet_dump_file=arguments.dump_pet,
        enable_detection_result_dump_file=arguments.dump_detection_result,
        enable_patterns=arguments.enable_patterns,
        generate_data_cu_inst=arguments.generate_data_cu_inst,
        cu_inst_result_file=arguments.cu_inst_res,
        llvm_cxxfilt_path=arguments.llvm_cxxfilt_path,
        enable_json_file=arguments.json,
        log_level=arguments.log.upper(),
        write_log=arguments.write_log,
        load_existing_doall_and_reduction_patterns=arguments.load_existing_doall_and_reduction_patterns,
        ignore_dependency_states=arguments.ignore_dependency_states,
        collect_statistics=arguments.enable_statistics,
        jobs=arguments.jobs,
        enable_pet_plot_file=arguments.plot_pet,
        enable_task_graph_plot=arguments.plot_task_graph,
        enable_context_graph_plot=arguments.plot_context_graph,
        enable_visualizer=arguments.visualize,
        visualize_on=None,
    )


def main() -> None:
    arguments = parse_args()
    setup_logger(arguments)
    run(arguments)


if __name__ == "__main__":
    main()

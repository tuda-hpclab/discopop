# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from argparse import ArgumentParser
import os
import sys
from discopop_library.GlobalLogger.setup import setup_logger
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
from discopop_library.ProjectManager.ProjectManager import run
from discopop_library.ProjectManager.configurations.execution_time import (
    DEFAULT_EXECUTION_TIME_REGEX,
    DEFAULT_EXECUTION_TIME_TAG,
    EXECUTION_TIME_DISABLED,
    validate_execution_time_regex,
)
from discopop_library.ProjectManager.configurations.repetitions import (
    DEFAULT_MEASURED_REPETITIONS,
    validate_repetitions,
)

GUI_COMMAND = "discopop_gui"

GUI_MOVED_NOTICE = (
    "Note: 'discopop' used to open the graphical interface. It is now the command\n"
    "line tool, and the window has moved to '" + GUI_COMMAND + "' (equivalent to\n"
    "'discopop_project_manager --gui')."
)


def _build_parser() -> ArgumentParser:
    """Build the parser shared by the command line and the GUI entry point."""
    parser = ArgumentParser(description="Initialize and prepare projects for the use in the DiscoPoP framework.")
    # all flags that are not considered stable should be added to the experimental_parser
    experimental_parser = parser.add_argument_group(
        "EXPERIMENTAL",
        "Arguments for configuration manager and other experimental features. These arguments are considered EXPERIMENTAL and they may or may not be removed or modified in the near future.",
    )

    # fmt: off
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable verbose output.")
    parser.add_argument("-p", "--project", default=os.getcwd(), help="Path to the projects root folder. Important: it must be possible to create a copy of this folder and compile / execute the copy with the definitions from compile.sh, execute.sh, and settings.json. Please refer to the wiki pages (https://tuda-hpclab.github.io/discopop/) for further details. Default: $(cwd)")
    parser.add_argument("--init", action="store_true", help="Initialize the .discopop directory in the specified project path")
    parser.add_argument("--gui", action="store_true", help="Open the graphical configuration manager")
    parser.add_argument("-x", "--execute", default="tiny", help="Comma separated list of configurations to be executed. Format: <config_name>[:<mode>][:<thread_count>] . Modes: dp,hd,seq,par. Default: tiny")
    parser.add_argument("-xf", "--execute-full", action="store_true", help="Execute all configurations for validation purposes.")
    parser.add_argument("-a", "--apply-suggestions", help="Comma separated list of suggestions ids to be applied before the specified execution. Use the keyword 'auto' to load the configuration determined by the autotuner (if multiple configurations exist, union will be considered). Use the keyword 'prm' to load the configuration determined by the parallel region merger.")
    parser.add_argument('-l', '--list', action="store_true", help="Show a list of available configurations. If set, nothing else will be done.")
    parser.add_argument("-i", "--inplace", action="store_true", help="Prevents the creation of project copies when code configurations are executed. Instead, executes the configuration in the project root folder.")
    parser.add_argument("--skip-cleanup", action="store_true", help="Prevents the deletion of created project copies. May requires high amount of disk space.")
    parser.add_argument("--report", action="store_true", help="Generate and a report of the stored execution results.")
    parser.add_argument("--show-report", action="store_true", help="Show the generated report of the stored execution results.")
    parser.add_argument("-r", "--reset", action="store_true", help="Reset the .discopop folder except configurations in project subdirectory.")
    parser.add_argument("-rx", "--reset-execution-results", action="store_true", help="Reset the observed execution results and generated reports.")
    parser.add_argument("-lp", "--label-prefix", default="", help="Specify a prefix for execution measurement labels")
    parser.add_argument("-tox", "--timeout-execution", type=int, default=3600, help="Timeout in seconds for each individual code execution. Use 0 to disable timeout. Default: 3600.")
    parser.add_argument("-toc", "--timeout-compilation", type=int, default=3600, help="Timeout in seconds for each individual code compilation. Use 0 to disable timeout. Default: 3600.")
    parser.add_argument("-tov", "--timeout-validation", type=int, default=3600, help="Timeout in seconds for each individual output validation (validate.sh). Use 0 to disable timeout. Default: 3600.")

    parser.add_argument("-xr", "--execution-repetitions", type=int, default=DEFAULT_MEASURED_REPETITIONS,
                        help="Repeat each measured execution this many times and report the median of the measured times, so that a single noisy run no longer decides a configuration's runtime. Every individual measurement is kept in execution_results.json alongside it. Applies to the seq and par runs; the dp and hd runs are instrumented profiling runs rather than measurements and are never repeated. Pass 1 to measure once, as releases before this option did. Default: " + str(DEFAULT_MEASURED_REPETITIONS) + ".")

    parser.add_argument("-etr", "--execution-time-regex", nargs="?", const=DEFAULT_EXECUTION_TIME_REGEX, default=None,
                        help="Read the execution time from the console output of execute.sh instead of measuring its wall clock time. Expects a regular expression whose first capture group holds the value, e.g. 'Total time:\\s*([0-9.]+)'. Given without a value, the tag '<" + DEFAULT_EXECUTION_TIME_TAG + ">value</" + DEFAULT_EXECUTION_TIME_TAG + ">' is searched for. Overrides the per configuration setting stored in execution_time.json; pass an empty string to disable the search even where a configuration enables it. If omitted, each configuration's own setting applies.")

    parser.add_argument("--log", type=str, default="WARNING", help="Specify log level: DEBUG, INFO, WARNING, ERROR, CRITICAL")
    parser.add_argument("--write-log", action="store_true", help="Create Logfile.")
    # EXPERIMENTAL FLAGS:
    # fmt: on

    return parser


def parse_args(force_gui: bool = False) -> ProjectManagerArguments:
    """Parse the arguments passed to the discopop_configuration_manager"""
    arguments = _build_parser().parse_args()
    if force_gui:
        arguments.gui = True

    # Reject an unusable pattern here rather than letting every execution fall
    # back to the wall clock time with a warning nobody reads.
    if arguments.execution_time_regex not in (None, EXECUTION_TIME_DISABLED):
        regex_error = validate_execution_time_regex(arguments.execution_time_regex)
        if regex_error is not None:
            print("ERROR: --execution-time-regex: " + regex_error)
            sys.exit(1)

    # A count of zero would mean "measure nothing"; rejected here rather than after
    # the project has been copied and built.
    repetitions_error = validate_repetitions(arguments.execution_repetitions)
    if repetitions_error is not None:
        print("ERROR: --execution-repetitions: " + repetitions_error)
        sys.exit(1)

    return ProjectManagerArguments(
        project_root=arguments.project,
        full_execute=arguments.execute_full,
        list=arguments.list,
        execute_configurations=arguments.execute,
        execute_inplace=arguments.inplace,
        skip_cleanup=arguments.skip_cleanup,
        generate_report=arguments.report,
        show_report=arguments.show_report,
        initialize_directory=arguments.init,
        apply_suggestions=arguments.apply_suggestions,
        reset=arguments.reset,
        reset_execution_results=arguments.reset_execution_results,
        gui=arguments.gui,
        log_level=arguments.log.upper(),
        write_log=arguments.write_log,
        label_prefix=arguments.label_prefix,
        timeout_execution=None if arguments.timeout_execution == 0 else float(arguments.timeout_execution),
        timeout_compilation=None if arguments.timeout_compilation == 0 else float(arguments.timeout_compilation),
        timeout_validation=None if arguments.timeout_validation == 0 else float(arguments.timeout_validation),
        execution_time_regex=arguments.execution_time_regex,
        execution_repetitions=arguments.execution_repetitions,
    )


def main() -> None:
    if len(sys.argv) == 1:
        # A bare "discopop" used to open the graphical interface. Falling through
        # to the command line tool would instead execute the default -x
        # configuration ("tiny"): copying, building and running the project is
        # not what somebody reaching for the bare command name asked for, and
        # nothing in the output would explain why their machine got busy.
        parser = _build_parser()
        parser.print_help()
        if parser.prog == "discopop":
            print("\n" + GUI_MOVED_NOTICE)
        return
    arguments = parse_args()
    setup_logger(arguments)
    run(arguments)


def gui_main() -> None:
    arguments = parse_args(force_gui=True)
    setup_logger(arguments)
    run(arguments)


if __name__ == "__main__":
    main()

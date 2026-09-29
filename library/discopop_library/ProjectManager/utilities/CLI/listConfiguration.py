# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
from typing import Dict, List, Optional
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
import logging
from tabulate import tabulate  # type: ignore

from discopop_library.ProjectManager.configurations.compile_script import (
    resolve_compile_script_path,
    validation_needs_separate_compile,
)
from discopop_library.PatchApplicator.PatchApplicationResult import clear_application_result
from discopop_library.ProjectManager.configurations.copying import (
    copy_configuration,
    get_application_result,
    patch_applicator_dir_of,
)
from discopop_library.ProjectManager.configurations.deletion import delete_configuration
from discopop_library.ProjectManager.configurations.execution import (
    execute_configuration,
    record_skipped_execution,
)
from discopop_library.ProjectManager.configurations.execution_time import resolve_execution_time_regex
from discopop_library.ProjectManager.configurations.repetitions import repetitions_for_mode
from discopop_library.ProjectManager.configurations.validation import has_validate_script, run_validation_phase

logger = logging.getLogger("ConfigurationManager")

PATH = str
NAME = str  # todo rename


def __get_legend() -> str:
    return """Legend:
(C):  Compatibility: required scripts and settings exist and validated via execution.
(TC): Theoretical Compatibility: required scripts and settings exist but not validated.
(F):  Failure: executing the script resulted in a non-zero return code.
(M):  Missing: file does not exist
(NV):  Not validated
"""


def show_configurations_without_execution(arguments: ProjectManagerArguments) -> None:
    logger.info("listing available configurations without execution ...")

    # collect configurations
    configurations = [f.path for f in os.scandir(arguments.project_config_dir) if f.is_dir()]

    compatibility: Dict[PATH, Dict[NAME, bool]] = dict()
    table = [["Configuration", "(TC) Autotuner"]]
    # collect compatibility information
    for config in configurations:
        # autotuner: dp settings & hd settings
        dp_settings = os.path.join(config, "dp_settings.json")
        hd_settings = os.path.join(config, "hd_settings.json")
        dp_settings_exist = os.path.exists(dp_settings)
        hd_settings_exist = os.path.exists(hd_settings)
        if not config in compatibility:
            compatibility[config] = dict()
        compatibility[config]["autotuner"] = dp_settings_exist and hd_settings_exist

        # prepare display
        # --> autotuner
        if compatibility[config]["autotuner"]:
            autotuner_cell_contents = "PASS"
        else:
            autotuner_cell_contents = ""
            autotuner_cell_contents += "(M) dp - settings\n" if not dp_settings_exist else ""
            autotuner_cell_contents += "(M) hd - settings\n" if not hd_settings_exist else ""

        table.append([os.path.basename(config), autotuner_cell_contents])

    # display
    print(__get_legend())
    print(tabulate(table, tablefmt="grid"))


def show_configurations_with_execution(
    arguments: ProjectManagerArguments, restricted_configurations: Optional[List[str]] = None
) -> None:
    logger.info("listing configurations with validating execution ...")
    # prepare restrictions
    config_restrictions: Dict[NAME, List[str]] = dict()
    config_thread_counts: Dict[NAME, Dict[str, int]] = dict()

    if restricted_configurations is not None:
        for entry in restricted_configurations:
            if ":" in entry:
                config_name = entry.split(":")[0]
                config_mode = entry.split(":")[1]
                config_thread_count = int(entry.split(":")[2]) if entry.count(":") > 1 else __get_default_thread_count()
            else:
                config_name = entry
                config_mode = ""
                config_thread_count = 1 if config_name == "seq" else __get_default_thread_count()
            if config_name not in config_restrictions:
                config_restrictions[config_name] = []
            if len(config_mode) > 0:
                config_restrictions[config_name].append(config_mode)
            if config_name not in config_thread_counts:
                config_thread_counts[config_name] = dict()
            non_null_cfc = 1
            if config_thread_count is not None:
                non_null_cfc = config_thread_count
            config_thread_counts[config_name][config_mode] = non_null_cfc

    # collect and restrict configurations if required
    configurations = [f.path for f in os.scandir(arguments.project_config_dir) if f.is_dir()]
    if len(config_restrictions) != 0:
        logger.debug("restricting tested configurations to: " + str(config_restrictions))
        configurations = [config for config in configurations if os.path.basename(config) in config_restrictions]

    compatibility: Dict[PATH, Dict[NAME, bool]] = dict()
    table = [["Configuration", "Overview", "(C) Autotuner"]]
    # execute configurations and collect compatibility information
    for config in configurations:
        # declare values
        dp_settings_exist = False
        dp_compile_successful = False
        dp_execute_successful = False
        hd_settings_exist = False
        hd_compile_successful = False
        hd_execute_successful = False
        seq_settings_exist = False
        seq_compile_successful = False
        seq_execute_successful = False
        seq_validate_compile_successful = False
        seq_validate_successful = False
        par_settings_exist = False
        par_compile_successful = False
        par_execute_successful = False
        par_validate_compile_successful = False
        par_validate_successful = False
        # validate.sh is an optional, per-config script that re-runs the code and
        # validates its output, separated from the timed execute.sh run. It is only
        # applied to the "real" runs (seq/par); dp/hd are profiling modes where
        # re-running the instrumented binary would regenerate profiling data.
        validate_sh_exists = has_validate_script(config)
        # validate.sh may require its own build, in which case the validation phase
        # recompiles after the timed execute.sh run. A compile_validate.sh without a
        # validate.sh is ignored, hence the conjunction.
        validate_compile_required = validate_sh_exists and validation_needs_separate_compile(
            arguments.project_config_dir, os.path.basename(config)
        )
        # Only execute.sh is a measurement, so only its runs are searched for an
        # execution time reported by the program itself; compile.sh and validate.sh
        # keep their wall clock times.
        # Repetitions follow the same reasoning one step further: of the execute.sh
        # runs, only seq and par measure a runtime. dp and hd are instrumented
        # profiling runs whose output feeds the Explorer, so repeating them would
        # multiply the profiling cost without improving any measurement.
        execution_time_regex = resolve_execution_time_regex(config, arguments.execution_time_regex)

        if arguments.execute_inplace:
            # inplace runs reuse the project root's .discopop, which -- unlike a fresh
            # copy -- is never rewritten; drop a result recorded by an earlier apply so
            # it cannot be attributed to this run
            clear_application_result(patch_applicator_dir_of(arguments.project_root))

        # collect overview information
        compile_sh = resolve_compile_script_path(arguments.project_config_dir, os.path.basename(config))
        shared_dp_settings = os.path.join(arguments.project_config_dir, "dp_settings.json")
        shared_hd_settings = os.path.join(arguments.project_config_dir, "hd_settings.json")
        shared_seq_settings = os.path.join(arguments.project_config_dir, "seq_settings.json")
        shared_par_settings = os.path.join(arguments.project_config_dir, "par_settings.json")

        # --> dp
        dp_settings_exist = os.path.exists(shared_dp_settings)
        if __is_selected(config_restrictions, config, "dp"):
            dp_project_path = (
                arguments.project_root
                if arguments.execute_inplace
                else copy_configuration(arguments, config, shared_dp_settings)
            )

            # A failed patch application leaves the copy holding the original code;
            # compiling and measuring it would misreport it as a parallel run.
            dp_application_failed = __handle_application_failure(
                arguments,
                dp_project_path,
                config,
                shared_dp_settings,
                os.path.join(config, "execute.sh"),
                __get_thread_count(config, "dp", config_thread_counts),
            )
            ret = (
                None
                if dp_application_failed
                else execute_configuration(
                    arguments,
                    dp_project_path,
                    config,
                    shared_dp_settings,
                    compile_sh,
                    __get_thread_count(config, "dp", config_thread_counts),
                    arguments.timeout_compilation,
                )
            )
            dp_compile_successful = ret is not None and ret[0] == 0

            if dp_compile_successful:
                ret = execute_configuration(
                    arguments,
                    dp_project_path,
                    config,
                    shared_dp_settings,
                    os.path.join(config, "execute.sh"),
                    __get_thread_count(config, "dp", config_thread_counts),
                    arguments.timeout_execution,
                    execution_time_regex=execution_time_regex,
                )
                dp_execute_successful = ret is not None and ret[0] == 0
            if not (arguments.skip_cleanup or arguments.execute_inplace):
                delete_configuration(arguments, dp_project_path)
        # --> hd
        hd_settings_exist = os.path.exists(shared_hd_settings)
        if __is_selected(config_restrictions, config, "hd"):
            hd_project_path = (
                arguments.project_root
                if arguments.execute_inplace
                else copy_configuration(arguments, config, shared_hd_settings)
            )

            # A failed patch application leaves the copy holding the original code;
            # compiling and measuring it would misreport it as a parallel run.
            hd_application_failed = __handle_application_failure(
                arguments,
                hd_project_path,
                config,
                shared_hd_settings,
                os.path.join(config, "execute.sh"),
                __get_thread_count(config, "hd", config_thread_counts),
            )
            ret = (
                None
                if hd_application_failed
                else execute_configuration(
                    arguments,
                    hd_project_path,
                    config,
                    shared_hd_settings,
                    compile_sh,
                    __get_thread_count(config, "hd", config_thread_counts),
                    arguments.timeout_compilation,
                )
            )
            hd_compile_successful = ret is not None and ret[0] == 0

            if hd_compile_successful:
                ret = execute_configuration(
                    arguments,
                    hd_project_path,
                    config,
                    shared_hd_settings,
                    os.path.join(config, "execute.sh"),
                    __get_thread_count(config, "hd", config_thread_counts),
                    arguments.timeout_execution,
                    execution_time_regex=execution_time_regex,
                )
                hd_execute_successful = ret is not None and ret[0] == 0
            if not (arguments.skip_cleanup or arguments.execute_inplace):
                delete_configuration(arguments, hd_project_path)
        # --> seq
        seq_settings_exist = os.path.exists(shared_seq_settings)
        if __is_selected(config_restrictions, config, "seq"):
            seq_project_path = (
                arguments.project_root
                if arguments.execute_inplace
                else copy_configuration(arguments, config, shared_seq_settings)
            )
            # A failed patch application leaves the copy holding the original code;
            # compiling and measuring it would misreport it as a parallel run.
            seq_application_failed = __handle_application_failure(
                arguments,
                seq_project_path,
                config,
                shared_seq_settings,
                os.path.join(config, "execute.sh"),
                __get_thread_count(config, "seq", config_thread_counts),
            )
            ret = (
                None
                if seq_application_failed
                else execute_configuration(
                    arguments,
                    seq_project_path,
                    config,
                    shared_seq_settings,
                    compile_sh,
                    __get_thread_count(config, "seq", config_thread_counts),
                    arguments.timeout_compilation,
                )
            )
            seq_compile_successful = ret is not None and ret[0] == 0

            if seq_compile_successful:
                ret = execute_configuration(
                    arguments,
                    seq_project_path,
                    config,
                    shared_seq_settings,
                    os.path.join(config, "execute.sh"),
                    __get_thread_count(config, "seq", config_thread_counts),
                    arguments.timeout_execution,
                    execution_time_regex=execution_time_regex,
                    repetitions=repetitions_for_mode("seq", arguments.execution_repetitions),
                )
                seq_execute_successful = ret is not None and ret[0] == 0

                # optional output validation (auto-run when validate.sh exists);
                # no validate.sh => execute.sh alone decides correctness
                if seq_execute_successful:
                    seq_validation = run_validation_phase(
                        arguments,
                        seq_project_path,
                        config,
                        shared_seq_settings,
                        __get_thread_count(config, "seq", config_thread_counts),
                        timeout_compilation=arguments.timeout_compilation,
                        timeout_validation=arguments.timeout_validation,
                    )
                    seq_validate_compile_successful = (
                        not seq_validation.compile_required or seq_validation.compile_successful
                    )
                    seq_validate_successful = seq_validation.verdict(seq_execute_successful)
            if not (arguments.skip_cleanup or arguments.execute_inplace):
                delete_configuration(arguments, seq_project_path)
        # --> par
        par_settings_exist = os.path.exists(shared_par_settings)
        if __is_selected(config_restrictions, config, "par"):
            par_project_path = (
                arguments.project_root
                if arguments.execute_inplace
                else copy_configuration(arguments, config, shared_par_settings)
            )
            # A failed patch application leaves the copy holding the original code;
            # compiling and measuring it would misreport it as a parallel run.
            par_application_failed = __handle_application_failure(
                arguments,
                par_project_path,
                config,
                shared_par_settings,
                os.path.join(config, "execute.sh"),
                __get_thread_count(config, "par", config_thread_counts),
            )
            ret = (
                None
                if par_application_failed
                else execute_configuration(
                    arguments,
                    par_project_path,
                    config,
                    shared_par_settings,
                    compile_sh,
                    __get_thread_count(config, "par", config_thread_counts),
                    arguments.timeout_compilation,
                )
            )
            par_compile_successful = ret is not None and ret[0] == 0

            if par_compile_successful:
                ret = execute_configuration(
                    arguments,
                    par_project_path,
                    config,
                    shared_par_settings,
                    os.path.join(config, "execute.sh"),
                    __get_thread_count(config, "par", config_thread_counts),
                    arguments.timeout_execution,
                    execution_time_regex=execution_time_regex,
                    repetitions=repetitions_for_mode("par", arguments.execution_repetitions),
                )
                par_execute_successful = ret is not None and ret[0] == 0

                # optional output validation (auto-run when validate.sh exists);
                # no validate.sh => execute.sh alone decides correctness
                if par_execute_successful:
                    par_validation = run_validation_phase(
                        arguments,
                        par_project_path,
                        config,
                        shared_par_settings,
                        __get_thread_count(config, "par", config_thread_counts),
                        timeout_compilation=arguments.timeout_compilation,
                        timeout_validation=arguments.timeout_validation,
                    )
                    par_validate_compile_successful = (
                        not par_validation.compile_required or par_validation.compile_successful
                    )
                    par_validate_successful = par_validation.verdict(par_execute_successful)
            if not (arguments.skip_cleanup or arguments.execute_inplace):
                delete_configuration(arguments, par_project_path)

        # collect information: autotuner
        if not config in compatibility:
            compatibility[config] = dict()
        compatibility[config]["autotuner"] = (
            dp_settings_exist
            and hd_settings_exist
            and dp_compile_successful
            and dp_execute_successful
            and hd_compile_successful
            and hd_execute_successful
        )

        # prepare display
        # --> overview
        overview_cell_contents = ""
        if __is_selected(config_restrictions, config, "dp"):
            overview_cell_contents += "(PASS) dp - settings\n" if dp_settings_exist else "(M) dp - settings\n"
            overview_cell_contents += "(PASS) dp - compile\n" if dp_compile_successful else "(F) dp - compile\n"
            overview_cell_contents += "(PASS) dp - execute\n" if dp_execute_successful else "(F) dp - execute\n"
        if __is_selected(config_restrictions, config, "hd"):
            overview_cell_contents += "(PASS) hd - settings\n" if hd_settings_exist else "(M) hd - settings\n"
            overview_cell_contents += "(PASS) hd - compile\n" if hd_compile_successful else "(F) hd - compile\n"
            overview_cell_contents += "(PASS) hd - execute\n" if hd_execute_successful else "(F) hd - execute\n"
        if __is_selected(config_restrictions, config, "seq"):
            overview_cell_contents += "(PASS) seq - settings\n" if seq_settings_exist else "(M) seq - settings\n"
            overview_cell_contents += "(PASS) seq - compile\n" if seq_compile_successful else "(F) seq - compile\n"
            overview_cell_contents += "(PASS) seq - execute\n" if seq_execute_successful else "(F) seq - execute\n"
            if validate_compile_required:
                overview_cell_contents += (
                    "(PASS) seq - validate-compile\n"
                    if seq_validate_compile_successful
                    else "(F) seq - validate-compile\n"
                )
            if validate_sh_exists:
                overview_cell_contents += (
                    "(PASS) seq - validate\n" if seq_validate_successful else "(F) seq - validate\n"
                )
        if __is_selected(config_restrictions, config, "par"):
            overview_cell_contents += "(PASS) par - settings\n" if par_settings_exist else "(M) par - settings\n"
            overview_cell_contents += "(PASS) par - compile\n" if par_compile_successful else "(F) par - compile\n"
            overview_cell_contents += "(PASS) par - execute\n" if par_execute_successful else "(F) par - execute\n"
            if validate_compile_required:
                overview_cell_contents += (
                    "(PASS) par - validate-compile\n"
                    if par_validate_compile_successful
                    else "(F) par - validate-compile\n"
                )
            if validate_sh_exists:
                overview_cell_contents += (
                    "(PASS) par - validate\n" if par_validate_successful else "(F) par - validate\n"
                )
        # --> autotuner
        if compatibility[config]["autotuner"]:
            autotuner_cell_contents = "PASS "
        else:
            autotuner_dp_failure_marker = (
                "(NV)"
                if (
                    os.path.basename(config) in config_restrictions
                    and "dp" not in config_restrictions[os.path.basename(config)]
                )
                else "(F)"
            )
            autotuner_hd_failure_marker = (
                "(NV)"
                if (
                    os.path.basename(config) in config_restrictions
                    and "hd" not in config_restrictions[os.path.basename(config)]
                )
                else "(F)"
            )
            autotuner_cell_contents = ""
            autotuner_cell_contents += "(M) dp - settings\n" if not dp_settings_exist else ""
            autotuner_cell_contents += (
                autotuner_dp_failure_marker + " dp - compile\n" if not dp_compile_successful else ""
            )
            autotuner_cell_contents += (
                autotuner_dp_failure_marker + " dp - execute\n" if not dp_execute_successful else ""
            )
            autotuner_cell_contents += "(M) hd - settings\n" if not hd_settings_exist else ""
            autotuner_cell_contents += (
                autotuner_hd_failure_marker + " hd - compile\n" if not hd_compile_successful else ""
            )
            autotuner_cell_contents += (
                autotuner_hd_failure_marker + " hd - execute\n" if not hd_execute_successful else ""
            )

        table.append([os.path.basename(config), overview_cell_contents, autotuner_cell_contents])

    # display
    print(__get_legend())
    print(tabulate(table, tablefmt="grid"))


def __is_selected(config_restrictions: Dict[NAME, List[str]], config: str, mode: str) -> bool:
    return len(config_restrictions) == 0 or (
        os.path.basename(config) in config_restrictions
        and (
            len(config_restrictions[os.path.basename(config)]) == 0
            or mode in config_restrictions[os.path.basename(config)]
        )
    )


def __get_thread_count(config: str, mode: str, config_thread_counts: dict[NAME, Dict[str, int]]) -> int:
    config_name = os.path.basename(config)
    if mode == "seq":
        return 1
    if config_name in config_thread_counts:
        if mode in config_thread_counts[config_name]:
            return config_thread_counts[config_name][mode]

    return __get_default_thread_count()


def __get_default_thread_count() -> int:
    cpu_count = os.cpu_count()
    if cpu_count is None:
        return 4  # default if no value could be determined

    return int(cpu_count / 2)  # account of hyperthreading typically encountered as a default


def __handle_application_failure(
    arguments: ProjectManagerArguments,
    project_path: str,
    config: str,
    settings_path: str,
    script_path: str,
    thread_count: int,
) -> bool:
    """True when the copy's requested suggestions did not all reach the code.

    A placeholder entry is recorded in that case, so the skipped run stays visible in
    the reports instead of silently looking like a parallel run without a speedup.
    """
    if arguments.execute_inplace:
        return False
    result = get_application_result(project_path)
    if result is None or not result.failure:
        return False
    print("WARNING: " + result.summary())
    print("Skipping this run: executing the copy would measure the UNMODIFIED code.")
    record_skipped_execution(arguments, project_path, config, settings_path, script_path, thread_count, result)
    return True

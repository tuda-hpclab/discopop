# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

import os
from dataclasses import dataclass
from typing import Dict, List, Optional
from discopop_library.ProjectManager.ProjectManagerArguments import ProjectManagerArguments
import logging
from tabulate import tabulate  # type: ignore

from discopop_library.ProjectManager.configurations.compile_script import (
    resolve_compile_script_path,
    validation_needs_separate_compile,
)
from discopop_library.PatchApplicator.PatchApplicationResult import clear_application_result
from discopop_library.ProjectManager.configurations.building import BuildResult, build_lock, ensure_build
from discopop_library.ProjectManager.configurations.builds import BuildKey, BuildPolicy, BuildRecord, invalidate_build
from discopop_library.ProjectManager.configurations.running import execute_in_build
from discopop_library.ProjectManager.configurations.copying import (
    patch_applicator_dir_of,
    resolve_requested_suggestions,
)
from discopop_library.PatchApplicator.PatchApplicationResult import PatchApplicationResult
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
        if config not in compatibility:
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
        outcomes: Dict[str, _ModeOutcome] = dict()
        for mode in _RUN_ORDER:
            shared_settings = os.path.join(arguments.project_config_dir, mode + "_settings.json")
            if __is_selected(config_restrictions, config, mode):
                outcomes[mode] = __run_mode(
                    arguments,
                    config,
                    mode,
                    shared_settings,
                    compile_sh,
                    __get_thread_count(config, mode, config_thread_counts),
                    execution_time_regex,
                )
            else:
                # not run, but whether the settings exist is reported nonetheless
                outcomes[mode] = _ModeOutcome(settings_exist=os.path.exists(shared_settings))
        dp_settings_exist = outcomes["dp"].settings_exist
        dp_compile_successful = outcomes["dp"].compile_successful
        dp_execute_successful = outcomes["dp"].execute_successful
        hd_settings_exist = outcomes["hd"].settings_exist
        hd_compile_successful = outcomes["hd"].compile_successful
        hd_execute_successful = outcomes["hd"].execute_successful
        seq_settings_exist = outcomes["seq"].settings_exist
        seq_compile_successful = outcomes["seq"].compile_successful
        seq_execute_successful = outcomes["seq"].execute_successful
        seq_validate_compile_successful = outcomes["seq"].validate_compile_successful
        seq_validate_successful = outcomes["seq"].validate_successful
        par_settings_exist = outcomes["par"].settings_exist
        par_compile_successful = outcomes["par"].compile_successful
        par_execute_successful = outcomes["par"].execute_successful
        par_validate_compile_successful = outcomes["par"].validate_compile_successful
        par_validate_successful = outcomes["par"].validate_successful

        # collect information: autotuner
        if config not in compatibility:
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


@dataclass
class _ModeOutcome:
    """What the run of one mode of a configuration achieved; everything but the settings is False if it did not run."""

    settings_exist: bool = False
    compile_successful: bool = False
    execute_successful: bool = False
    validate_compile_successful: bool = False
    validate_successful: bool = False


# the order the modes are run in (the profiling modes first)
_RUN_ORDER = ("dp", "hd", "seq", "par")

# the modes whose execute.sh is a measurement, and which a validate.sh is applied to
_VALIDATED_MODES = ("seq", "par")


def __run_mode(
    arguments: ProjectManagerArguments,
    config: str,
    mode: str,
    shared_settings: str,
    compile_sh: str,
    thread_count: int,
    execution_time_regex: Optional[str],
) -> _ModeOutcome:
    """Compile and execute ``config`` in ``mode``: in the project root (``--inplace``), otherwise in a build that is
    kept and reused as long as it is current (see :mod:`discopop_library.ProjectManager.configurations.builds`)."""
    outcome = _ModeOutcome(settings_exist=os.path.exists(shared_settings))
    if arguments.execute_inplace:
        project_path = arguments.project_root
        ret = execute_configuration(
            arguments, project_path, config, shared_settings, compile_sh, thread_count, arguments.timeout_compilation
        )
        outcome.compile_successful = ret is not None and ret[0] == 0
    else:
        key = BuildKey(
            os.path.basename(config),
            mode,
            tuple(resolve_requested_suggestions(arguments, arguments.dot_dp, log_skipped=False)),
        )

        def application_failed(tree: str, result: PatchApplicationResult) -> None:
            print("WARNING: " + result.summary())
            print("Skipping this run: executing the copy would measure the UNMODIFIED code.")
            record_skipped_execution(
                arguments, tree, config, shared_settings, os.path.join(config, "execute.sh"), thread_count, result
            )

        with build_lock(arguments, key):
            build = ensure_build(
                arguments,
                key,
                config,
                shared_settings,
                compile_sh,
                thread_count,
                BuildPolicy(arguments.build_policy),
                arguments.timeout_compilation,
                message=print,
                on_application_failure=application_failed,
            )
            if build.result == BuildResult.UNAVAILABLE:
                print("ERROR: " + build.message)
            outcome.compile_successful = build.usable
            if build.tree is not None and build.record is not None and build.usable and not arguments.build_only:
                _execute_and_validate(
                    arguments,
                    build.tree,
                    config,
                    mode,
                    shared_settings,
                    thread_count,
                    execution_time_regex,
                    outcome,
                    build.record,
                )
        return outcome

    if outcome.compile_successful and not arguments.build_only:
        _execute_and_validate(
            arguments, project_path, config, mode, shared_settings, thread_count, execution_time_regex, outcome
        )
    return outcome


def _execute_and_validate(
    arguments: ProjectManagerArguments,
    project_path: str,
    config: str,
    mode: str,
    shared_settings: str,
    thread_count: int,
    execution_time_regex: Optional[str],
    outcome: _ModeOutcome,
    build: Optional[BuildRecord] = None,
) -> None:
    """Run execute.sh of ``config`` in the compiled ``project_path`` and, for seq and par, validate its output.

    ``build`` is the build ``project_path`` belongs to, None for the project root (``--inplace``)."""
    repetitions = repetitions_for_mode(mode, arguments.execution_repetitions)
    if build is None:
        ret = execute_configuration(
            arguments,
            project_path,
            config,
            shared_settings,
            os.path.join(config, "execute.sh"),
            thread_count,
            arguments.timeout_execution,
            execution_time_regex=execution_time_regex,
            # only seq and par are repeated; dp and hd are profiling runs
            repetitions=repetitions,
        )
    else:
        ret, run = execute_in_build(
            arguments,
            build,
            config,
            shared_settings,
            thread_count,
            arguments.timeout_execution,
            execution_time_regex,
            repetitions,
        )
        if run is not None:
            print("Run " + run.run_id + ": results in " + run.dot_discopop)
    outcome.execute_successful = ret is not None and ret[0] == 0

    # optional output validation (auto-run when validate.sh exists);
    # no validate.sh => execute.sh alone decides correctness
    if mode in _VALIDATED_MODES and outcome.execute_successful:
        validation = run_validation_phase(
            arguments,
            project_path,
            config,
            shared_settings,
            thread_count,
            timeout_compilation=arguments.timeout_compilation,
            timeout_validation=arguments.timeout_validation,
        )
        if validation.compile_required and build is not None:
            # the validation build overwrote the build of the tree: the next run has to compile again
            invalidate_build(arguments.project_dir, BuildKey(build.configuration, build.mode, tuple(build.suggestions)))
        outcome.validate_compile_successful = not validation.compile_required or validation.compile_successful
        outcome.validate_successful = validation.verdict(outcome.execute_successful)


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

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The discopop_patch_repair driver.

The run has two phases. The **discovery** phase asks the autotuner, once, which of the
considered suggestions build and which do not; the **repair** phase then works through
the failures, handing each one to an LLM agent and verifying what comes back.

Discovery is deliberately a separate phase and a separate invocation: ``-A 0`` already
compiles every candidate individually, so one run answers the question for all of them,
and only the far smaller set of failures costs a per-suggestion invocation afterwards.
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

from discopop_library.FolderStructure.setup import setup_patch_repair
from discopop_library.PatchRepair import llm_config
from discopop_library.PatchRepair.PatchRepairArguments import PatchRepairArguments
from discopop_library.PatchRepair.backups import restore_patch_sets
from discopop_library.PatchRepair.candidates import Candidate, collect_candidates
from discopop_library.PatchRepair.compilation import CompileCheckError, CompileReport, run_compile_check
from discopop_library.ProjectManager.configurations.execution import read_applied_suggestions
from discopop_library.PatchRepair.results import (
    STATUS_FAILED,
    STATUS_NOT_APPLIED,
    STATUS_OK,
    STATUS_REPAIRED,
    STATUS_UNREACHABLE,
    ProgressReporter,
    ResultsWriter,
    SuggestionRecord,
)

logger = logging.getLogger("PatchRepair")

# Process exit codes. Anything non-zero means the run did not do what it set out to do;
# a suggestion that simply could not be repaired is not an error of the tool.
EXIT_OK = 0
EXIT_ERROR = 1


def run(arguments: PatchRepairArguments) -> int:
    setup_patch_repair(arguments.dot_dp_path)

    applied = read_applied_suggestions(arguments.dot_dp_path)
    if applied:
        # Both a repair and a restore replace patch files, and the applicator rolls a
        # suggestion back with the patch that is on disk *then*: replacing the patch of
        # an applied suggestion leaves it impossible to remove. The compile checks would
        # also build every candidate on top of the already patched sources.
        print(
            "ERROR: suggestion(s) " + str(sorted(applied)) + " are currently applied to the project sources.\n"
            "Roll them back first (discopop_patch_applicator -C), then run the repair again."
        )
        return EXIT_ERROR

    if arguments.restore:
        restored = restore_patch_sets(arguments.patch_repair_path, arguments.patch_generator_path)
        if restored:
            print("Restored " + str(len(restored)) + " patch set(s): " + str(restored))
        else:
            print("Nothing to restore: no backups found in " + arguments.patch_repair_path + ".")
        return EXIT_OK

    start_time = time.time()
    reporter = ProgressReporter(os.path.join(arguments.patch_repair_path, "progress.jsonl"))
    results = ResultsWriter(os.path.join(arguments.patch_repair_path, "results.json"))
    try:
        return _run(arguments, reporter, results, start_time)
    finally:
        reporter.close()


def _run(
    arguments: PatchRepairArguments,
    reporter: ProgressReporter,
    results: ResultsWriter,
    start_time: float,
) -> int:
    candidates = collect_candidates(arguments)
    if not candidates:
        print("No suggestions to consider.")
        reporter.start([], arguments.backend, arguments.model, arguments.dry_run)
        reporter.done(0, 0, 0, time.time() - start_time)
        return EXIT_OK

    reporter.start([c.suggestion_id for c in candidates], arguments.backend, arguments.model, arguments.dry_run)
    print("Considering " + str(len(candidates)) + " suggestion(s): " + str([c.suggestion_id for c in candidates]))

    print("Checking which suggestions compile...")
    try:
        report = run_compile_check(arguments, [c.suggestion_id for c in candidates])
    except CompileCheckError as error:
        print("ERROR: " + str(error))
        return EXIT_ERROR

    if not report.reference_built:
        # Every candidate failure is inconclusive in this case: nothing can be blamed on
        # a patch when the unmodified project does not build either. Asking an agent to
        # repair patches against that would be asking it to fix the wrong thing.
        print(
            "ERROR: the project does not build without any suggestion applied.\n"
            "Fix the build first -- no patch can be blamed for a failure the "
            "unmodified code produces as well."
        )
        reporter.discovery([], [], [], reference_built=False)
        return EXIT_ERROR

    unchecked = sorted(c.suggestion_id for c in candidates if c.suggestion_id not in report.outcomes)
    if unchecked:
        # Should not happen now that the check is restricted to exactly these ids, but a
        # candidate without an outcome would otherwise vanish from the run without trace.
        print("WARNING: the compile check reported nothing for suggestion(s) " + str(unchecked) + ".")

    reporter.discovery(
        report.building(),
        report.failing(),
        sorted(sid for sid, outcome in report.outcomes.items() if not outcome.applied),
        reference_built=True,
    )
    _record_healthy_suggestions(candidates, report, results)

    to_repair = [c for c in candidates if c.suggestion_id in set(report.failing())]
    print(
        "Compiles: "
        + str(len(report.building()))
        + " | does not compile: "
        + str(len([c for c in to_repair if report.outcomes[c.suggestion_id].applied]))
        + " | patches not applicable: "
        + str(len([c for c in to_repair if not report.outcomes[c.suggestion_id].applied]))
    )

    repairable = [c for c in to_repair if report.outcomes[c.suggestion_id].applied]
    if not repairable:
        print("Nothing to repair.")
        reporter.done(0, 0, len(candidates), time.time() - start_time)
        return EXIT_OK

    for candidate in repairable:
        outcome = report.outcomes[candidate.suggestion_id]
        print("  suggestion " + str(candidate.suggestion_id) + ": " + (outcome.first_error() or "build failed"))

    try:
        profile = _resolve_profile(arguments)
    except ValueError as error:
        # Reported here rather than up front: the discovery pass is useful on its own,
        # and a run that finds nothing to repair never needed an agent at all.
        print("ERROR: " + str(error))
        return EXIT_ERROR
    for warning in llm_config.check_connection(profile):
        print("WARNING: " + warning)
    print("Repairing with " + llm_config.describe_connection(profile) + ".")

    repaired, failed, unreachable = _repair_all(arguments, repairable, report, reporter, results, profile)

    duration = time.time() - start_time
    reporter.done(repaired, failed, len(candidates), duration, unreachable=unreachable)
    print("##############################")
    print("Repaired: " + str(repaired))
    print("Not repaired: " + str(failed))
    if unreachable:
        # Named rather than folded into "not repaired": these suggestions were never
        # judged by a model, so the run says nothing about them -- and the thing to fix
        # is the agent, not the prompt or the budget.
        print("Agent unreachable: " + str(unreachable) + " (no answer; not a failed repair)")
    print("Time: " + str(round(duration, 1)) + "s")
    print("##############################")
    return EXIT_OK


def _record_healthy_suggestions(candidates: List[Candidate], report: CompileReport, results: ResultsWriter) -> None:
    """Record the suggestions that need no repair, so results.json describes the whole run."""
    building = set(report.building())
    for candidate in candidates:
        outcome = report.outcomes.get(candidate.suggestion_id)
        if outcome is None:
            continue
        if candidate.suggestion_id in building:
            results.record(
                SuggestionRecord(
                    suggestion_id=candidate.suggestion_id,
                    hotspot_type=candidate.hotspot_type,
                    status=STATUS_OK,
                )
            )
        elif not outcome.applied:
            # Nothing was built, so there is no compiler error to repair: the patches
            # themselves do not apply, which is a different failure with a different fix.
            results.record(
                SuggestionRecord(
                    suggestion_id=candidate.suggestion_id,
                    hotspot_type=candidate.hotspot_type,
                    status=STATUS_NOT_APPLIED,
                    first_error="the generated patches could not be applied",
                )
            )


def _resolve_profile(arguments: PatchRepairArguments) -> Dict[str, Any]:
    """The connection this run drives the agent through."""
    config_path = arguments.llm_config or llm_config.default_config_path(arguments.patch_repair_path)
    config = llm_config.load_config(config_path)
    return llm_config.resolve_connection(
        config,
        name=arguments.connection,
        backend_override=arguments.backend,
        model_override=arguments.model,
    )


def _repair_all(
    arguments: PatchRepairArguments,
    repairable: List[Candidate],
    report: CompileReport,
    reporter: ProgressReporter,
    results: ResultsWriter,
    profile: Dict[str, Any],
) -> "tuple[int, int, int]":
    """Hand every failing suggestion to the agent.

    Returns ``(repaired, failed, unreachable)``. The last is counted separately
    because "the agent could not be reached" is not a statement about the model, and
    folding it into ``failed`` would report an outage as a model that cannot fix
    patches.
    """
    # Imported here so the discovery phase above stands on its own: a run that finds
    # nothing to repair never loads the agent machinery at all.
    from discopop_library.PatchRepair.loop import repair_suggestion

    repaired = 0
    failed = 0
    unreachable = 0
    for candidate in repairable:
        record = repair_suggestion(arguments, candidate, report.outcomes[candidate.suggestion_id], reporter, profile)
        results.record(record)
        # Counted by what the record says rather than by "not failed": a status this
        # loop does not know about must never be added to the repaired total.
        if record.status == STATUS_REPAIRED:
            repaired += 1
        elif record.status == STATUS_UNREACHABLE:
            unreachable += 1
        else:
            failed += 1
        if arguments.max_repairs and repaired >= arguments.max_repairs:
            logger.info("Reached --max-repairs; stopping.")
            break
    return repaired, failed, unreachable

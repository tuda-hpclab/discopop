# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from typing import List, Optional


class ExecutionResult(object):
    runtime: float
    return_code: int
    result_valid: bool
    thread_sanitizer: bool
    # True when at least one of the requested suggestions never reached the code. Such
    # a configuration is not a measurement of the suggestions it is labelled with --
    # it would be a measurement of the unmodified code -- so it is never executed and
    # must never be accepted as a search result.
    application_failed: bool
    failed_suggestions: List[int]
    # Wall clock duration of the run, which is what ``runtime`` holds unless the
    # configuration asked for the execution time to be read from the program's own
    # output. The two must not be confused: ``runtime`` is what candidates are
    # ranked by, but anything bounding the *process* -- above all the per-candidate
    # timeout -- has to be expressed in wall clock terms, since a reported time
    # covers only part of the run.
    wall_clock_runtime: float
    # True when the configuration was built but deliberately not run (--compile-only).
    # ``runtime`` is then 0.0 and carries no information: it is not a fast run, it is
    # no run at all. Consumers that report or rank runtimes must check this first.
    compiled_only: bool
    # Every measurement the run produced, when it was repeated. ``runtime`` is their
    # median, so the spread between them says how much of a difference between two
    # candidates this measurement could actually have resolved. Empty when the run
    # was not measured at all (--compile-only, a failed application).
    repetition_runtimes: List[float]

    def __init__(
        self,
        runtime: float,
        return_code: int,
        result_valid: bool,
        thread_sanitizer: bool,
        application_failed: bool = False,
        failed_suggestions: Optional[List[int]] = None,
        wall_clock_runtime: Optional[float] = None,
        compiled_only: bool = False,
        repetition_runtimes: Optional[List[float]] = None,
    ):
        self.runtime = runtime
        # defaults to runtime, which is exactly right when no execution time was
        # read from the program's output
        self.wall_clock_runtime = runtime if wall_clock_runtime is None else wall_clock_runtime
        self.return_code = return_code
        self.result_valid = result_valid
        self.thread_sanitizer = thread_sanitizer
        self.application_failed = application_failed
        self.failed_suggestions = [] if failed_suggestions is None else failed_suggestions
        self.compiled_only = compiled_only
        self.repetition_runtimes = [] if repetition_runtimes is None else repetition_runtimes

    def __str__(self) -> str:
        if self.compiled_only:
            return "compiled only, not executed. code: " + str(self.return_code)
        res = (
            ""
            + "time: "
            + str(self.runtime)
            + " code: "
            + str(self.return_code)
            + " valid: "
            + str(self.result_valid)
            + " TSAN: "
            + str(self.thread_sanitizer)
        )
        if len(self.repetition_runtimes) > 1 and self.return_code == 0:
            # What the reported time rests on: a search that accepted a suggestion
            # by a margin smaller than this spread decided on noise. Not claimed for
            # a failed run: its runtime is the failing repetition's own, not a
            # median -- the loop stops at the first failure.
            res += (
                " (median of "
                + str(len(self.repetition_runtimes))
                + ": "
                + str(round(min(self.repetition_runtimes), 4))
                + "-"
                + str(round(max(self.repetition_runtimes), 4))
                + ")"
            )
        if self.application_failed:
            res += " NOT APPLIED: " + str(self.failed_suggestions)
        return res

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Measuring a configuration more than once, and picking the run that counts.

A single run of ``execute.sh`` is one sample of a noisy quantity. Whatever else
is on the machine -- another benchmark, a background rebuild, the page cache in
whatever state the previous run left it -- lands in that one number, and two
measurements of the *same* code can then differ by more than the effect being
looked for. Repeating the run and reporting the median is what makes the
difference between two configurations readable again.

``execute_configuration`` therefore accepts a repetition count, and only for
``execute.sh``: ``compile.sh`` and ``validate.sh`` go through the same function
but produce no measurement, so repeating them would only cost time.

Of the repetitions, one is singled out as the *representative* -- the run whose
time is the median (the lower of the two middle values when the count is even).
Its wall clock time, console output, return code and time source are what get
recorded, rather than a median computed separately per field. The record is then
internally consistent: the stored wall clock time really is the wall clock time
of the run whose time is reported, and the stored output really is the output
that time was read from. Every individual measurement is kept alongside it under
``repetition_times``, so a spread can be computed afterwards without re-running
anything.

Nothing about the shape of a recorded run changes: ``time`` still holds the
measurement of interest, which is what the reports, the plots, the auto-tuner
and the benchmark harnesses read.
"""

from typing import Optional, Sequence

# The value meaning "do not repeat": one run, recorded exactly as it was before
# this option existed. It is what ``execute_configuration`` falls back to when a
# caller says nothing, and what a mode that measures nothing always gets.
SINGLE_MEASUREMENT = 1

# What the command line and the graphical interface start at.
#
# Measured runs are repeated by default, because the noise they carry is the whole
# reason the option exists and a runtime nobody asked to be trustworthy is still
# read as one. Three is the smallest count at which a median can ignore an
# outlier: two runs have no middle value, and every further pair buys less than it
# costs, since one program run is added per reported number.
#
# The auto-tuner is not repeated by default. It performs one program execution per
# *candidate*, so the same count there multiplies the runtime of a whole search
# rather than of one reported number -- and ``--noise-threshold`` already keeps
# noise out of the search's decisions. Raising it is worth it only when the
# machine's noise is comparable to that threshold.
DEFAULT_MEASURED_REPETITIONS = 3
DEFAULT_TUNING_REPETITIONS = SINGLE_MEASUREMENT

# How the reported time was chosen among the repetitions; stored as
# "time_aggregate" next to the measurement so a consumer need not infer it from
# the number of repetitions. Only ``median`` says that ``time`` is an aggregate:
# a run that failed reports the failing repetition's own time, and a run that was
# never started reports no time at all. Claiming "median" for either would tell a
# reader that a value had been averaged over the noise when it had not.
TIME_AGGREGATE_MEDIAN = "median"
TIME_AGGREGATE_FAILED_RUN = "failed_run"
TIME_AGGREGATE_NOT_MEASURED = "not_measured"

# The execution modes whose ``execute.sh`` run measures a runtime. ``dp`` and
# ``hd`` build and run instrumented binaries whose output feeds the Explorer and
# the hotspot analysis; their duration is a byproduct, so repeating them would
# multiply the profiling cost without improving any measurement.
MEASURED_MODES = ("seq", "par")


def validate_repetitions(value: int) -> Optional[str]:
    """An error message describing why ``value`` is unusable, or None if it is fine.

    Zero repetitions would mean "measure nothing", which no caller can do
    anything with -- there would be no time to report -- so it is rejected here
    rather than silently treated as one.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return "expected a whole number of repetitions, got '" + str(value) + "'"
    if value < 1:
        return "a configuration must be executed at least once, got " + str(value)
    return None


def select_representative(times: Sequence[float]) -> int:
    """Index of the repetition whose time is the median of ``times``.

    With an even number of repetitions there is no single middle value; the lower
    of the two is taken, because it is an actual run that happened and therefore
    has an output, a return code and a wall clock time to report alongside it.
    Their average would have none of those.
    """
    if not times:
        raise ValueError("cannot pick a representative among no repetitions")
    order = sorted(range(len(times)), key=lambda index: times[index])
    return order[(len(order) - 1) // 2]


def repetitions_for_mode(mode: str, repetitions: int) -> int:
    """How often ``mode``'s ``execute.sh`` should be run.

    The decision is made here rather than at each call site because the command
    line and the graphical interface both have to make it, and two copies of it
    could drift apart -- silently, since the result is a count and not an error.
    """
    return repetitions if mode in MEASURED_MODES else SINGLE_MEASUREMENT

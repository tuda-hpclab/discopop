# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

from tabulate import tabulate  # type: ignore
from discopop_library.EmpiricalAutotuning.output.progress import DebugStatEntry


import logging
from typing import List


def _not_applied_cell(stats: DebugStatEntry) -> str:
    """The "not applied" column: which requested suggestions never reached the code.

    A non-empty cell means the row is not a measurement of its suggestion set -- the
    configuration was never run, because its code was still the unmodified original.
    """
    failed = list(stats[6]) if len(stats) > 6 else []
    return str(failed) if failed else "-"


def show_debug_stats(debug_stats: List[DebugStatEntry], logger: logging.Logger) -> None:
    # show debug stats
    table = []
    headers = ["time (s)", "applied suggestions", "return code", "result valid", "TSAN", "not applied", "path"]

    for stats in sorted(debug_stats, key=lambda x: (x[1]), reverse=True):
        row = []
        row.append(str(round(stats[1], 5)))
        row.append(str(stats[0]))
        row.append(str(stats[2]))
        row.append(str(stats[3]))
        row.append(str(stats[4]))
        row.append(_not_applied_cell(stats))
        row.append(str(stats[5]))
        table.append(row)
    logger.debug("Configuration measurements:\n" + tabulate(table, headers, tablefmt="github"))


def show_info_stats(debug_stats: List[DebugStatEntry], logger: logging.Logger) -> None:
    # show debug stats
    table = []
    headers = ["time (s)", "applied suggestions", "return code", "result valid", "TSAN", "not applied"]

    for stats in sorted(debug_stats, key=lambda x: (x[1]), reverse=True):
        row = []
        row.append(str(round(stats[1], 5)))
        row.append(str(stats[0]))
        row.append(str(stats[2]))
        row.append(str(stats[3]))
        row.append(str(stats[4]))
        row.append(_not_applied_cell(stats))
        table.append(row)
    logger.info("Configuration measurements:\n" + tabulate(table, headers, tablefmt="github"))

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Immutable snapshots of what a GUI panel asks a background job to do.

A panel reads its widgets and Tk variables on the main thread into one of these objects and hands only
the snapshot to the worker thread; the worker never touches a widget or a Tk variable.
"""

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class ExplorerRequest:
    enable_patterns: str
    jobs: str
    ignore_dependency_states: bool
    # open the explorer's own graph visualizer (``--visualize``); the Tk GUI runs a visualized run in-process instead
    visualize: bool = False


@dataclass(frozen=True)
class AutotunerRequest:
    configuration: str
    hotspot_types: str
    threads: str
    repetitions: int
    # set when the repetition field held an unusable value, to be reported to the user
    repetitions_warning: Optional[str]
    algorithm: str
    log_level: str
    # "evaluate" or the search mode
    mode: str
    evaluate_ids: Tuple[str, ...]
    # None: the whole search space
    search_space_ids: Optional[Tuple[str, ...]]


@dataclass(frozen=True)
class PatchRepairRequest:
    configuration: str
    hotspot_types: str
    prompts: int
    retries: int
    agent_timeout: int
    log_level: str
    backend: str
    model: str
    dry_run: bool
    # None: all suggestions
    suggestion_ids: Optional[Tuple[str, ...]]

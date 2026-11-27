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

from discopop_library.PatchRepair.PatchRepairArguments import DEFAULT_HOTSPOT_TYPES


@dataclass(frozen=True)
class ExplorerRequest:
    enable_patterns: str
    jobs: str
    ignore_dependency_states: bool
    # open the explorer's own graph visualizer (``--visualize``); the Tk GUI runs a visualized run in-process instead
    visualize: bool = False
    # also write explorer/unsure_suggestions.json (``--unsure-suggestions``), the input of the blocker resolution
    unsure_suggestions: bool = False


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
    # compile the seq / par candidates one after the other in the kept build tree of their mode (False: a copy of
    # the project per candidate, --no-kept-build-trees)
    kept_build_trees: bool = True


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
    # a stored connection of the LLM configuration shared with the blocker resolution; None: backend and model
    connection: Optional[str] = None


@dataclass(frozen=True)
class BlockerResolutionRequest:
    # a stored connection of the LLM configuration shared with patch repair; empty: backend and model below
    connection: str
    prompts: int
    retries: int
    agent_timeout: int
    log_level: str
    backend: str
    # empty: the backend's default model
    model: str
    review: bool
    # False: --reject-rounding
    accept_rounding: bool
    # False: --no-discopop-tools
    discopop_tools: bool
    # 0: no limit
    max_suggestions: int
    # None: all unsure suggestions
    suggestion_ids: Optional[Tuple[str, ...]]
    # comma separated (yes, maybe, no): the others are skipped, the explicit ids above are checked regardless
    hotspot_types: str = DEFAULT_HOTSPOT_TYPES
    # False: --no-use-approved (the approvals stay unused until "Use approved suggestions"); True: in use when it ends
    use_approved: bool = True

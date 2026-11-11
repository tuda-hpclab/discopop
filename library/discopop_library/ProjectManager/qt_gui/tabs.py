# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The names of the tabs of the main window (the keys of :class:`TabHost`)."""

from discopop_library.ProjectManager.services.workflow_status import (
    STAGE_AUTOTUNING,
    STAGE_EDITOR,
    STAGE_EXECUTE,
    STAGE_HOTSPOT,
    STAGE_PATCH_REPAIR,
    STAGE_PATTERN_DETECTION,
    STAGE_PROFILING,
    STAGE_REPORT,
    STAGE_SETUP,
)

# the tabs are the stages of the workflow (services/workflow_status.py defines the keys, toolkit-free)
TAB_SETUP = STAGE_SETUP
TAB_EDITOR = STAGE_EDITOR
TAB_PROFILING = STAGE_PROFILING
TAB_EXECUTE = STAGE_EXECUTE
TAB_REPORT = STAGE_REPORT
TAB_HOTSPOT = STAGE_HOTSPOT
TAB_PATTERN_DETECTION = STAGE_PATTERN_DETECTION
TAB_PATCH_REPAIR = STAGE_PATCH_REPAIR
TAB_AUTOTUNING = STAGE_AUTOTUNING
# the order of the tabs, as in the sidebar: the build of the project and its configurations first; profiling and
# hotspots are measured before, and feed into, pattern detection and the autotuner; patch repair sits between them, a
# suggestion that does not build is one the tuner can only record as a failure; Execute measures the configurations
# with or without the suggestions, the report shows the measurements
TAB_ORDER = (
    TAB_SETUP,
    TAB_EDITOR,
    TAB_PROFILING,
    TAB_HOTSPOT,
    TAB_PATTERN_DETECTION,
    TAB_PATCH_REPAIR,
    TAB_AUTOTUNING,
    TAB_EXECUTE,
    TAB_REPORT,
)

# the workflow sidebar: sections of (tab, title) in display order; the setup first, the results last
NAV_SECTIONS = (
    ("Setup", ((TAB_SETUP, "Project Setup"), (TAB_EDITOR, "Configuration Setup"))),
    (
        "Pipeline",
        (
            (TAB_PROFILING, "Profiling"),
            (TAB_HOTSPOT, "Hotspots"),
            (TAB_PATTERN_DETECTION, "Pattern Detection"),
            (TAB_PATCH_REPAIR, "Patch Repair"),
            (TAB_AUTOTUNING, "Autotuning"),
            (TAB_EXECUTE, "Execute"),
        ),
    ),
    ("Results", ((TAB_REPORT, "Report"),)),
)

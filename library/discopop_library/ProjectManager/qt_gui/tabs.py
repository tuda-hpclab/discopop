# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""The names of the tabs of the main window (the keys of :class:`TabHost`)."""

TAB_EDITOR = "Editor"
TAB_EXECUTE = "Execute"
TAB_REPORT = "Report"
TAB_HOTSPOT = "Hotspot Detection"
TAB_PATTERN_DETECTION = "Pattern Detection"
TAB_PATCH_REPAIR = "Patch Repair"
TAB_AUTOTUNING = "Autotuning"
# the order of the tabs: hotspots are measured before, and feed into, pattern detection and the autotuner; patch
# repair sits between them, a suggestion that does not build is one the tuner can only record as a failure
TAB_ORDER = (TAB_EDITOR, TAB_EXECUTE, TAB_REPORT, TAB_HOTSPOT, TAB_PATTERN_DETECTION, TAB_PATCH_REPAIR, TAB_AUTOTUNING)

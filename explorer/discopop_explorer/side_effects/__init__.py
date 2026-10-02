# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Observed side effects of functions (see DESIGN_get_side_effects.md).

``export`` runs inside the explorer and writes ``side_effects.json.gz``; ``schema``
reads it back, and ``analysis`` answers per-function queries from it. ``schema``,
``result`` and ``analysis`` import nothing heavy (no TaskGraph, no PET), so that
the MCP server can use them without loading the explorer's data structures.
"""

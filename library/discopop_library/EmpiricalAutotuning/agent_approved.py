# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""Suggestions approved by an LLM agent (discopop_suggestion_check) as candidates of the search, on request only.

An approval rests on an agent's judgement, so the search does not see it unless ``--include-agent-approved`` is given.
Then the suggestions published to ``patch_generator/`` (``discopop_suggestion_check --publish-approved``, recognised by
their marker file) join the Explorer's do-all suggestions as candidates: the search measures them like the others and
only keeps those that pay off and keep the validation passing.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

from discopop_library.SuggestionCheck.publish import published_ids
from discopop_library.SuggestionCheck.unsure import UNSURE_SUGGESTIONS_FILE


def add_published_approvals(detection_result: Any, dot_dp_path: str, logger: logging.Logger) -> List[int]:
    """Add the published approvals to ``detection_result.patterns.do_all`` (in memory only); returns their ids."""
    from discopop_explorer.pattern_detectors.do_all_detector import DoAllInfo

    ids = published_ids(dot_dp_path)
    if not ids:
        return []
    path = os.path.join(dot_dp_path, UNSURE_SUGGESTIONS_FILE)
    entries: Dict[int, Dict[str, Any]] = {}
    try:
        with open(path) as f:
            entries = {int(e["pattern_id"]): e for e in json.load(f).get("suggestions", [])}
    except (OSError, ValueError, KeyError):
        logger.warning("Agent-approved suggestions not included: cannot read " + path)
        return []
    taken = set(detection_result.patterns.get_pattern_ids())
    added: List[int] = []
    for pattern_id in ids:
        entry = entries.get(pattern_id)
        if entry is None or pattern_id in taken:
            logger.warning(
                "Agent-approved suggestion " + str(pattern_id) + " is not included: no matching unsure suggestion"
            )
            continue
        # the entry is the serialised DoAllInfo of the unsure loop; the patch exists in patch_generator/<id>
        info = DoAllInfo.__new__(DoAllInfo)
        info.__dict__.update({k: v for k, v in entry.items() if not k.startswith("_")})
        info.pattern_id = pattern_id
        info.applicable_pattern = True
        info.standalone_pattern = True
        detection_result.patterns.do_all.append(info)
        added.append(pattern_id)
    if added:
        logger.info("Included agent-approved suggestions in the search space: " + str(added))
    return added

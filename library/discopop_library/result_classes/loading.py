# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Loading the explorer's ``detection_result_dump.json`` without the callpath tree of the PET.

``PEGraphX.callpath_tree`` holds every callpath state the profiler recorded (``stateID_to_callpath_mapping.txt``): only
the task detection reads it, while the explorer runs. In the dump it can be nearly all of the file (relearn: 17.9 of
18.3 GB, 236 million states, ~160 GB of memory when decoded), so the tools that read the patterns and the loops of a
dump (the autotuner, the Amdahl bounds) leave it out: the file is streamed, the value of ``"callpath_tree"`` is
replaced by ``{}`` and only the rest is decoded.

The cut keeps the references (``py/id``) of the rest valid: jsonpickle numbers the dicts, lists and objects in the
order it restores them, and the tree is a single dict (replaced by a single dict) whose values are tuples of strings,
which get no number. Its entries are ``"<state>": {"py/tuple": ["<parent>", "<label>"]}`` with labels free of
whitespace, brackets and braces (function names, ``call_<id>``), so its end is the first ``]}}``. If the text after
the cut does not continue the JSON as expected, the whole file is decoded as before.
"""

import logging
from typing import Any, Optional, Tuple

import jsonpickle  # type: ignore

_TREE_KEY = b'"callpath_tree": '
_TREE_END = b"]}}"
_CHUNK = 1 << 26

logger = logging.getLogger("DetectionResultLoading")


def read_without_callpath_tree(path: str, chunk_size: int = _CHUNK) -> Tuple[str, bool]:
    """The text of the dump with ``{}`` as the value of ``"callpath_tree"``, and whether a tree was left out.

    The text is returned unchanged (and False) if there is no such key or its value does not end as expected.
    """
    kept = bytearray()
    with open(path, "rb") as file:
        buffer = b""
        # copy up to the key
        while True:
            chunk = file.read(chunk_size)
            buffer += chunk
            index = buffer.find(_TREE_KEY)
            if index >= 0:
                break
            if not chunk:
                kept += buffer
                return kept.decode("utf-8"), False
            overlap = len(_TREE_KEY) - 1
            kept += buffer[:-overlap]
            buffer = buffer[-overlap:]
        start = index + len(_TREE_KEY)
        kept += buffer[:start]
        buffer = buffer[start:]
        while len(buffer) < 2:
            chunk = file.read(chunk_size)
            if not chunk:
                return _unchanged(path), False
            buffer += chunk
        if buffer.startswith(b"{}"):
            # an empty tree: nothing to leave out
            kept += buffer
            kept += file.read()
            return kept.decode("utf-8"), False
        if not buffer.startswith(b"{"):
            return _unchanged(path), False
        # skip to the end of the tree
        while True:
            index = buffer.find(_TREE_END)
            if index >= 0:
                break
            chunk = file.read(chunk_size)
            if not chunk:
                return _unchanged(path), False
            buffer = buffer[-(len(_TREE_END) - 1) :] + chunk
        rest = buffer[index + len(_TREE_END) :]
        while not rest.strip():
            chunk = file.read(chunk_size)
            if not chunk:
                break
            rest += chunk
        if rest.lstrip()[:1] not in (b",", b"}"):
            return _unchanged(path), False
        kept += b"{}"
        kept += rest
        kept += file.read()
    return kept.decode("utf-8"), True


def _unchanged(path: str) -> str:
    logger.warning("The callpath tree of " + path + " could not be left out: decoding the whole file.")
    with open(path, "r") as file:
        return file.read()


def load_detection_result(path: str) -> Any:
    """The ``DetectionResult`` of a ``detection_result_dump.json``, whose PET has an empty ``callpath_tree``."""
    text, left_out = read_without_callpath_tree(path)
    try:
        return jsonpickle.decode(text, keys=True)
    except Exception:  # noqa: BLE001
        if not left_out:
            raise
    full: Optional[str] = _unchanged(path)
    return jsonpickle.decode(full, keys=True)

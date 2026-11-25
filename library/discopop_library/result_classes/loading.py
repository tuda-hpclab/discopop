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
replaced by ``{}`` and only the rest is decoded. The loaded PET holds a ``LeftOutCallpathTree`` instead, which fails
on any use, so code that needs the tree cannot silently work with none.

The cut keeps the references (``py/id``) of the rest valid: jsonpickle numbers the dicts, lists and objects in the
order it restores them, and the tree is a single dict (replaced by a single dict) whose values are tuples of strings,
which get no number. Its entries are ``"<state>": {"py/tuple": ["<parent>", "<label>"]}`` with labels free of
whitespace, brackets and braces (function names, ``call_<id>``), so its end is the first ``]}}``. The text left out is
checked to hold such entries only: every ``[`` opens a tuple and every ``{`` but the tree's own opens a tuple value
(a reference, an object, a list or a dict as a value would break the cut; the tags of jsonpickle are keys of dicts).
If it does not, or the text after the cut does not continue the JSON as expected, the whole file is decoded as before.
"""

import logging
from typing import Any, NoReturn, Tuple

import jsonpickle  # type: ignore

_TREE_KEY = b'"callpath_tree": '
_TREE_END = b"]}}"
_TUPLE_VALUE = b'{"py/tuple": ['
_CHUNK = 1 << 26

logger = logging.getLogger("DetectionResultLoading")


class LeftOutCallpathTree(dict):  # type: ignore[type-arg]
    """The ``callpath_tree`` of a PET loaded without it: every read fails instead of finding no state."""

    def _fail(self) -> NoReturn:
        raise RuntimeError(
            "The callpath tree of this detection result was left out when it was loaded "
            "(discopop_library.result_classes.loading); decode the dump with jsonpickle to use it."
        )

    def __getitem__(self, key: Any) -> NoReturn:
        self._fail()

    def __contains__(self, key: Any) -> NoReturn:
        self._fail()

    def __iter__(self) -> NoReturn:
        self._fail()

    def __len__(self) -> NoReturn:
        self._fail()

    def get(self, *args: Any, **kwargs: Any) -> NoReturn:
        self._fail()

    def keys(self) -> NoReturn:
        self._fail()

    def values(self) -> NoReturn:
        self._fail()

    def items(self) -> NoReturn:
        self._fail()


def _other_braces(text: bytes, end: int) -> int:
    """The number of ``{`` in ``text[:end]``, a piece of the tree's text not splitting what is counted, that open no
    tuple value: 0 for entries of the tree, 1 for the piece holding its opening brace; -1 if it holds a ``[`` that opens
    no tuple value. Every other jsonpickle tag (``{"py/id": 3}``, ``{"py/object": ...}``) opens a dict, so it is
    counted. Counted in place: the tree can be most of a file of many GB."""
    values = text.count(_TUPLE_VALUE, 0, end)
    if text.count(b"[", 0, end) != values:
        return -1
    return text.count(b"{", 0, end) - values


def read_without_callpath_tree(path: str, chunk_size: int = _CHUNK) -> Tuple[str, bool]:
    """The text of the dump with ``{}`` as the value of ``"callpath_tree"``, and whether a tree was left out.

    The text is returned unchanged (and False) if there is no such key or its value is not a tree as expected.
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
                return _whole_file(path, "it ends after the key"), False
            buffer += chunk
        if buffer.startswith(b"{}"):
            # an empty tree: nothing to leave out
            kept += buffer
            kept += file.read()
            return kept.decode("utf-8"), False
        if not buffer.startswith(b"{"):
            return _whole_file(path, "its value is no dict"), False
        # skip to the end of the tree, checking what is left out: the tree's opening brace and tuple values only. A
        # piece is checked up to its last "]", which splits nothing that is counted and keeps a "]}}" in the rest
        braces = 0
        while True:
            index = buffer.find(_TREE_END)
            if index >= 0:
                counted = _other_braces(buffer, index)
                if counted < 0 or braces + counted != 1:
                    return _whole_file(path, "it holds more than tuples of strings"), False
                break
            checked = buffer.rfind(b"]")
            if checked > 0:
                counted = _other_braces(buffer, checked)
                if counted < 0:
                    return _whole_file(path, "it holds more than tuples of strings"), False
                braces += counted
                buffer = buffer[checked:]
            chunk = file.read(chunk_size)
            if not chunk:
                return _whole_file(path, "its end was not found"), False
            buffer += chunk
        rest = buffer[index + len(_TREE_END) :]
        while not rest.strip():
            chunk = file.read(chunk_size)
            if not chunk:
                break
            rest += chunk
        if rest.lstrip()[:1] not in (b",", b"}"):
            return _whole_file(path, "the text after it is unexpected"), False
        kept += b"{}"
        kept += rest
        kept += file.read()
    return kept.decode("utf-8"), True


def _whole_file(path: str, reason: str) -> str:
    logger.warning("The callpath tree of " + path + " could not be left out (" + reason + "): decoding the whole file.")
    with open(path, "r") as file:
        return file.read()


def load_detection_result(path: str) -> Any:
    """The ``DetectionResult`` of a ``detection_result_dump.json``. Its PET holds a ``LeftOutCallpathTree`` if the
    tree was left out (an empty tree stays an empty dict)."""
    text, left_out = read_without_callpath_tree(path)
    try:
        result = jsonpickle.decode(text, keys=True)
    except Exception as error:
        if left_out:
            error.add_note(
                "The callpath tree of the PET was left out before decoding "
                "(discopop_library.result_classes.loading)."
            )
        raise
    if left_out:
        result.pet.callpath_tree = LeftOutCallpathTree()
    return result

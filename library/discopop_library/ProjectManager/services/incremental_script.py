# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.


"""A proposal for ``compile_incremental.sh``, derived from a ``compile.sh``.

An incremental script continues the kept build tree: it must only *rebuild* (no clean, normally no configure step). The
proposal keeps the shebang, the environment lines (``set``, ``export``, ``cd``, assignments, ``source``) and the build
lines (``cmake --build``, ``ninja``, ``make``) and drops everything else it recognizes as configuring or cleaning. It
is a starting point for the user, who sees and saves it in the editor; nothing is written by this module. Toolkit-free.
"""

import shlex
from typing import List, Optional

HEADER_COMMENT = (
    "# Derived from compile.sh: this script continues the kept build tree and must only rebuild\n"
    "# (no clean, no rm -rf of the build directory, normally no configure step). Check it before saving.\n"
    "# CMake superbuilds (ExternalProject): build the inner project, e.g. cmake --build build/<project>-build,\n"
    "# as the outer build does not see changed sources of an external project.\n"
    "# OMP_NUM_THREADS is set to the thread count of the run, and $(nproc) honors it: use $(nproc --all) for -j.\n"
)
EMPTY_TEMPLATE = (
    "#!/bin/bash\n"
    "# Derived from compile.sh: no build line could be recognized there. Write the command that rebuilds\n"
    "# the kept build tree (e.g. cmake --build build -j, make -j, ninja -C build); it must only rebuild.\n"
    "# CMake superbuilds (ExternalProject): build the inner project, e.g. cmake --build build/<project>-build.\n"
    "# OMP_NUM_THREADS is set to the thread count of the run, and $(nproc) honors it: use $(nproc --all) for -j.\n"
)

_ENVIRONMENT_COMMANDS = {"set", "export", "cd", "source", ".", "unset"}
_BUILD_COMMANDS = {"make", "gmake", "ninja"}
_CLEAN_TARGETS = {"clean", "distclean", "mrproper", "realclean", "maintainer-clean"}
_COMPOUND_KEYWORDS = {
    "if",
    "then",
    "else",
    "elif",
    "fi",
    "for",
    "while",
    "until",
    "do",
    "done",
    "case",
    "esac",
    "{",
    "}",
}


def _join_continuations(text: str) -> List[str]:
    lines: List[str] = []
    pending = ""
    for raw in text.splitlines():
        if raw.rstrip().endswith("\\"):
            pending += raw.strip()[:-1].rstrip() + " " if pending else raw.rstrip()[:-1].rstrip() + " "
            continue
        lines.append(pending + raw.strip() if pending else raw)
        pending = ""
    if pending:
        lines.append(pending)
    return lines


def _split_commands(line: str) -> List[str]:
    """Split a line at ``&&`` and ``;`` outside quotes (a trailing comment is dropped)."""
    parts: List[str] = []
    current = ""
    quote = ""
    i = 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == quote:
                quote = ""
        elif c in "'\"":
            quote = c
        elif c == "#" and (i == 0 or line[i - 1].isspace()):
            break
        elif line.startswith("&&", i):
            parts.append(current)
            current = ""
            i += 2
            continue
        elif c == ";":
            parts.append(current)
            current = ""
            i += 1
            continue
        current += c
        i += 1
    parts.append(current)
    return [part.strip() for part in parts if part.strip()]


def _is_assignment(word: str) -> bool:
    name, sep, _value = word.partition("=")
    return bool(sep) and name.replace("_", "a").isalnum() and not name[0].isdigit()


def _target_arguments(arguments: List[str]) -> List[str]:
    """The targets of ``cmake --build`` (``--target a b``, ``-t a``, ``--target=a``)."""
    targets: List[str] = []
    taking = False
    for argument in arguments:
        if argument in ("--target", "-t"):
            taking = True
        elif argument.startswith("--target="):
            targets.append(argument.split("=", 1)[1])
        elif taking and not argument.startswith("-"):
            targets.append(argument)
        else:
            taking = False
    return targets


def _classify(command: str) -> str:
    """ "env" (keep), "build" (keep), "compound" (not handled) or "drop"."""
    try:
        words = shlex.split(command)
    except ValueError:
        return "drop"
    if not words:
        return "drop"
    if all(_is_assignment(word) for word in words):
        return "env"
    program_words = [w for w in words if not _is_assignment(w)] if _is_assignment(words[0]) else words
    # leading assignments (CC=gcc make) belong to the command
    while program_words and _is_assignment(program_words[0]):
        program_words = program_words[1:]
    program = program_words[0].rsplit("/", 1)[-1]
    arguments = program_words[1:]
    if program in _COMPOUND_KEYWORDS or program in ("[", "[[", "test"):
        return "compound" if program in _COMPOUND_KEYWORDS else "drop"
    if program in _ENVIRONMENT_COMMANDS:
        return "env"
    if program == "cmake":
        if "--build" not in arguments or "--clean-first" in arguments:
            return "drop"
        if any(argument in _CLEAN_TARGETS for argument in _target_arguments(arguments)):
            return "drop"
        return "build"
    if program in _BUILD_COMMANDS:
        if any(argument in _CLEAN_TARGETS for argument in arguments):
            return "drop"
        if program in ("make", "gmake") and any(argument in ("-B", "--always-make") for argument in arguments):
            return "drop"
        if program == "ninja" and "-t" in arguments and "clean" in arguments:
            return "drop"
        return "build"
    return "drop"


def propose_incremental_script(compile_script_text: str) -> Optional[str]:
    """A proposed ``compile_incremental.sh`` for the text of a ``compile.sh``; None if no build line is found.

    A script with shell control structures (``if``, ``for``, ...) is not proposed for, as dropping lines of a block
    would leave broken syntax.
    """
    lines = _join_continuations(compile_script_text)
    shebang = "#!/bin/bash"
    if lines and lines[0].startswith("#!"):
        shebang = lines[0].strip()
    kept: List[str] = []
    found_build = False
    for line in lines:
        if line.startswith("#!"):
            continue
        commands = _split_commands(line)
        kept_commands: List[str] = []
        for command in commands:
            kind = _classify(command)
            if kind == "compound":
                return None
            if kind == "build":
                found_build = True
            if kind in ("env", "build"):
                kept_commands.append(command)
        if kept_commands:
            kept.append(" && ".join(kept_commands))
    if not found_build:
        return None
    return shebang + "\n" + HEADER_COMMENT + "\n".join(kept) + "\n"

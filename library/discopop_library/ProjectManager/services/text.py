# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Cleaning of the console output of subprocesses for display."""

import re

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m|\x1b\[[A-Z]")


def clean_ansi_output(text: str) -> str:
    """Remove ANSI escape codes and clean up carriage returns for display."""
    text = _ANSI_ESCAPE.sub("", text)
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        if "\r" in line:
            parts = line.split("\r")
            line = parts[-1] if parts[-1] else parts[-2] if len(parts) > 1 else ""
        if line.strip():
            cleaned_lines.append(line)
    return "\n".join(cleaned_lines)

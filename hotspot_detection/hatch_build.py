# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""
PEP 517 build backend wrapper.

Checks for required system executables before delegating
all build hooks to scikit_build_core.build.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from typing import Any

from requirements import REQUIRED_EXECUTABLES, REQUIRED_EXECUTABLE_ALTERNATIVES

SUPPORTED_CLANG_VERSIONS = {19, 20, 21, 22}


def _get_clang_version(clang_path: str) -> int | None:
    """Extract the major version from a clang executable."""
    try:
        result = subprocess.run(
            [clang_path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        match = re.search(r"clang version (\d+)", result.stdout)
        if match:
            return int(match.group(1))
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return None


def _check_clang_version_requirement(alternatives: list[str]) -> bool:
    """Check if at least one clang alternative exists with a supported version."""
    for alt in alternatives:
        if alt == "clang" and shutil.which(alt):
            version = _get_clang_version(alt)
            if version and version in SUPPORTED_CLANG_VERSIONS:
                return True
        elif alt.startswith("clang-") and shutil.which(alt):
            return True
    return False


def _check_system_dependencies() -> None:
    missing_exe: list[str] = [exe for exe in REQUIRED_EXECUTABLES if shutil.which(exe) is None]

    missing_groups: list[list[str]] = [
        group for group in REQUIRED_EXECUTABLE_ALTERNATIVES if not _check_clang_version_requirement(group)
    ]

    if not missing_exe and not missing_groups:
        return

    lines = ["", "Missing executables on path:", ""]
    for exe in missing_exe:
        lines.append(f"  - executable '{exe}'")
    for group in missing_groups:
        version_note = " (version 19-22 required)" if "clang" in group[0] else ""
        lines.append(f"  - one of: {', '.join(group)}{version_note}")
    lines += [
        "",
        "Please refer to the installation instructions for prerequisites described in the README.md to prepare your environment and re-run the build.",
        "GitHub: https://github.com/discopop-project/Hotspot-Detection",
        "",
    ]
    print("\n".join(lines), file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# PEP 517 hooks — delegate everything to scikit_build_core after the check
# ---------------------------------------------------------------------------

from scikit_build_core.build import (  # noqa: E402  (import after guard logic)
    build_wheel as _build_wheel,
    build_sdist as _build_sdist,
    get_requires_for_build_wheel as _get_requires_for_build_wheel,
    get_requires_for_build_sdist as _get_requires_for_build_sdist,
)

try:
    from scikit_build_core.build import build_editable as _build_editable
    from scikit_build_core.build import get_requires_for_build_editable as _get_requires_for_build_editable
    from scikit_build_core.build import prepare_metadata_for_build_editable as _prepare_metadata_for_build_editable

    _has_editable = True
except ImportError:
    _has_editable = False

try:
    from scikit_build_core.build import prepare_metadata_for_build_wheel as _prepare_metadata_for_build_wheel

    _has_prepare_wheel = True
except ImportError:
    _has_prepare_wheel = False


def get_requires_for_build_wheel(config_settings: Any = None) -> list[str]:
    return _get_requires_for_build_wheel(config_settings)  # type: ignore


def get_requires_for_build_sdist(config_settings: Any = None) -> list[str]:
    return _get_requires_for_build_sdist(config_settings)  # type: ignore


def build_wheel(wheel_directory: str, config_settings: Any = None, metadata_directory: Any = None) -> str:
    _check_system_dependencies()
    return _build_wheel(wheel_directory, config_settings, metadata_directory)  # type: ignore


def build_sdist(sdist_directory: str, config_settings: Any = None) -> str:
    _check_system_dependencies()
    return _build_sdist(sdist_directory, config_settings)  # type: ignore


if _has_prepare_wheel:

    def prepare_metadata_for_build_wheel(metadata_directory: str, config_settings: Any = None) -> str:
        return _prepare_metadata_for_build_wheel(metadata_directory, config_settings)  # type: ignore


if _has_editable:

    def get_requires_for_build_editable(config_settings: Any = None) -> list[str]:
        raise RuntimeError(
            "Editable installs (-e flag) are not supported for discopop-hotspot-detection.\n"
            "\n"
            "Reason: The package requires compiled artifacts (LLVMHotspotDetection.so) and\n"
            "        wrapper scripts to be in specific locations. Editable mode breaks\n"
            "        relative path resolution.\n"
            "\n"
            "Solution: Use standard install instead:\n"
            "  pip install .\n"
        )

    def build_editable(wheel_directory: str, config_settings: Any = None, metadata_directory: Any = None) -> str:
        raise RuntimeError(
            "Editable installs (-e flag) are not supported for discopop-hotspot-detection.\n"
            "\n"
            "Reason: The package requires compiled artifacts (LLVMHotspotDetection.so) and\n"
            "        wrapper scripts to be in specific locations. Editable mode breaks\n"
            "        relative path resolution.\n"
            "\n"
            "Solution: Use standard install instead:\n"
            "  pip install .\n"
        )

    def prepare_metadata_for_build_editable(metadata_directory: str, config_settings: Any = None) -> str:
        raise RuntimeError(
            "Editable installs (-e flag) are not supported for discopop-hotspot-detection.\n"
            "\n"
            "Reason: The package requires compiled artifacts (LLVMHotspotDetection.so) and\n"
            "        wrapper scripts to be in specific locations. Editable mode breaks\n"
            "        relative path resolution.\n"
            "\n"
            "Solution: Use standard install instead:\n"
            "  pip install .\n"
        )

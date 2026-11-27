# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.
"""The agent's workspace: a throwaway copy of the project sources it reads and changes. DiscoPoP computes the patch
from the changes (design/agent_checked_suggestions.md, §5.2)."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from discopop_library.PatchGenerator.diffs import get_diffs_from_modified_code
from discopop_library.PatchRepair.patching import _diff_arguments
from discopop_library.PatchRepair.patchset import PatchEntry, PatchSet
from discopop_library.ProjectManager.configurations.builds import source_entries
from discopop_library.ProjectManager.services.fingerprint_ignore import is_ignored
from discopop_library.SuggestionCheck.facts import SourceFiles, project_relative


class ProjectChanged(Exception):
    """a source file of the project itself changed while an agent was working: it left its workspace"""


class ProjectGuard:
    """the state (size, modification time) of the project's files, compared after every agent call"""

    def __init__(self, project_root: str) -> None:
        self.project_root = os.path.abspath(project_root)
        self._before = source_entries(self.project_root)

    def check(self) -> None:
        after = source_entries(self.project_root)
        changed = sorted(name for name in set(self._before) | set(after) if self._before.get(name) != after.get(name))
        if changed:
            raise ProjectChanged(
                "the project changed while an agent was working, which must only change its copy: "
                + ", ".join(changed[:10])
                + (" ..." if len(changed) > 10 else "")
            )


@dataclass
class Changes:
    # file id -> the changed content of a file with a file id
    mapped: Dict[int, str] = field(default_factory=dict)
    # changed, added or removed files without a file id, relative to the project root
    unmapped: List[str] = field(default_factory=list)


class Workspace:
    """a copy of the project's files (those git knows of, or all outside .discopop and .git), without those matching
    one of the ignore patterns (the project's fingerprint_ignore.json, e.g. a build directory inside the project),
    and every source file with a file id inside the project root (also one git ignores or a pattern names)"""

    def __init__(
        self,
        project_root: str,
        files: SourceFiles,
        prefix: str = "discopop_suggestion_check_",
        ignore: Sequence[str] = (),
    ) -> None:
        # resolved, like the paths of the file mapping in relative(): a project reached through a symbolic link, or
        # a file mapping recorded under another path to the same files, must still match
        self.project_root = os.path.realpath(project_root)
        self.files = files
        self.root = tempfile.mkdtemp(prefix=prefix)
        self._copied: Dict[str, Tuple[int, int]] = dict()
        try:
            self._copy(ignore)
        except BaseException:
            # nobody gets the workspace to remove
            self.remove()
            raise

    def _copy(self, ignore: Sequence[str]) -> None:
        mapped = {name for path in self.files.file_mapping.values() if (name := self.relative(path)) is not None}
        names = set(source_entries(self.project_root))
        # every mapped source file inside the root, also one git ignores (e.g. generated, or listed in .gitignore):
        # the agent must be able to open and change each of them
        names |= {name for name in mapped if name.split(os.sep)[0] not in (".discopop", ".git")}
        for name in sorted(names):
            source = os.path.join(self.project_root, name)
            if not os.path.isfile(source):
                continue
            if ignore and name not in mapped and is_ignored(name.replace(os.sep, "/"), ignore):
                continue
            target = os.path.join(self.root, name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
            stat = os.stat(target)
            self._copied[name] = (stat.st_size, stat.st_mtime_ns)

    def relative(self, original: Path) -> Optional[str]:
        """the path of a project file relative to the project root, None outside it"""
        return project_relative(original, self.project_root)

    def write(self, changes: Dict[int, str]) -> None:
        """puts changed contents of files with a file id into the copy, e.g. for the review"""
        for file_id, content in changes.items():
            relative = self.relative(self.files.file_mapping[file_id])
            if relative is None:
                raise ValueError("file " + str(file_id) + " is outside the project")
            with open(os.path.join(self.root, relative), "w", newline="") as f:
                f.write(content)

    def changes(self) -> Changes:
        ids_by_name = {
            name: file_id
            for file_id, path in self.files.file_mapping.items()
            if (name := self.relative(path)) is not None
        }
        result = Changes()
        present = set()
        for directory, subdirectories, names in os.walk(self.root):
            for name in names:
                present.add(os.path.relpath(os.path.join(directory, name), self.root))
        for name in sorted(present | set(self._copied)):
            copy = os.path.join(self.root, name)
            original = os.path.join(self.project_root, name)
            if name not in present or name not in self._copied:
                result.unmapped.append(name)
                continue
            stat = os.stat(copy)
            if (stat.st_size, stat.st_mtime_ns) == self._copied[name] or _same_content(copy, original):
                continue
            file_id = ids_by_name.get(name)
            if file_id is None:
                result.unmapped.append(name)
            else:
                with open(copy, "r", newline="", errors="surrogateescape") as f:
                    result.mapped[file_id] = f.read()
        return result

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def _same_content(a: str, b: str) -> bool:
    try:
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def patch_of(changes: Dict[int, str], files: SourceFiles, suggestion_id: int) -> PatchSet:
    """the patch from the original files to the changed ones, with the patch generator's own diffing"""
    # the changed files are written to a scratch directory, not next to the originals: the check never writes into
    # the project, not even briefly
    with tempfile.TemporaryDirectory(prefix="discopop_suggestion_check_diff_") as scratch:
        diffs = get_diffs_from_modified_code(dict(files.file_mapping), changes, _diff_arguments(), Path(scratch))
    patch = PatchSet(suggestion_id=suggestion_id)
    for file_id, text in sorted(diffs.items()):
        if text.strip():
            patch.entries[file_id] = PatchEntry(file_id, text, files.file_mapping[file_id])
    return patch

# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Turning an agent's answer into a patch set that can be trusted.

The agent answers with unified diffs, which is the one thing language models are
reliably bad at: hunk headers have to carry exact line counts, and a model that fixed
the actual compiler error will still hand back a diff that ``patch`` rejects. Two of
the steps here exist to take that burden off the model rather than spend retries on it:

* :func:`dry_run_apply` rejects a bad diff in milliseconds instead of after a compile,
  and ``patch``'s own message ("Hunk #1 FAILED at 120") is precisely what the next turn
  needs to be told.
* :func:`canonicalize` applies the answer and *re-derives* the diff with ``diff -Naru``,
  reusing the patch generator's own code. The stored patch is therefore always
  byte-identical in form to what ``discopop_patch_generator`` emits, whatever the model
  wrote -- only ``patch``'s fuzz tolerance has to carry it, not exactness.

:func:`check_pragmas_preserved` is the other half. An agent can always make a compiler
error go away by deleting the parallelization; the build then goes green and the
suggestion has silently become a no-op. Every OpenMP directive the original patch added
must still be added by the repaired one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional, Tuple

from discopop_library.PatchGenerator.PatchGeneratorArguments import PatchGeneratorArguments
from discopop_library.PatchGenerator.diffs import (
    LF,
    detect_line_terminator,
    get_diffs_from_modified_code,
)
from discopop_library.PatchRepair.patchset import PatchEntry, PatchSet

logger = logging.getLogger("PatchRepair").getChild("patching")

# The block an agent is asked to answer in. A per-file marker rather than one block for
# the whole set, so a multi-file suggestion can be answered for one file at a time.
PATCH_BLOCK = re.compile(
    r"===\s*BEGIN\s+PATCH\s+(?P<file_id>\d+)\s*===\r?\n(?P<body>.*?)\r?\n?===\s*END\s+PATCH\s+(?P=file_id)\s*===",
    re.DOTALL | re.IGNORECASE,
)

# Fallback for a single-file set: a fenced diff block, which is what a model reaches for
# when it ignores the output contract.
FENCED_DIFF = re.compile(r"```(?:diff|patch)?\r?\n(?P<body>.*?)```", re.DOTALL)

# An OpenMP directive, reduced to what must survive a repair. The clauses are
# deliberately not part of it: changing them is the expected fix.
OMP_DIRECTIVE = re.compile(
    r"#\s*pragma\s+omp\s+(?P<directive>[a-z_]+(?:\s+(?:for|simd|do|parallel|sections|taskloop))*)", re.IGNORECASE
)


class ExtractionError(ValueError):
    """The agent's answer did not contain a usable patch."""


@dataclass
class ApplyResult:
    ok: bool
    # What to tell the agent when it is not ok: patch(1)'s own output, per file.
    message: str = ""
    # Where the patched sources ended up, when the apply was for real.
    workspace: Optional[str] = None
    failed_file_ids: List[int] = field(default_factory=list)


def extract_patches(answer: str, known_file_ids: List[int]) -> Dict[int, str]:
    """The per-file diffs in an agent's answer.

    Raises :class:`ExtractionError` with a message meant for the agent when the answer
    cannot be read: an unknown file id, a duplicate block, or no block at all. Those are
    the answer's fault and the next turn can fix them, so they are reported rather than
    guessed around.
    """
    found: Dict[int, str] = {}
    for match in PATCH_BLOCK.finditer(answer or ""):
        file_id = int(match.group("file_id"))
        if file_id in found:
            raise ExtractionError(
                "The answer contains more than one patch block for file id "
                + str(file_id)
                + ". Emit exactly one block per file."
            )
        if file_id not in known_file_ids:
            raise ExtractionError(
                "The answer contains a patch block for file id "
                + str(file_id)
                + ", which is not part of this suggestion. Known file ids: "
                + ", ".join(str(i) for i in known_file_ids)
                + "."
            )
        found[file_id] = _normalize_block(match.group("body"))

    if found:
        return found

    # A single-file suggestion has only one thing the diff could be for, so a fenced
    # block is unambiguous. With several files it is not, and guessing would write a
    # patch to the wrong file.
    if len(known_file_ids) == 1:
        fences = FENCED_DIFF.findall(answer or "")
        if fences:
            return {known_file_ids[0]: _normalize_block(fences[-1])}

    raise ExtractionError(
        "The answer contains no patch block. Answer with one block per file that needs "
        "changing, in the form:\n===BEGIN PATCH <file_id>===\n<unified diff>\n===END PATCH <file_id>==="
    )


def _normalize_block(body: str) -> str:
    """Strip a fence the model may have put *inside* the block, and fix the trailer.

    A unified diff must end with a newline; ``patch`` treats a missing one as a
    truncated hunk, which would reject an otherwise perfect answer over whitespace.
    """
    text = body.strip("\r\n")
    fence = FENCED_DIFF.search(text)
    if fence is not None and text.lstrip().startswith("```"):
        text = fence.group("body").strip("\r\n")
    if text and not text.endswith("\n"):
        text += "\n"
    return text


HUNK_HEADER = re.compile(
    r"^@@\s+-(?P<old>\d+)(?:,(?P<old_count>\d+))?\s+\+(?P<new>\d+)(?:,(?P<new_count>\d+))?\s+@@", re.MULTILINE
)


def hunk_line_numbers(patch_text: str, side: str = "old") -> List[int]:
    """The first line of every hunk, on the ``old`` or ``new`` side of the diff.

    Used to window the source around what a patch touches. Only the hunk starts are
    needed: the window is widened by ``--context-lines`` anyway, and a hunk's own length
    is not what decides how much surrounding code the model needs.
    """
    numbers: List[int] = []
    for match in HUNK_HEADER.finditer(patch_text or ""):
        numbers.append(int(match.group("old" if side == "old" else "new")))
    return numbers


def apply_and_read(patch_set: PatchSet) -> Dict[int, str]:
    """The text of every file of ``patch_set`` with the set applied.

    This is what the compiler's line numbers refer to: the tuner built the patched code
    in a project copy it has since deleted, so the patched source has to be reproduced
    here for the prompt to be readable at all.
    """
    applied = apply_patch_set(patch_set, dry_run=False)
    if not applied.ok or applied.workspace is None:
        raise ValueError(applied.message or "the patch set could not be applied")
    try:
        result: Dict[int, str] = {}
        for file_id, entry in patch_set.entries.items():
            patched = Path(applied.workspace) / str(file_id) / os.path.basename(str(entry.target))
            with open(patched, "r", newline="") as f:
                result[file_id] = f.read()
        return result
    finally:
        shutil.rmtree(applied.workspace, ignore_errors=True)


def make_workspace(targets: Dict[int, Path]) -> Tuple[str, Dict[int, Path]]:
    """Copy every file a patch set touches into a temporary directory.

    Each file keeps its own subdirectory named by file id, so two files with the same
    base name cannot collide, and the originals are never touched by an apply.
    """
    workspace = tempfile.mkdtemp(prefix="discopop_patch_repair_")
    copies: Dict[int, Path] = {}
    for file_id, target in targets.items():
        destination_dir = os.path.join(workspace, str(file_id))
        os.makedirs(destination_dir, exist_ok=True)
        destination = os.path.join(destination_dir, os.path.basename(str(target)))
        shutil.copyfile(str(target), destination)
        copies[file_id] = Path(destination)
    return workspace, copies


def apply_texts(
    copies: Dict[int, Path],
    patches: Dict[int, str],
    targets: Dict[int, Path],
    workspace: str,
    dry_run: bool,
) -> Tuple[List[str], List[int]]:
    """Apply patch texts to files already copied into ``workspace``.

    Returns the per-file failure messages and the file ids they belong to, both empty
    when everything applied. ``targets`` names the pristine files, which is where the
    line terminator to match is read from.
    """
    failures: List[str] = []
    failed_file_ids: List[int] = []
    for file_id, text in sorted(patches.items()):
        patch_file = os.path.join(workspace, str(file_id) + ".patch")
        with open(patch_file, "w", newline="") as f:
            f.write(match_line_terminator(text, targets[file_id]))
        # --batch: never ask. Without it patch turns interactive on a reversed or
        # already-applied patch ("Assume -R? [n]", "Apply anyway? [n]") and, with no
        # terminal attached, reads EOF -- so the outcome depends on a prompt nobody
        # answered rather than on the patch.
        # --forward: and never guess. --batch ALONE answers that prompt with "Assuming
        # -R" and silently *reverses* the patch, returning 0 -- so a candidate that is
        # already in the file would be accepted here while having removed the very lines
        # it was supposed to add. --forward skips such a patch and fails instead, which
        # is what the gate is for.
        command = ["patch", "--batch", "--forward"]
        if dry_run:
            command.append("--dry-run")
        command += [str(copies[file_id]), patch_file]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0:
            failed_file_ids.append(file_id)
            # Both streams: patch reports "checking file X" on stdout and the reason it
            # failed ("Hunk #1 FAILED at 21") wherever it pleases, so showing only the
            # first non-empty one regularly hides the only part worth reading.
            detail = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
            failures.append(
                "file id "
                + str(file_id)
                + " ("
                + os.path.basename(str(targets[file_id]))
                + "): "
                + (detail or "patch failed")
            )
    return failures, failed_file_ids


def apply_patch_set(patch_set: PatchSet, dry_run: bool) -> ApplyResult:
    """Apply a whole patch set to a throwaway copy of its target files.

    All or nothing: if any entry is rejected the result is a failure naming it, because
    a partially applicable set is exactly the state the applicator refuses to produce.
    With ``dry_run`` the workspace is removed again and only the verdict is returned.
    """
    targets = patch_set.targets()
    workspace, copies = make_workspace(targets)
    patches = {file_id: entry.text for file_id, entry in patch_set.entries.items()}

    failures, failed_file_ids = apply_texts(copies, patches, targets, workspace, dry_run)

    if failures:
        shutil.rmtree(workspace, ignore_errors=True)
        return ApplyResult(
            ok=False,
            message="The patch could not be applied:\n" + "\n".join(failures),
            failed_file_ids=failed_file_ids,
        )

    if dry_run:
        shutil.rmtree(workspace, ignore_errors=True)
        return ApplyResult(ok=True)
    return ApplyResult(ok=True, workspace=workspace)


def canonicalize_delta(original: PatchSet, replacements: Dict[int, str]) -> Optional[PatchSet]:
    """Read the agent's diffs as changes to the *patched* code, and re-derive from there.

    The single most common way a model gets this task wrong, and it is worth catching
    rather than retrying against. What the model is shown is the broken *patched* code
    and the compiler's complaint about it, so it naturally answers with a diff that
    edits that -- removing the pragma line the patch added and adding a corrected one.
    A patch, however, has to be a diff against the *pristine* file, where that line does
    not exist yet, so ``patch`` rejects the answer outright.

    The intent is nonetheless unambiguous and recoverable: apply the original patch
    first, then the model's diff on top of it, and re-derive the diff against the
    pristine file. The result is exactly the patch the model meant to write. Returns
    None when the answer does not apply this way either, in which case it really is
    wrong rather than merely expressed against the wrong base.
    """
    applied = apply_patch_set(original, dry_run=False)
    if not applied.ok or applied.workspace is None:
        return None

    workspace = applied.workspace
    targets = original.targets()
    try:
        copies = {
            file_id: Path(workspace) / str(file_id) / os.path.basename(str(target))
            for file_id, target in targets.items()
        }
        failures, _ = apply_texts(copies, replacements, targets, workspace, dry_run=False)
        if failures:
            return None

        modified_code: Dict[int, str] = {}
        for file_id, path in copies.items():
            with open(path, "r", newline="") as f:
                modified_code[file_id] = f.read()
        diffs = get_diffs_from_modified_code(dict(targets), modified_code, _diff_arguments())
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    canonical = PatchSet(suggestion_id=original.suggestion_id)
    for file_id, entry in original.entries.items():
        canonical.entries[file_id] = PatchEntry(file_id=file_id, text=diffs.get(file_id, ""), target=entry.target)
    return canonical.without_empty()


# Lines of a unified diff that are the diff's own framing rather than file content.
# In a diff of CRLF files these still end with a plain LF -- the CR belongs to the
# content lines, where it is part of what is compared. A content line starts with
# " ", "-" or "+", so of these only "---" and "+++" can also be content (a removed
# "--i;", an added "++count;"); see :func:`_framing_lines`.
DIFF_FRAMING_PREFIXES = ("---", "+++", "@@", "diff ", "index ", "\\")


def _framing_lines(lines: List[str]) -> List[bool]:
    """For every line of a unified diff, whether it is framing rather than content.

    Everything up to the first hunk header is framing. After it, a "---" line is a file
    header only when it opens the "---" / "+++" / "@@" triple that starts the next file;
    any other "---" or "+++" line is a removed or added content line. The hunk headers'
    line counts are not used for this: an agent's counts are often wrong, while the
    triple is what ``patch`` itself needs to see.
    """
    framing: List[bool] = []
    seen_hunk = False
    in_header = False  # inside a recognized file header, up to its first hunk
    for index, line in enumerate(lines):
        if line.startswith("@@"):
            seen_hunk = True
            in_header = False
            framing.append(True)
        elif not seen_hunk or in_header:
            framing.append(line.startswith(DIFF_FRAMING_PREFIXES))
        elif line.startswith(("diff ", "index ", "\\")):
            framing.append(True)
        elif (
            line.startswith("---")
            and index + 2 < len(lines)
            and lines[index + 1].startswith("+++")
            and lines[index + 2].startswith("@@")
        ):
            in_header = True
            framing.append(True)
        else:
            framing.append(False)
    return framing


def match_line_terminator(patch_text: str, target: Path) -> str:
    """Give a patch's *content* lines the line terminator its target file uses.

    ``patch`` compares context lines byte for byte, so a diff whose content lines end
    in LF is rejected outright against a CRLF source ("Hunk #1 FAILED ... (different
    line endings)"). An agent writes LF whatever the file does, which would make every
    answer fail on a CRLF project -- a failure about whitespace, reported to the model
    as though it were about its fix.

    Only the content lines are converted. ``diff`` itself writes the ``---``/``+++``/
    ``@@`` framing with a plain LF even for a CRLF file, and converting those too is
    what makes ``patch`` strip every CR from the patch and then fail to match the file.
    """
    terminator = detect_line_terminator(target)
    if terminator is None or terminator == LF:
        return patch_text

    lines = [line.rstrip("\r") for line in patch_text.splitlines()]
    rebuilt: List[str] = []
    for line, is_framing in zip(lines, _framing_lines(lines)):
        rebuilt.append(line + (LF if is_framing else terminator))
    return "".join(rebuilt)


def dry_run_apply(patch_set: PatchSet) -> ApplyResult:
    """Whether the whole set applies, without changing anything."""
    return apply_patch_set(patch_set, dry_run=True)


def canonicalize(patch_set: PatchSet) -> PatchSet:
    """Re-derive every patch from the code it produces.

    Applies the set to a throwaway copy and diffs the result against the pristine
    originals with the patch generator's own ``diff -Naru``, so the stored patches carry
    correct hunk headers and each file's own line terminators whatever the agent wrote.
    Patches that turn out to change nothing are dropped: an agent's no-op edit is not
    part of the suggestion.
    """
    applied = apply_patch_set(patch_set, dry_run=False)
    if not applied.ok or applied.workspace is None:
        raise ValueError(applied.message or "the patch set could not be applied for canonicalization")

    workspace = applied.workspace
    try:
        file_mapping: Dict[int, Path] = {}
        modified_code: Dict[int, str] = {}
        for file_id, entry in sorted(patch_set.entries.items()):
            patched = Path(workspace) / str(file_id) / os.path.basename(str(entry.target))
            with open(patched, "r", newline="") as f:
                modified_code[file_id] = f.read()
            file_mapping[file_id] = entry.target

        # The generator's own diffing, so a repaired patch is indistinguishable in form
        # from a generated one.
        diffs = get_diffs_from_modified_code(file_mapping, modified_code, _diff_arguments())
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    canonical = PatchSet(suggestion_id=patch_set.suggestion_id)
    for file_id, entry in sorted(patch_set.entries.items()):
        canonical.entries[file_id] = PatchEntry(file_id=file_id, text=diffs.get(file_id, ""), target=entry.target)
    return canonical.without_empty()


def _diff_arguments() -> PatchGeneratorArguments:
    """A ``PatchGeneratorArguments`` for diffing only.

    ``get_diffs_from_modified_code`` reads exactly one field of it, ``verbose``. Its
    constructor, however, insists that the DiscoPoP build directory and both compilers
    exist -- prerequisites of *generating* patches, which is not what is happening here.
    Building the instance without running that validation keeps a repair run from
    demanding a toolchain it never invokes.
    """
    arguments = PatchGeneratorArguments.__new__(PatchGeneratorArguments)
    arguments.log_level = "WARNING"
    arguments.write_log = False
    arguments.verbose = False
    arguments.discopop_build_path = ""
    arguments.CC = ""
    arguments.CXX = ""
    arguments.add_from_json = "None"
    arguments.only_optimizer_output_patterns = False
    arguments.only_maximum_id_pattern = False
    return arguments


def directives_of(patch_text: str) -> List[str]:
    """The OpenMP directives a patch *adds*, normalized and without their clauses.

    Only added lines count: a directive that merely appears as context was already in
    the code and says nothing about what this patch contributes.
    """
    directives: List[str] = []
    for line in patch_text.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        match = OMP_DIRECTIVE.search(line[1:])
        if match is not None:
            directives.append(" ".join(match.group("directive").lower().split()))
    return sorted(directives)


def check_pragmas_preserved(original: PatchSet, candidate: PatchSet) -> Optional[str]:
    """Whether the repair kept what the suggestion was for. None means it did.

    Checked per file rather than across the set, so a directive cannot be "preserved" by
    having moved into a different translation unit. Clause changes are allowed -- adding
    ``private(...)`` is the expected fix -- but a directive that disappears turns the
    suggestion into a no-op that builds green, which is worse than an honest failure.
    """
    for file_id, entry in sorted(original.entries.items()):
        expected = directives_of(entry.text)
        if not expected:
            continue
        candidate_entry = candidate.entries.get(file_id)
        actual = directives_of(candidate_entry.text) if candidate_entry is not None else []
        missing = _missing_directives(expected, actual)
        if missing:
            return (
                "The parallelization was removed from "
                + os.path.basename(str(entry.target))
                + ": the repaired patch no longer adds "
                + ", ".join("'#pragma omp " + directive + "'" for directive in missing)
                + ". Fix the error by changing the directive's clauses, not by deleting it."
            )
    return None


def _missing_directives(expected: List[str], actual: List[str]) -> List[str]:
    """Expected directives not covered by ``actual``, counting multiplicity."""
    remaining = list(actual)
    missing: List[str] = []
    for directive in expected:
        if directive in remaining:
            remaining.remove(directive)
        else:
            missing.append(directive)
    return missing

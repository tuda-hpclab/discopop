# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Tests for turning an agent's answer into a patch set that can be trusted.

The agent writes unified diffs by hand, which is the failure mode the whole module is
built around, so these tests are mostly about what happens when it writes them badly.
"""

from pathlib import Path
from typing import Any, Dict

import pytest

from discopop_library.PatchRepair.patching import (
    ExtractionError,
    canonicalize,
    check_pragmas_preserved,
    directives_of,
    dry_run_apply,
    extract_patches,
)
from discopop_library.PatchRepair.patchset import PatchEntry, PatchSet

SOURCE = """#include <cstdio>

int main() {
  int sum = 0;
  int Arr[100];
  for (int i = 0; i < 100; i++) {
    Arr[i] = i % 13;
  }
  for (int i = 0; i < 100; i++) {
    sum += Arr[i];
  }
  printf("%d\\n", sum);
  return 0;
}
"""


def _write_source(tmp_path: Path, text: str = SOURCE, name: str = "example.cpp") -> Path:
    path = tmp_path / name
    path.write_text(text)
    return path


def _patch_set(target: Path, text: str, file_id: int = 0, suggestion_id: int = 7) -> PatchSet:
    patch_set = PatchSet(suggestion_id=suggestion_id)
    patch_set.entries[file_id] = PatchEntry(file_id=file_id, text=text, target=target)
    return patch_set


# A diff whose hunk header is correct: 4 old lines (8-11), 5 new ones.
GOOD_DIFF = """--- a/example.cpp
+++ b/example.cpp
@@ -8,4 +8,5 @@
   }
+  #pragma omp parallel for reduction(+:sum)
   for (int i = 0; i < 100; i++) {
     sum += Arr[i];
   }
"""


# -- extraction ----------------------------------------------------------------


def test_a_delimited_block_is_extracted() -> None:
    answer = "Here is the fix.\n\n===BEGIN PATCH 3===\n" + GOOD_DIFF + "===END PATCH 3===\n\nHope that helps."
    assert extract_patches(answer, [3]) == {3: GOOD_DIFF}


def test_several_files_are_extracted_independently() -> None:
    answer = (
        "===BEGIN PATCH 3===\n"
        + GOOD_DIFF
        + "===END PATCH 3===\n===BEGIN PATCH 5===\n"
        + GOOD_DIFF
        + "===END PATCH 5==="
    )
    assert sorted(extract_patches(answer, [3, 5, 9])) == [3, 5]


def test_a_file_the_agent_did_not_answer_for_is_simply_absent() -> None:
    # the merge in PatchSet.with_replacements then keeps its original patch
    answer = "===BEGIN PATCH 3===\n" + GOOD_DIFF + "===END PATCH 3==="
    assert list(extract_patches(answer, [3, 5])) == [3]


def test_an_unknown_file_id_is_reported_rather_than_guessed_around() -> None:
    answer = "===BEGIN PATCH 99===\n" + GOOD_DIFF + "===END PATCH 99==="
    with pytest.raises(ExtractionError, match="not part of this suggestion"):
        extract_patches(answer, [3])


def test_two_blocks_for_one_file_are_refused() -> None:
    answer = (
        "===BEGIN PATCH 3===\n"
        + GOOD_DIFF
        + "===END PATCH 3===\n===BEGIN PATCH 3===\n"
        + GOOD_DIFF
        + "===END PATCH 3==="
    )
    with pytest.raises(ExtractionError, match="more than one patch block"):
        extract_patches(answer, [3])


def test_a_fenced_diff_is_accepted_for_a_single_file_suggestion() -> None:
    """A model that ignores the output contract still has an unambiguous answer here."""
    answer = "Sure:\n\n```diff\n" + GOOD_DIFF + "```\n"
    assert extract_patches(answer, [3]) == {3: GOOD_DIFF}


def test_a_fenced_diff_is_not_guessed_at_for_a_multi_file_suggestion() -> None:
    # writing it to the wrong file would be silent corruption
    answer = "```diff\n" + GOOD_DIFF + "```"
    with pytest.raises(ExtractionError, match="no patch block"):
        extract_patches(answer, [3, 5])


def test_an_answer_without_any_patch_is_reported() -> None:
    with pytest.raises(ExtractionError, match="no patch block"):
        extract_patches("I could not work out what is wrong.", [3])


def test_a_block_missing_its_trailing_newline_is_repaired() -> None:
    """patch(1) reads a diff that does not end in a newline as a truncated hunk."""
    answer = "===BEGIN PATCH 3===\n" + GOOD_DIFF.rstrip("\n") + "\n===END PATCH 3==="
    assert extract_patches(answer, [3])[3].endswith("\n")


# -- applying ------------------------------------------------------------------


def test_a_correct_diff_applies(tmp_path: Path) -> None:
    target = _write_source(tmp_path)
    assert dry_run_apply(_patch_set(target, GOOD_DIFF)).ok


def test_a_dry_run_does_not_touch_the_original(tmp_path: Path) -> None:
    target = _write_source(tmp_path)
    dry_run_apply(_patch_set(target, GOOD_DIFF))
    assert target.read_text() == SOURCE


def test_wrong_line_numbers_still_apply_through_patch_fuzz(tmp_path: Path) -> None:
    """The agent only has to be close; exactness is re-derived in canonicalize()."""
    target = _write_source(tmp_path)
    shifted = GOOD_DIFF.replace("@@ -8,4 +8,5 @@", "@@ -40,4 +40,5 @@")
    assert dry_run_apply(_patch_set(target, shifted)).ok


# Context that appears nowhere in the file. patch(1) tolerates up to two mismatched
# context lines (its default fuzz), which is deliberately left alone -- an approximate
# diff that lands is then re-derived by canonicalize() and verified by the compiler --
# so a test for rejection has to miss by more than that.
UNAPPLICABLE_DIFF = """--- a/example.cpp
+++ b/example.cpp
@@ -8,4 +8,5 @@
   completely_different_line_one();
+  #pragma omp parallel for reduction(+:sum)
   completely_different_line_two();
   completely_different_line_three();
   completely_different_line_four();
"""


def test_a_hunk_that_matches_nothing_is_rejected_with_patchs_own_message(tmp_path: Path) -> None:
    target = _write_source(tmp_path)
    result = dry_run_apply(_patch_set(target, UNAPPLICABLE_DIFF))
    assert not result.ok
    assert result.failed_file_ids == [0]
    assert "file id 0" in result.message


def test_one_rejected_entry_fails_the_whole_set(tmp_path: Path) -> None:
    """The applicator refuses to half-apply a suggestion, so the repair tool must too."""
    first = _write_source(tmp_path, name="a.cpp")
    second = _write_source(tmp_path, name="b.cpp")
    patch_set = PatchSet(suggestion_id=7)
    patch_set.entries[0] = PatchEntry(0, GOOD_DIFF, first)
    patch_set.entries[1] = PatchEntry(1, UNAPPLICABLE_DIFF, second)

    result = dry_run_apply(patch_set)

    assert not result.ok
    assert result.failed_file_ids == [1]


def test_files_with_the_same_base_name_do_not_collide(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "y").mkdir()
    first = _write_source(tmp_path / "x")
    second = _write_source(tmp_path / "y")
    patch_set = PatchSet(suggestion_id=7)
    patch_set.entries[0] = PatchEntry(0, GOOD_DIFF, first)
    patch_set.entries[1] = PatchEntry(1, GOOD_DIFF, second)

    assert dry_run_apply(patch_set).ok


# -- canonicalization ----------------------------------------------------------


def test_canonicalization_rewrites_a_wrong_hunk_header(tmp_path: Path) -> None:
    target = _write_source(tmp_path)
    shifted = GOOD_DIFF.replace("@@ -8,4 +8,5 @@", "@@ -40,4 +40,5 @@")

    canonical = canonicalize(_patch_set(target, shifted))

    assert "@@ -40,4 +40,5 @@" not in canonical.entries[0].text
    assert "#pragma omp parallel for reduction(+:sum)" in canonical.entries[0].text
    # and the result is what patch(1) will accept against the pristine file
    assert dry_run_apply(canonical).ok


def test_canonicalization_preserves_crlf_line_endings(tmp_path: Path) -> None:
    """A CRLF file diffed as LF makes patch reject the whole thing."""
    target = tmp_path / "crlf.cpp"
    target.write_bytes(SOURCE.replace("\n", "\r\n").encode())

    canonical = canonicalize(_patch_set(target, GOOD_DIFF))

    assert b"\r\n" in canonical.entries[0].text.encode()
    assert dry_run_apply(canonical).ok


def test_a_no_op_edit_is_dropped_from_the_set(tmp_path: Path) -> None:
    target = _write_source(tmp_path)
    empty_patch = _patch_set(target, "")
    # an empty diff applies trivially and changes nothing
    assert canonicalize(empty_patch).entries == {}


# -- the pragma guard ----------------------------------------------------------


def test_directives_are_read_from_added_lines_only() -> None:
    patch = "--- a\n+++ b\n@@ -1,2 +1,3 @@\n #pragma omp parallel for\n+#pragma omp simd\n"
    # the context line was already in the code and is not what this patch contributes
    assert directives_of(patch) == ["simd"]


def test_clauses_do_not_change_a_directives_identity() -> None:
    original = "+#pragma omp parallel for reduction(+:sum)\n"
    repaired = "+#pragma omp parallel for reduction(+:sum) private(i) firstprivate(N)\n"
    assert directives_of(original) == directives_of(repaired)


def test_adding_clauses_is_accepted(tmp_path: Path) -> None:
    target = _write_source(tmp_path)
    original = _patch_set(target, GOOD_DIFF)
    repaired = _patch_set(target, GOOD_DIFF.replace("reduction(+:sum)", "reduction(+:sum) private(i)"))
    assert check_pragmas_preserved(original, repaired) is None


def test_deleting_the_directive_is_refused(tmp_path: Path) -> None:
    """Otherwise the build goes green and the suggestion is silently a no-op."""
    target = _write_source(tmp_path)
    original = _patch_set(target, GOOD_DIFF)
    gutted = _patch_set(target, GOOD_DIFF.replace("+  #pragma omp parallel for reduction(+:sum)\n", ""))

    message = check_pragmas_preserved(original, gutted)

    assert message is not None
    assert "parallelization was removed" in message


def test_dropping_one_file_of_a_set_is_refused(tmp_path: Path) -> None:
    """A directive cannot be 'preserved' by having moved into another file."""
    first = _write_source(tmp_path, name="a.cpp")
    second = _write_source(tmp_path, name="b.cpp")
    original = PatchSet(suggestion_id=7)
    original.entries[0] = PatchEntry(0, GOOD_DIFF, first)
    original.entries[1] = PatchEntry(1, GOOD_DIFF, second)
    candidate = PatchSet(suggestion_id=7)
    candidate.entries[0] = PatchEntry(0, GOOD_DIFF, first)

    assert check_pragmas_preserved(original, candidate) is not None


def test_a_patch_that_adds_no_directive_is_not_guarded(tmp_path: Path) -> None:
    # nothing to preserve, so the guard must not invent a requirement
    target = _write_source(tmp_path)
    plain = _patch_set(target, "--- a\n+++ b\n@@ -1,1 +1,2 @@\n+int x = 0;\n")
    assert check_pragmas_preserved(plain, _patch_set(target, "")) is None

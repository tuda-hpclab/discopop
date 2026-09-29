# This file is part of the DiscoPoP software (http://www.discopop.tu-darmstadt.de)
#
# Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
#
# This software may be modified and distributed under the terms of
# the 3-Clause BSD License.  See the LICENSE file in the package base
# directory for details.

"""Repairing one suggestion: the attempt loop and its gates.

Two nested budgets, and the distinction matters:

* ``--prompts`` -- independent **attempts**, each starting a fresh conversation and
  using the next rung of the prompt ladder. A later attempt asks a *better question*,
  not the same one again.
* ``--retries`` -- follow-up **turns** inside one attempt. The conversation continues,
  so the model sees its own previous answer and is told only what was wrong with it.

A candidate passes six gates, cheapest first (see
:mod:`discopop_library.PatchRepair.patching`), and every rejection is phrased for the
agent, because it becomes the next turn's input. Nothing is written to
``patch_generator/`` until a candidate has passed all six.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from discopop_library.PatchRepair import llm_backends
from discopop_library.PatchRepair.PatchRepairArguments import PatchRepairArguments
from discopop_library.PatchRepair.backups import backup_patch_set, record_written_patch_set
from discopop_library.PatchRepair.candidates import Candidate
from discopop_library.PatchRepair.compilation import CompileCheckError, CompileOutcome, run_compile_check
from discopop_library.PatchRepair.diagnostics import implicated_file_ids, parse_diagnostics
from discopop_library.PatchRepair.patching import (
    ExtractionError,
    apply_and_read,
    canonicalize,
    canonicalize_delta,
    check_pragmas_preserved,
    dry_run_apply,
    extract_patches,
    hunk_line_numbers,
)
from discopop_library.PatchRepair.patchset import (
    PatchSet,
    load_patch_set,
    restore_patch_dir,
    snapshot_patch_dir,
    write_patch_set,
)
from discopop_library.PatchRepair.prompts import (
    PromptContext,
    load_pattern_metadata,
    render,
    render_retry,
    template_for_attempt,
)
from discopop_library.PatchRepair.results import (
    STATUS_FAILED,
    STATUS_REPAIRED,
    STATUS_UNREACHABLE,
    ProgressReporter,
    SuggestionRecord,
)
from discopop_library.PathManagement.PathManagement import load_file_mapping

logger = logging.getLogger("PatchRepair").getChild("loop")

# Gate names, as they appear in the progress channel and the attempt transcripts. They
# are what makes a failing run diagnosable without reading every transcript.
GATE_AGENT = "agent"
GATE_EXTRACTION = "extraction"
GATE_APPLY = "apply"
GATE_CANONICALIZE = "canonicalize"
GATE_PRAGMAS = "pragmas"
GATE_COMPILE = "compile"
GATE_ACCEPTED = "accepted"

# Appended when a candidate applies to neither the pristine nor the patched code, so
# the next turn is told about the distinction rather than left to guess at it again.
_BASE_REMINDER = (
    "Remember that your diff must apply to the ORIGINAL, UNPATCHED file. The patch "
    "shown to you ADDS the OpenMP directive; the original file does not contain it. "
    "To change the directive, change the '+' line inside the patch -- do not write a "
    "diff that removes the directive and adds a corrected one, because the original "
    "file has no directive to remove."
)


def repair_suggestion(
    arguments: PatchRepairArguments,
    candidate: Candidate,
    outcome: CompileOutcome,
    reporter: ProgressReporter,
    profile: Dict[str, object],
) -> SuggestionRecord:
    """Try to repair one suggestion's patch set, and report what happened."""
    started = time.time()
    suggestion_id = candidate.suggestion_id
    record = SuggestionRecord(
        suggestion_id=suggestion_id,
        hotspot_type=candidate.hotspot_type,
        status=STATUS_FAILED,
        backend=llm_backends.backend_of(profile),
        model=str(profile.get("model") or "") or None,
        first_error=outcome.first_error(),
    )

    file_mapping = load_file_mapping(os.path.join(arguments.dot_dp_path, "FileMapping.txt"))
    original = load_patch_set(arguments.patch_generator_path, suggestion_id, file_mapping)
    record.files = original.file_ids
    if not original.entries:
        logger.warning("Suggestion " + str(suggestion_id) + " has no usable patch; skipping it.")
        record.duration_s = time.time() - started
        return record

    try:
        context = _build_context(arguments, suggestion_id, original, outcome, file_mapping)
    except ValueError as error:
        # The original patch set no longer applies, so there is no patched code to show
        # and no compiler error to repair: a different failure with a different fix.
        logger.error("Suggestion " + str(suggestion_id) + ": " + str(error))
        record.first_error = str(error)
        record.duration_s = time.time() - started
        return record

    module = llm_backends.for_profile(profile)
    _run_turns(arguments, context, original, record, module, profile, reporter, suggestion_id)
    record.duration_s = time.time() - started
    reporter.suggestion(record)
    return record


def _run_turns(
    arguments: PatchRepairArguments,
    context: PromptContext,
    original: PatchSet,
    record: SuggestionRecord,
    module: Any,
    profile: Dict[str, object],
    reporter: ProgressReporter,
    suggestion_id: int,
) -> SuggestionRecord:
    """Spend the budget on one suggestion, filling in ``record``.

    Separated from :func:`repair_suggestion` so the accounting can be tested without an
    agent: which calls are charged to ``--prompts`` x ``--retries`` is the part of this
    module most likely to regress silently (see test_budget.py).
    """
    # Two counters, because not every agent call is an attempt at repairing anything.
    # ``charged`` is what --prompts x --retries and --max-attempts bound: calls the
    # model actually answered. ``calls`` counts every invocation, answered or not, and
    # is what numbers the artifact directories.
    charged = 0
    calls = 0
    unanswered = 0

    for attempt in range(1, arguments.prompts + 1):
        if charged >= arguments.max_attempts:
            break
        template = template_for_attempt(attempt, arguments.prompt_dir)
        message = render(
            context,
            template,
            context_lines=arguments.context_lines,
            max_error_chars=arguments.max_error_chars,
            max_prompt_chars=arguments.max_prompt_chars,
            prompt_dir=arguments.prompt_dir,
        )
        session: Optional[str] = None
        new_session = module.new_session_id()

        for turn in range(0, arguments.retries + 1):
            if charged >= arguments.max_attempts:
                break

            # A call that never delivers an answer is repeated in place: the model has
            # not been asked yet, so neither this turn nor this attempt has been used
            # up. Its own allowance bounds the repetition, so an agent that is simply
            # down ends the suggestion instead of looping.
            while True:
                calls += 1
                record.attempts = calls
                artifacts = _attempt_dir(arguments, suggestion_id, calls)

                accepted, failure, canonical, answered = _one_turn(
                    arguments,
                    module,
                    profile,
                    message,
                    original,
                    context,
                    session,
                    new_session,
                    artifacts,
                    reporter,
                    suggestion_id,
                    calls,
                    turn,
                    template,
                )
                if answered:
                    charged += 1
                    break
                unanswered += 1
                record.unanswered = unanswered
                if unanswered > arguments.agent_error_retries:
                    # Nothing about the patch has been learned, and saying "no fix was
                    # found" would attribute the endpoint's failure to the model.
                    logger.warning(
                        "Suggestion "
                        + str(suggestion_id)
                        + ": the agent produced no answer in "
                        + str(unanswered)
                        + " call(s); giving up on it. Last failure: "
                        + failure
                    )
                    record.status = STATUS_UNREACHABLE
                    return record
                # A new conversation: the failed call may have left a half-started one
                # behind, and there is no answer to follow up on in any case.
                new_session = module.new_session_id()

            if accepted and canonical is not None:
                _write_back(arguments, original, canonical, record)
                record.status = STATUS_REPAIRED
                record.accepted_attempt = calls
                return record

            session = _session_after(artifacts, session, new_session)
            if session is None:
                # Without a session id the conversation cannot be continued, so a
                # follow-up turn would silently be a fresh attempt asked with the retry
                # template -- which says "that did not work" to a model with no "that".
                logger.debug("No session to continue for suggestion " + str(suggestion_id) + "; starting over.")
                break
            message = render_retry(failure, original.file_ids, arguments.prompt_dir)

    return record


def _one_turn(
    arguments: PatchRepairArguments,
    module: object,
    profile: Dict[str, object],
    message: str,
    original: PatchSet,
    context: PromptContext,
    session: Optional[str],
    new_session: Optional[str],
    artifacts: str,
    reporter: ProgressReporter,
    suggestion_id: int,
    attempt: int,
    turn: int,
    template: str,
) -> Tuple[bool, str, Optional[PatchSet], bool]:
    """One agent call and the six gates.

    Returns ``(accepted, failure text, patch set, answered)``. ``answered`` is False
    only when the call produced nothing to judge -- the agent was unreachable, reported
    an error about itself, or did not answer in time. The caller does not charge such a
    call to the repair budget, because the model was never asked.
    """

    def reject(gate: str, detail: str, answered: bool = True) -> Tuple[bool, str, None, bool]:
        _write_text(os.path.join(artifacts, "rejection.txt"), gate + ": " + detail)
        reporter.attempt(suggestion_id, attempt, turn, template, gate, detail)
        logger.info("Suggestion " + str(suggestion_id) + " attempt " + str(attempt) + " rejected at " + gate)
        return False, detail, None, answered

    _write_text(os.path.join(artifacts, "prompt.txt"), message)

    # The agent runs in an empty throwaway directory, never in the project. It is given
    # everything it needs in the prompt and is asked for text, so it has no reason to
    # touch a file -- but a coding agent pointed at a project will reach for its edit
    # tool anyway, and opencode scopes itself to (and can write in) the directory it is
    # run in. Handing it the project would let a "fix" land in the user's sources
    # instead of in the patch, silently and outside everything the gates below check.
    sandbox = tempfile.mkdtemp(prefix="discopop_patch_repair_agent_")
    try:
        invocation = llm_backends.run_agent(
            module,
            profile,
            message,
            cwd=sandbox,
            timeout=arguments.agent_timeout,
            session=session,
            new_session=new_session,
        )
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)
    _write_text(os.path.join(artifacts, "response.txt"), invocation.text)
    if invocation.raw and invocation.raw != invocation.text:
        _write_text(os.path.join(artifacts, "events.jsonl"), invocation.raw)
    if invocation.session_id:
        _write_text(os.path.join(artifacts, "session.txt"), invocation.session_id)

    if not invocation.ok:
        # Not the model's fault and not an answer: there is nothing to tell it and
        # nothing to judge, so the call is reported but not charged to the budget.
        return reject(GATE_AGENT, invocation.failure_reason(), answered=False)

    # -- gate 1: extraction
    try:
        replacements = extract_patches(invocation.text, original.file_ids)
    except ExtractionError as error:
        return reject(GATE_EXTRACTION, str(error))
    _write_patch_dir(os.path.join(artifacts, "candidate"), replacements)

    candidate_set = original.with_replacements(replacements)

    # -- gate 2: does the whole set apply to the pristine code?
    applied = dry_run_apply(candidate_set)
    if applied.ok:
        # -- gates 3 and 4: apply for real and re-derive the diffs
        try:
            canonical = canonicalize(candidate_set)
        except ValueError as error:
            return reject(GATE_CANONICALIZE, str(error))
    else:
        # The answer may still be right and merely expressed against the wrong base:
        # the model is shown the broken *patched* code, so it tends to answer with a
        # diff that edits that rather than one against the pristine file. That intent is
        # recoverable, and catching it here is worth far more than spending a retry
        # explaining the distinction again.
        canonical_delta = canonicalize_delta(original, replacements)
        if canonical_delta is None:
            return reject(GATE_APPLY, applied.message + "\n\n" + _BASE_REMINDER)
        logger.info(
            "Suggestion "
            + str(suggestion_id)
            + " attempt "
            + str(attempt)
            + ": read the answer as a change to the patched code and re-derived the patch."
        )
        reporter.attempt(suggestion_id, attempt, turn, template, GATE_APPLY, "interpreted as a delta")
        canonical = canonical_delta
    _write_patch_dir(
        os.path.join(artifacts, "canonical"), {fid: entry.text for fid, entry in canonical.entries.items()}
    )

    # -- gate 5: is the parallelization still there?
    pragma_failure = check_pragmas_preserved(original, canonical)
    if pragma_failure is not None:
        return reject(GATE_PRAGMAS, pragma_failure)

    # -- gate 6: does it compile? The only gate that costs a build, so it runs last.
    try:
        verification = _verify_by_building(arguments, original, canonical)
    except CompileCheckError as error:
        return reject(GATE_COMPILE, "the verification build could not be performed: " + str(error))

    if verification is None or not verification.built:
        stderr = verification.stderr if verification is not None else ""
        _write_text(os.path.join(artifacts, "compile_stderr.txt"), stderr)
        context.diagnostics_text = stderr
        context.diagnostics = parse_diagnostics(stderr, original.targets())
        context.implicated_file_ids = implicated_file_ids(context.diagnostics)
        return reject(GATE_COMPILE, "It still does not compile:\n\n" + stderr.strip())

    reporter.attempt(suggestion_id, attempt, turn, template, GATE_ACCEPTED, "")
    return True, "", canonical, True


def _verify_by_building(
    arguments: PatchRepairArguments, original: PatchSet, canonical: PatchSet
) -> Optional[CompileOutcome]:
    """Build ``canonical`` through the autotuner and return what the compiler said.

    The candidate has to be on disk for that (see :func:`_stage_for_verification`), so
    every way out of here -- a failed build, a :class:`CompileCheckError`, Ctrl+C during
    the build or any other error -- puts ``patch_generator/<id>/`` back byte for byte,
    unless the candidate built. Under ``--dry-run`` even one that built is taken out
    again right away.
    """
    suggestion_id = original.suggestion_id
    snapshot = snapshot_patch_dir(arguments.patch_generator_path, suggestion_id)
    keep = False
    try:
        _stage_for_verification(arguments, original, canonical)
        report = run_compile_check(arguments, [suggestion_id])
        verification = report.outcomes.get(suggestion_id)
        keep = verification is not None and verification.built and not arguments.dry_run
        return verification
    finally:
        if not keep:
            restore_patch_dir(arguments.patch_generator_path, suggestion_id, snapshot)


def _build_context(
    arguments: PatchRepairArguments,
    suggestion_id: int,
    patch_set: PatchSet,
    outcome: CompileOutcome,
    file_mapping: Dict[int, Path],
) -> PromptContext:
    """Everything the prompt can be built from, gathered once per suggestion."""
    diagnostics = parse_diagnostics(outcome.stderr, file_mapping)
    pattern = load_pattern_metadata(arguments.dot_dp_path, suggestion_id)

    original_sources: Dict[int, str] = {}
    for file_id, entry in patch_set.entries.items():
        with open(entry.target, "r", newline="") as f:
            original_sources[file_id] = f.read()

    # The compiler's line numbers are in post-patch coordinates, and the build tree they
    # came from is gone, so the patched code is reproduced here.
    patched_sources = apply_and_read(patch_set)

    touched: Dict[int, List[int]] = {}
    for file_id, entry in patch_set.entries.items():
        touched[file_id] = hunk_line_numbers(entry.text, side="old")

    return PromptContext(
        suggestion_id=suggestion_id,
        pattern_type=str((pattern or {}).get("pattern_type") or "unknown"),
        patch_set=patch_set,
        original_sources=original_sources,
        patched_sources=patched_sources,
        diagnostics_text=outcome.stderr,
        diagnostics=diagnostics,
        implicated_file_ids=implicated_file_ids(diagnostics),
        pattern=pattern,
        touched_lines=touched,
    )


def _stage_for_verification(arguments: PatchRepairArguments, original: PatchSet, canonical: PatchSet) -> None:
    """Put the candidate into patch_generator/ so the autotuner builds *it*.

    The tuner reads the patches from disk, so a candidate can only be verified by being
    written there. The original is backed up first and restored when the candidate turns
    out not to build, so a rejected candidate never survives the attempt -- including
    under ``--dry-run``, where the file must end the run exactly as it started.
    """
    backup_patch_set(arguments.patch_repair_path, arguments.patch_generator_path, original.suggestion_id)
    write_patch_set(arguments.patch_generator_path, canonical)


def _write_back(
    arguments: PatchRepairArguments, original: PatchSet, canonical: PatchSet, record: SuggestionRecord
) -> None:
    """Keep the accepted candidate, or put the original back under --dry-run."""
    record.changed_files = canonical.changed_against(original)
    if arguments.dry_run:
        # The original was already put back right after the verification build.
        logger.info("Suggestion " + str(original.suggestion_id) + " could be repaired; not written (--dry-run).")
        return
    # Already on disk from the verification build; nothing further to write. Recorded so
    # a later backup or restore can tell this set from one the patch generator wrote.
    record_written_patch_set(arguments.patch_repair_path, arguments.patch_generator_path, original.suggestion_id)
    logger.info(
        "Suggestion "
        + str(original.suggestion_id)
        + " repaired; rewrote patch(es) for file id(s) "
        + str(record.changed_files)
    )


def _session_after(artifacts: str, session: Optional[str], new_session: Optional[str]) -> Optional[str]:
    """The session the next turn should continue.

    A backend that names its own sessions reports the id in its event stream, which is
    written to the attempt directory; one that lets the caller name it keeps the id it
    was given.
    """
    if session:
        return session
    recorded = os.path.join(artifacts, "session.txt")
    if os.path.exists(recorded):
        with open(recorded, "r") as f:
            text = f.read().strip()
        if text:
            return text
    return new_session


def _attempt_dir(arguments: PatchRepairArguments, suggestion_id: int, attempt: int) -> str:
    path = os.path.join(arguments.patch_repair_path, "attempts", str(suggestion_id), str(attempt))
    if os.path.exists(path):
        shutil.rmtree(path, ignore_errors=True)
    os.makedirs(path, exist_ok=True)
    return path


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _write_patch_dir(path: str, patches: Dict[int, str]) -> None:
    os.makedirs(path, exist_ok=True)
    for file_id, text in patches.items():
        with open(os.path.join(path, str(file_id) + ".patch"), "w", newline="") as f:
            f.write(text)
